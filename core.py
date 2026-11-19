"""Ядро MaisonAI: пути, база данных SQLite, файлы пользователей, очередь фоновых задач с прогрессом."""
import json, mimetypes, os, sqlite3, sys, threading, time, traceback, uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

HERE = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
DATA = Path(os.environ.get("MAISONAI_DATA") or HERE / "data")
FILES = DATA / "files"
TMP = DATA / "tmp"
DB = DATA / "maisonai.db"
for p in (DATA, FILES, TMP): p.mkdir(parents=True, exist_ok=True)
ASSETS = HERE / "assets"
VERSION = "4.0.0"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, pass TEXT NOT NULL,
  display_name TEXT, prefs TEXT DEFAULT '{}', created TEXT DEFAULT (datetime('now')), last_login TEXT);
CREATE TABLE IF NOT EXISTS sessions(h TEXT PRIMARY KEY, user_id INTEGER NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS projects(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, title TEXT NOT NULL,
  kind TEXT DEFAULT 'general', data TEXT DEFAULT '{}', favorite INTEGER DEFAULT 0,
  created TEXT DEFAULT (datetime('now')), updated TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS assets(id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, project_id INTEGER,
  kind TEXT NOT NULL, name TEXT, path TEXT NOT NULL, mime TEXT, size INTEGER, meta TEXT DEFAULT '{}',
  favorite INTEGER DEFAULT 0, created TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, project_id INTEGER, tool TEXT NOT NULL,
  title TEXT, params TEXT DEFAULT '{}', status TEXT DEFAULT 'queued', progress REAL DEFAULT 0, message TEXT DEFAULT '',
  result TEXT, error TEXT, provider TEXT, favorite INTEGER DEFAULT 0,
  created REAL, started REAL, finished REAL);
CREATE TABLE IF NOT EXISTS chats(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, project_id INTEGER,
  role TEXT NOT NULL, content TEXT NOT NULL, meta TEXT DEFAULT '{}', created TEXT DEFAULT (datetime('now')));
CREATE INDEX IF NOT EXISTS ix_assets_user ON assets(user_id, created);
CREATE INDEX IF NOT EXISTS ix_jobs_user ON jobs(user_id, created);
CREATE INDEX IF NOT EXISTS ix_chats ON chats(user_id, project_id, id);
"""

@contextmanager
def db():
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    try:
        yield c; c.commit()
    finally:
        c.close()

def init_db():
    with db() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(SCHEMA)
        # задачи, прерванные выключением программы, не должны «висеть» вечно
        c.execute("UPDATE jobs SET status='error', error='Программа была закрыта во время выполнения. Запустите задачу снова.' WHERE status IN ('queued','running')")

def row(r): return dict(r) if r is not None else None
def rows(rs): return [dict(r) for r in rs]
def jload(s, default=None):
    try: return json.loads(s) if s else (default if default is not None else {})
    except Exception: return default if default is not None else {}

# ---------------- файлы ----------------
KIND_BY_MIME = {"image": "image", "video": "video", "audio": "audio"}
def kind_of(mime: str) -> str: return KIND_BY_MIME.get((mime or "").split("/")[0], "file")

def user_dir(uid: int) -> Path:
    d = FILES / str(int(uid)); d.mkdir(parents=True, exist_ok=True); return d

def new_path(uid: int, ext: str) -> Path:
    ext = ext if ext.startswith(".") else "." + ext
    return user_dir(uid) / (uuid.uuid4().hex + ext.lower())

def tmp_path(ext: str) -> Path:
    return TMP / (uuid.uuid4().hex + (ext if ext.startswith(".") else "." + ext))

def add_asset(uid, path: Path, kind=None, name=None, project_id=None, meta=None, mime=None):
    path = Path(path)
    try: path.resolve().relative_to(FILES.resolve())
    except ValueError:   # временный файл → переносим в папку пользователя
        dst = new_path(uid, path.suffix or ".bin")
        import shutil; shutil.move(str(path), dst); path = dst
    path = path.resolve()
    mime = mime or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    aid = uuid.uuid4().hex[:16]
    with db() as c:
        c.execute("INSERT INTO assets(id,user_id,project_id,kind,name,path,mime,size,meta) VALUES(?,?,?,?,?,?,?,?,?)",
                  (aid, uid, project_id, kind or kind_of(mime), name or path.name, path.relative_to(FILES.resolve()).as_posix(), mime,
                   path.stat().st_size, json.dumps(meta or {}, ensure_ascii=False)))
    if project_id: touch_project(project_id)
    return asset_public(get_asset(uid, aid))

def get_asset(uid, aid):
    with db() as c: return row(c.execute("SELECT * FROM assets WHERE id=? AND user_id=?", (aid, uid)).fetchone())

def asset_file(a) -> Path: return FILES / a["path"]

def asset_public(a):
    if not a: return None
    out = {k: a[k] for k in ("id", "kind", "name", "mime", "size", "favorite", "created", "project_id")}
    out["meta"] = jload(a.get("meta")); out["url"] = f"/files/{a['id']}"
    return out

def touch_project(pid):
    with db() as c: c.execute("UPDATE projects SET updated=datetime('now') WHERE id=?", (pid,))

# ---------------- фоновые задачи ----------------
POOL = ThreadPoolExecutor(max_workers=int(os.environ.get("MAISONAI_WORKERS", "3")))
CANCEL = set()

class Cancelled(Exception): pass

class Job:
    """Передаётся в функцию задачи: прогресс, сообщения, отмена."""
    def __init__(self, jid, uid, project_id, params):
        self.id, self.uid, self.project_id, self.params = jid, uid, project_id, params
        self._last = 0.0; self.allow = None
    def progress(self, p: float, msg: str = None):
        if self.id in CANCEL: raise Cancelled()
        now = time.time()
        if now - self._last < 0.3 and p < 1 and not msg: return
        self._last = now
        with db() as c:
            if msg is None: c.execute("UPDATE jobs SET progress=? WHERE id=?", (max(0.0, min(1.0, p)), self.id))
            else: c.execute("UPDATE jobs SET progress=?, message=? WHERE id=?", (max(0.0, min(1.0, p)), msg, self.id))
    def provider(self, name: str):
        with db() as c: c.execute("UPDATE jobs SET provider=? WHERE id=?", (name, self.id))
    def check(self):
        if self.id in CANCEL: raise Cancelled()
    def asset(self, path, **kw):
        kw.setdefault("project_id", self.project_id)
        return add_asset(self.uid, path, **kw)

class UserError(Exception):
    """Понятная пользователю ошибка (без технических подробностей)."""

def submit(uid, tool, title, params, fn, project_id=None):
    jid = uuid.uuid4().hex[:16]; params_in = params
    with db() as c:
        c.execute("INSERT INTO jobs(id,user_id,project_id,tool,title,params,status,created) VALUES(?,?,?,?,?,?,?,?)",
                  (jid, uid, project_id, tool, (title or tool)[:200], json.dumps(params, ensure_ascii=False), "queued", time.time()))
    def run():
        job = Job(jid, uid, project_id, params_in)
        params = {k: v for k, v in params_in.items() if not k.startswith("_")}   # служебное (кошелёк, отпечаток) не передаём в функцию
        job.allow = params_in.get("_allow")   # подтверждённая сумма для платных вызовов (billing)
        with db() as c: c.execute("UPDATE jobs SET status='running', started=?, message=? WHERE id=?", (time.time(), "Начинаю…", jid))
        try:
            res = fn(job, **params)
            with db() as c:
                c.execute("UPDATE jobs SET status='done', progress=1, message='Готово', result=?, finished=? WHERE id=?",
                          (json.dumps(res, ensure_ascii=False), time.time(), jid))
            if project_id: touch_project(project_id)
        except Cancelled:
            with db() as c: c.execute("UPDATE jobs SET status='cancelled', message='Отменено', finished=? WHERE id=?", (time.time(), jid))
        except Exception as e:
            msg = str(e) if isinstance(e, UserError) else friendly_error(e)
            if not isinstance(e, UserError): traceback.print_exc()
            with db() as c: c.execute("UPDATE jobs SET status='error', error=?, message='Ошибка', finished=? WHERE id=?", (msg, time.time(), jid))
        finally:
            CANCEL.discard(jid)
    POOL.submit(run)
    return jid

def friendly_error(e: Exception) -> str:
    import httpx
    if isinstance(e, httpx.TimeoutException): return "Сервис ИИ не ответил вовремя. Попробуйте ещё раз или выберите другого провайдера в Настройках."
    if isinstance(e, httpx.ConnectError): return "Нет связи с сервисом. Проверьте интернет (или запущен ли локальный сервер ComfyUI/Ollama)."
    if isinstance(e, httpx.HTTPStatusError):
        code = e.response.status_code
        if code in (401, 403): return "Сервис отклонил ключ доступа. Проверьте ключ в Настройках → Провайдеры."
        if code == 402: return "У провайдера закончился бесплатный лимит или баланс. Подождите или выберите другого провайдера."
        if code == 429: return "Превышен лимит запросов бесплатного тарифа. Подождите немного и повторите."
        if code >= 500: return f"Сервис ИИ временно перегружен или недоступен (ошибка {code}). Нажмите «Повторить» через пару минут."
        try: detail = e.response.json()
        except Exception: detail = e.response.text[:300]
        return f"Сервис вернул ошибку {code}: {str(detail)[:300]}"
    return f"Непредвиденная ошибка: {type(e).__name__}: {str(e)[:300]}"

def job_public(j):
    if not j: return None
    out = dict(j)
    out["params"] = jload(j.get("params")); out["result"] = jload(j.get("result"), None)
    now = time.time()
    out["elapsed"] = round(((j.get("finished") or now) - (j.get("started") or j.get("created") or now)), 1) if j.get("started") else 0
    return out

def cleanup_tmp(max_age=6 * 3600):
    for p in TMP.glob("*"):
        try:
            if time.time() - p.stat().st_mtime > max_age:
                p.unlink() if p.is_file() else None
        except Exception: pass
