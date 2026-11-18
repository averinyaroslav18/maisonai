"""MaisonAI — сервер (FastAPI). Все ключи ИИ живут здесь, в браузер не попадают."""
import hashlib, hmac, json, os, re, secrets, shutil, socket, time
from pathlib import Path
from typing import List, Optional
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import ai, core, gen, media, providers as P, tools, intel, remote
from core import (DATA, FILES, HERE, UserError, add_asset, asset_file, asset_public, db, get_asset, jload, job_public, row, rows, submit)

import hfspace
hfspace.restore()          # облако Hugging Face: забрать данные из закрытого архива до открытия базы
core.init_db()
hfspace.start_backups()
app = FastAPI(title="MaisonAI", version=core.VERSION, docs_url=None, redoc_url=None)
LAST_SEEN = [time.time()]
PORT = int(os.environ.get("MAISONAI_PORT", "8790"))
CLOUD = os.environ.get("MAISONAI_CLOUD") == "1"   # облачный режим: доступ из интернета, управляет владелец
MAX_UPLOAD = 500 * 1024 * 1024
if CLOUD:
    try: P.auto_best()   # ключи из секретов сервера → сразу выбрать лучшее
    except Exception: pass

@app.on_event("shutdown")
def _save_on_exit():
    try: hfspace.backup_now()   # Hugging Face перезапускает сервер — успеваем сохранить
    except Exception: pass

# ---------------- доступ с iPad/iPhone по Wi-Fi ----------------
def is_local(request: Request) -> bool:
    if remote.via_tunnel(request): return False   # туннель Cloudflare тоже приходит с 127.0.0.1 — это НЕ компьютер
    return bool(request.client) and request.client.host in ("127.0.0.1", "::1", "localhost", "testclient")

def from_internet(request: Request) -> bool: return CLOUD or remote.via_tunnel(request)

def owner_id():
    with db() as c: r = c.execute("SELECT MIN(id) FROM users").fetchone()
    return r[0]

def can_admin(request: Request) -> bool:
    """Кто может менять ключи и провайдеров: на компьютере — только сам компьютер; в облаке — владелец (первый аккаунт)."""
    if CLOUD:
        u = getattr(request.state, "user", None)
        return bool(u) and u["id"] == owner_id()
    return is_local(request)

def is_https(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "") == "https"

_net = {"t": 0.0, "v": False}
def lan_enabled():
    if time.time() - _net["t"] > 1: _net["v"] = bool(P.load_cfg().get("lan_access")); _net["t"] = time.time()
    return _net["v"]

_rem = {"t": 0.0, "v": False}
def remote_enabled():
    if time.time() - _rem["t"] > 1: _rem["v"] = remote.enabled(); _rem["t"] = time.time()
    return _rem["v"]

def lan_ips():
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(("10.255.255.255", 1)); ips.append(s.getsockname()[0]); s.close()
    except OSError: pass
    try: ips += socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError: pass
    return [ip for i, ip in enumerate(ips) if not ip.startswith(("127.", "169.254.")) and ip not in ips[:i]]

# ---------------- пользователи ----------------
SESSION_DAYS = 30
FAILS = {}
PUBLIC = ("/api/auth/", "/api/info")
def _h(pw, salt): return hashlib.scrypt(pw.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
def hash_pw(pw): s = os.urandom(16); return s.hex() + "$" + _h(pw, s).hex()
def check_pw(pw, stored):
    try: s, h = stored.split("$"); return hmac.compare_digest(_h(pw, bytes.fromhex(s)).hex(), h)
    except Exception: return False
tok_hash = lambda t: hashlib.sha256(t.encode()).hexdigest()

def session_user(token):
    if not token: return None
    with db() as c:
        r = c.execute("SELECT u.id, u.username, u.display_name, u.prefs, u.created FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.h=? AND s.expires>?", (tok_hash(token), time.time())).fetchone()
    return row(r)

def U(request: Request) -> dict:
    u = getattr(request.state, "user", None)
    if not u: raise HTTPException(401, "Требуется вход")
    return u

@app.middleware("http")
async def gate(request: Request, call_next):
    LAST_SEEN[0] = time.time()
    if not CLOUD and remote.via_tunnel(request):
        if not remote_enabled(): return PlainTextResponse("Доступ из интернета выключен на компьютере (Настройки → iPad и MacBook).", status_code=403)
    elif not CLOUD and not is_local(request) and not lan_enabled():
        return PlainTextResponse("Доступ с других устройств выключен. Включите его на компьютере: Настройки → Устройства.", status_code=403)
    p = request.url.path
    request.state.user = None
    if p.startswith(("/api/", "/files/")):
        request.state.user = session_user(request.cookies.get("mai_session"))
        if not p.startswith(PUBLIC) and not request.state.user:
            return JSONResponse({"detail": "Требуется вход"}, status_code=401)
    resp = await call_next(request)
    if p.startswith("/api/"): resp.headers["Cache-Control"] = "no-store"
    elif not p.startswith("/files/"): resp.headers["Cache-Control"] = "no-cache"   # после обновления браузер сразу берёт новые файлы программы
    resp.headers["X-Content-Type-Options"] = "nosniff"; resp.headers["Referrer-Policy"] = "same-origin"
    if CLOUD and is_https(request): resp.headers["Strict-Transport-Security"] = "max-age=31536000"
    return resp

@app.exception_handler(UserError)
async def user_error(_, e: UserError): return JSONResponse({"detail": str(e)}, status_code=400)

class RegIn(BaseModel): username: str; password: str; display_name: str = ""; invite: str = ""
class LoginIn(BaseModel): username: str; password: str; remember: bool = True
class PassIn(BaseModel): old: str; new: str
class ProfileIn(BaseModel): display_name: Optional[str] = None; prefs: Optional[dict] = None

def start_session(uid, remember=True, request: Request = None):
    tok = secrets.token_urlsafe(32); days = SESSION_DAYS if remember else 1
    with db() as c:
        c.execute("INSERT INTO sessions(h,user_id,expires) VALUES(?,?,?)", (tok_hash(tok), uid, time.time() + days * 86400))
        c.execute("UPDATE users SET last_login=datetime('now') WHERE id=?", (uid,))
        c.execute("DELETE FROM sessions WHERE expires<?", (time.time(),))
    resp = JSONResponse({"ok": True})
    resp.set_cookie("mai_session", tok, max_age=days * 86400 if remember else None, httponly=True, samesite="lax", path="/", secure=bool(request and is_https(request)))
    return resp

@app.get("/api/info")
def info(): return {"name": "MaisonAI", "version": core.VERSION}

@app.get("/api/auth/status")
def auth_status(request: Request):
    u = request.state.user
    with db() as c: n = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    out = {"has_users": n > 0, "logged_in": bool(u), "local": can_admin(request), "cloud": CLOUD, "invite_needed": from_internet(request) and n > 0 and not P.load_cfg().get("open_registration")}
    if u: out["user"] = {"id": u["id"], "username": u["username"], "display_name": u["display_name"] or u["username"], "prefs": jload(u["prefs"]), "created": u["created"]}
    return out

@app.post("/api/auth/register")
def register(b: RegIn, request: Request):
    u = b.username.strip()
    if from_internet(request):   # из интернета (облако или туннель) после первого аккаунта регистрация — только по коду приглашения владельца
        with db() as c: n = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        cfg = P.load_cfg()
        if n > 0 and not cfg.get("open_registration") and not (cfg.get("invite_code") and hmac.compare_digest(b.invite.strip(), cfg["invite_code"])):
            raise HTTPException(403, "Регистрация закрыта. Попросите у владельца код приглашения (Настройки → Аккаунт).")
    if not re.fullmatch(r"[\w.\-]{3,32}", u): raise HTTPException(400, "Логин: 3–32 символа — буквы, цифры, точка, дефис или подчёркивание.")
    if len(b.password) < 8: raise HTTPException(400, "Пароль должен быть не короче 8 символов.")
    with db() as c:
        if c.execute("SELECT 1 FROM users WHERE lower(username)=lower(?)", (u,)).fetchone(): raise HTTPException(400, "Такой логин уже занят.")
        cur = c.execute("INSERT INTO users(username,pass,display_name) VALUES(?,?,?)", (u, hash_pw(b.password), (b.display_name.strip() or u)[:40]))
        uid = cur.lastrowid
    return start_session(uid, True, request)

@app.post("/api/auth/login")
def login(b: LoginIn, request: Request):
    k = b.username.strip().lower(); n, until = FAILS.get(k, [0, 0])
    if until > time.time(): raise HTTPException(429, f"Слишком много попыток. Подождите {int(until - time.time()) + 1} сек.")
    with db() as c: r = c.execute("SELECT id, pass FROM users WHERE lower(username)=?", (k,)).fetchone()
    if not r or not check_pw(b.password, r["pass"]):
        n += 1; FAILS[k] = [0, time.time() + 30] if n >= 5 else [n, 0]
        raise HTTPException(401, "Неверный логин или пароль.")
    FAILS.pop(k, None); return start_session(r["id"], b.remember, request)

@app.post("/api/auth/logout")
def logout(request: Request):
    t = request.cookies.get("mai_session")
    if t:
        with db() as c: c.execute("DELETE FROM sessions WHERE h=?", (tok_hash(t),))
    resp = JSONResponse({"ok": True}); resp.delete_cookie("mai_session", path="/"); return resp

@app.post("/api/account/password")
def change_password(b: PassIn, request: Request):
    u = U(request)
    if len(b.new) < 8: raise HTTPException(400, "Новый пароль должен быть не короче 8 символов.")
    with db() as c:
        r = c.execute("SELECT pass FROM users WHERE id=?", (u["id"],)).fetchone()
        if not check_pw(b.old, r["pass"]): raise HTTPException(400, "Текущий пароль неверный.")
        c.execute("UPDATE users SET pass=? WHERE id=?", (hash_pw(b.new), u["id"]))
    return {"ok": True}

@app.post("/api/account/profile")
def profile(b: ProfileIn, request: Request):
    u = U(request)
    with db() as c:
        if b.display_name is not None: c.execute("UPDATE users SET display_name=? WHERE id=?", (b.display_name.strip()[:40] or u["username"], u["id"]))
        if b.prefs is not None:
            prefs = {**jload(u["prefs"]), **{k: v for k, v in b.prefs.items() if k in ("language", "voice", "ratio", "sub_font", "reduce_motion")}}
            c.execute("UPDATE users SET prefs=? WHERE id=?", (json.dumps(prefs, ensure_ascii=False), u["id"]))
    return {"ok": True}

@app.delete("/api/account")
def delete_account(request: Request, password: str):
    u = U(request)
    with db() as c:
        r = c.execute("SELECT pass FROM users WHERE id=?", (u["id"],)).fetchone()
        if not check_pw(password, r["pass"]): raise HTTPException(400, "Неверный пароль.")
        for t in ("assets", "jobs", "chats", "projects", "sessions", "intel_videos", "styles", "characters", "blueprints", "trend_reports"): c.execute(f"DELETE FROM {t} WHERE user_id=?", (u["id"],))
        c.execute("DELETE FROM users WHERE id=?", (u["id"],))
    shutil.rmtree(FILES / str(u["id"]), ignore_errors=True)
    resp = JSONResponse({"ok": True}); resp.delete_cookie("mai_session", path="/"); return resp

# ---------------- провайдеры и настройки ----------------
class UseIn(BaseModel): use: dict = {}; models: dict = {}; base: dict = {}
class KeyIn(BaseModel): provider: str; key: str = ""; account: str = ""; clear: bool = False

@app.get("/api/settings/providers")
def providers_state(request: Request):
    U(request); s = P.public_state(); s["local"] = can_admin(request); s["cloud"] = CLOUD; s["video_caps"] = gen.VIDEO_CAPS; s["wan_models"] = gen.WAN
    return s

@app.post("/api/settings/providers")
def providers_set(b: UseIn, request: Request):
    U(request)
    if not can_admin(request): raise HTTPException(403, "Менять провайдеров может только владелец на компьютере (или владелец аккаунта в облаке).")
    c = P.load_cfg()
    if b.use: c["auto_best"] = False   # пользователь выбрал вручную — автонастройка не перебивает
    for cap, pid in b.use.items():
        if cap in P.CAP_LABELS and (pid == "" or (pid in P.PROVIDERS and cap in P.PROVIDERS[pid]["caps"])): c["use"][cap] = pid
    for k, v in b.models.items():
        if re.fullmatch(r"[a-z_]+:[a-z_]+", k): c["models"][k] = str(v)[:200]
    for pid, url in b.base.items():
        if pid in P.PROVIDERS:
            url = str(url).strip()
            if url and not re.match(r"^https?://", url): raise HTTPException(400, "Адрес сервера должен начинаться с http:// или https://")
            c["base"][pid] = url
    P.save_cfg(c); return P.public_state()

@app.post("/api/settings/auto")
def providers_auto(request: Request):
    U(request)
    if not can_admin(request): raise HTTPException(403, "Только владелец.")
    P.auto_best(force=True); return P.public_state()

@app.post("/api/settings/keys")
def keys_set(b: KeyIn, request: Request):
    U(request)
    if not can_admin(request): raise HTTPException(403, "Ключи может вводить только владелец: на компьютере — на самом компьютере, в облаке — первый аккаунт.")
    if b.provider not in P.PROVIDERS: raise HTTPException(400, "Неизвестный провайдер")
    sec = P.load_secrets(); cur = sec.get(b.provider) or {}
    if b.clear: sec.pop(b.provider, None)
    else:
        if b.key.strip(): cur["key"] = b.key.strip()
        if b.account.strip():
            m = re.search(r"\b[0-9a-f]{32}\b", b.account.strip().lower())   # можно вставить и весь адрес из браузера
            if not m: raise HTTPException(400, "Это не Account ID. Нужны 32 символа из букв a–f и цифр: откройте dash.cloudflare.com — они видны в адресной строке после «dash.cloudflare.com/». Можно вставить весь адрес — программа найдёт ID сама.")
            cur["account"] = m.group(0)
        sec[b.provider] = cur
    P.save_secrets(sec)
    c = P.load_cfg(); c["models"] = {k: v for k, v in c["models"].items() if not k.startswith(b.provider + ":")}; P.save_cfg(c)
    P.auto_best()   # сразу подключаем лучшее из доступного
    return P.public_state()

@app.post("/api/settings/test/{pid}")
def provider_test(pid: str, request: Request):
    U(request)
    if pid not in P.PROVIDERS: raise HTTPException(404, "Неизвестный провайдер")
    try: return ai.test_provider(pid)
    except UserError as e: return {"ok": False, "detail": str(e)}
    except Exception as e: return {"ok": False, "detail": core.friendly_error(e)}

@app.get("/api/settings/comfy_models")
def comfy_models(request: Request):
    U(request)
    try: return {"checkpoints": gen.comfy_models("checkpoints"), "diffusion_models": gen.comfy_models("diffusion_models")}
    except Exception as e: return {"error": core.friendly_error(e)}

@app.get("/api/settings/pollinations_prices")
def poll_prices(request: Request, kind: str = "video"):
    U(request)
    if kind not in ("video", "image", "audio"): raise HTTPException(400, "kind")
    try: return {"models": gen.pollinations_price(kind)}
    except Exception as e: return {"error": core.friendly_error(e)}

# ---------------- устройства (iPad/iPhone) ----------------
class NetIn(BaseModel): enabled: bool
@app.get("/api/net")
def net_state(request: Request):
    U(request)
    if CLOUD: return {"cloud": True, "enabled": True, "urls": [str(request.base_url).rstrip("/")], "local": can_admin(request)}
    return {"enabled": lan_enabled(), "port": PORT, "urls": [f"http://{ip}:{PORT}" for ip in lan_ips()], "local": is_local(request), "cloud_url": P.load_cfg().get("cloud_url", "")}

@app.post("/api/net")
def net_set(b: NetIn, request: Request):
    U(request)
    if not is_local(request): raise HTTPException(403, "Включать доступ можно только на самом компьютере.")
    c = P.load_cfg(); c["lan_access"] = b.enabled; P.save_cfg(c); _net["t"] = 0; return net_state(request)

@app.get("/api/net/qr")
def net_qr(url: str, request: Request):
    U(request)
    if not url.startswith("http") or len(url) > 200: raise HTTPException(400, "Некорректный адрес")
    import io, segno
    buf = io.BytesIO(); segno.make(url, error="m").save(buf, kind="svg", scale=6, border=2, dark="#000000", light="#ffffff")
    return Response(buf.getvalue(), media_type="image/svg+xml")

# ---------------- проекты ----------------
class ProjIn(BaseModel): title: str = "Новый проект"; kind: str = "general"
class ProjPatch(BaseModel): title: Optional[str] = None; favorite: Optional[bool] = None; data: Optional[dict] = None

def own_project(uid, pid):
    if pid in (None, "", 0): return None
    with db() as c: r = c.execute("SELECT * FROM projects WHERE id=? AND user_id=?", (int(pid), uid)).fetchone()
    if not r: raise HTTPException(404, "Проект не найден")
    return dict(r)

@app.get("/api/projects")
def projects(request: Request, q: str = "", favorite: bool = False):
    u = U(request); sql = "SELECT p.*, (SELECT COUNT(*) FROM assets a WHERE a.project_id=p.id) AS n_assets, (SELECT a.id FROM assets a WHERE a.project_id=p.id AND a.kind IN ('image','video') ORDER BY a.created DESC LIMIT 1) AS cover FROM projects p WHERE user_id=?"
    args = [u["id"]]
    if q: sql += " AND title LIKE ?"; args.append(f"%{q}%")
    if favorite: sql += " AND favorite=1"
    with db() as c: rs = rows(c.execute(sql + " ORDER BY updated DESC", args))
    for r in rs:
        r["data"] = jload(r["data"])
        if r["cover"]:
            a = get_asset(u["id"], r["cover"]); r["cover_url"] = f"/files/{r['cover']}" + ("?thumb=1" if a and a["kind"] == "video" else "")
    return rs

@app.post("/api/projects")
def project_new(b: ProjIn, request: Request):
    u = U(request)
    with db() as c: pid = c.execute("INSERT INTO projects(user_id,title,kind) VALUES(?,?,?)", (u["id"], b.title.strip()[:120] or "Новый проект", b.kind[:30])).lastrowid
    return project_get(pid, request)

@app.get("/api/projects/{pid}")
def project_get(pid: int, request: Request):
    u = U(request); p = own_project(u["id"], pid); p["data"] = jload(p["data"])
    with db() as c:
        p["assets"] = [asset_public(dict(a)) for a in c.execute("SELECT * FROM assets WHERE project_id=? AND user_id=? ORDER BY created DESC", (pid, u["id"]))]
        p["jobs"] = [job_public(dict(j)) for j in c.execute("SELECT * FROM jobs WHERE project_id=? AND user_id=? ORDER BY created DESC LIMIT 50", (pid, u["id"]))]
    return p

@app.patch("/api/projects/{pid}")
def project_patch(pid: int, b: ProjPatch, request: Request):
    u = U(request); p = own_project(u["id"], pid)
    with db() as c:
        if b.title is not None: c.execute("UPDATE projects SET title=?, updated=datetime('now') WHERE id=?", (b.title.strip()[:120] or p["title"], pid))
        if b.favorite is not None: c.execute("UPDATE projects SET favorite=? WHERE id=?", (int(b.favorite), pid))
        if b.data is not None: c.execute("UPDATE projects SET data=?, updated=datetime('now') WHERE id=?", (json.dumps({**jload(p["data"]), **b.data}, ensure_ascii=False)[:2_000_000], pid))
    return {"ok": True}

@app.delete("/api/projects/{pid}")
def project_delete(pid: int, request: Request, with_files: bool = True):
    u = U(request); own_project(u["id"], pid)
    with db() as c:
        if with_files:
            for a in c.execute("SELECT path FROM assets WHERE project_id=? AND user_id=? AND favorite=0", (pid, u["id"])).fetchall():
                try: (FILES / a["path"]).unlink()
                except OSError: pass
            c.execute("DELETE FROM assets WHERE project_id=? AND user_id=? AND favorite=0", (pid, u["id"]))
        c.execute("UPDATE assets SET project_id=NULL WHERE project_id=? AND user_id=?", (pid, u["id"]))
        c.execute("UPDATE jobs SET project_id=NULL WHERE project_id=? AND user_id=?", (pid, u["id"]))
        c.execute("DELETE FROM chats WHERE project_id=? AND user_id=?", (pid, u["id"]))
        c.execute("DELETE FROM projects WHERE id=? AND user_id=?", (pid, u["id"]))
    return {"ok": True}

# ---------------- файлы ----------------
@app.get("/api/assets")
def assets(request: Request, kind: str = "", project_id: int = 0, favorite: bool = False, limit: int = 120, offset: int = 0):
    u = U(request); sql, args = "SELECT * FROM assets WHERE user_id=?", [u["id"]]
    if kind: sql += " AND kind IN (%s)" % ",".join("?" * len(kind.split(","))); args += kind.split(",")
    if project_id: sql += " AND project_id=?"; args.append(project_id)
    if favorite: sql += " AND favorite=1"
    with db() as c: return [asset_public(dict(a)) for a in c.execute(sql + " ORDER BY created DESC LIMIT ? OFFSET ?", args + [min(500, limit), offset])]

ALLOWED = {"image": (".jpg", ".jpeg", ".png", ".webp"), "video": (".mp4", ".mov", ".webm", ".m4v", ".mkv"), "audio": (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac")}

@app.post("/api/assets/upload")
async def upload(request: Request, file: UploadFile = File(...), project_id: int = Form(0)):
    u = U(request)
    if project_id: own_project(u["id"], project_id)
    ext = Path(file.filename or "").suffix.lower()
    kind = next((k for k, exts in ALLOWED.items() if ext in exts), None)
    if not kind: raise HTTPException(400, "Этот тип файла не поддерживается. Можно: картинки (JPG, PNG, WebP), видео (MP4, MOV, WebM), аудио (MP3, WAV, M4A).")
    dst = core.new_path(u["id"], ext); size = 0
    with open(dst, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD: f.close(); dst.unlink(); raise HTTPException(413, "Файл больше 500 МБ.")
            f.write(chunk)
    meta = {}
    if kind in ("video", "audio"):
        try: meta = media.probe(dst)
        except UserError: dst.unlink(); raise HTTPException(400, "Файл повреждён или не является видео/аудио.")
    if kind == "image":
        try:
            from PIL import Image, ImageOps
            with Image.open(dst) as im:
                im = ImageOps.exif_transpose(im); meta = {"width": im.width, "height": im.height}
                if ext not in (".jpg", ".jpeg", ".png") or im.mode not in ("RGB", "RGBA", "L"):
                    im.convert("RGB").save(dst.with_suffix(".jpg"), quality=92); dst.unlink(); dst = dst.with_suffix(".jpg")
        except Exception: dst.unlink(missing_ok=True); raise HTTPException(400, "Не удалось открыть картинку.")
    return add_asset(u["id"], dst, kind=kind, name=(file.filename or dst.name)[:150], project_id=project_id or None, meta={**meta, "uploaded": True})

class AssetPatch(BaseModel): name: Optional[str] = None; favorite: Optional[bool] = None; project_id: Optional[int] = None

@app.patch("/api/assets/{aid}")
def asset_patch(aid: str, b: AssetPatch, request: Request):
    u = U(request); a = get_asset(u["id"], aid)
    if not a: raise HTTPException(404, "Файл не найден")
    with db() as c:
        if b.name is not None: c.execute("UPDATE assets SET name=? WHERE id=?", (b.name.strip()[:150] or a["name"], aid))
        if b.favorite is not None: c.execute("UPDATE assets SET favorite=? WHERE id=?", (int(b.favorite), aid))
        if b.project_id is not None:
            if b.project_id: own_project(u["id"], b.project_id)
            c.execute("UPDATE assets SET project_id=? WHERE id=?", (b.project_id or None, aid))
    return asset_public(get_asset(u["id"], aid))

@app.delete("/api/assets/{aid}")
def asset_delete(aid: str, request: Request):
    u = U(request); a = get_asset(u["id"], aid)
    if not a: raise HTTPException(404, "Файл не найден")
    try: asset_file(a).unlink()
    except OSError: pass
    with db() as c: c.execute("DELETE FROM assets WHERE id=?", (aid,))
    return {"ok": True}

@app.get("/api/assets/{aid}/text")
def asset_text(aid: str, request: Request):
    u = U(request); a = get_asset(u["id"], aid)
    if not a or a["mime"] != "application/json": raise HTTPException(404, "Не найдено")
    return json.loads(asset_file(a).read_text(encoding="utf-8"))

@app.get("/files/{aid}")
def serve_file(aid: str, request: Request, download: bool = False, thumb: bool = False):
    u = U(request); a = get_asset(u["id"], aid)
    if not a: raise HTTPException(404, "Файл не найден")
    p = asset_file(a)
    if not p.exists(): raise HTTPException(404, "Файл удалён с диска")
    if thumb and a["kind"] == "video":
        tp = p.with_suffix(".thumb.jpg")
        if not tp.exists():
            try: shutil.move(str(media.thumbnail(p)), tp)
            except Exception: raise HTTPException(404, "Нет превью")
        return FileResponse(tp, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})
    size = p.stat().st_size
    headers = {"Accept-Ranges": "bytes", "Cache-Control": "private, max-age=3600"}
    if download:
        from urllib.parse import quote
        headers["Content-Disposition"] = "attachment; filename*=UTF-8''" + quote(a["name"])
    rng = request.headers.get("range")
    m = re.match(r"bytes=(\d*)-(\d*)", rng or "")
    if m and (m.group(1) or m.group(2)):   # перемотка видео (особенно важно для iPad/iPhone Safari)
        if m.group(1): start = int(m.group(1)); end = int(m.group(2)) if m.group(2) else size - 1
        else: start = max(0, size - int(m.group(2))); end = size - 1
        end = min(end, size - 1)
        if start > end: return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
        def it():
            with open(p, "rb") as f:
                f.seek(start); left = end - start + 1
                while left > 0:
                    chunk = f.read(min(1024 * 512, left))
                    if not chunk: break
                    left -= len(chunk); yield chunk
        return StreamingResponse(it(), status_code=206, media_type=a["mime"], headers={**headers, "Content-Range": f"bytes {start}-{end}/{size}", "Content-Length": str(end - start + 1)})
    return FileResponse(p, media_type=a["mime"], headers=headers)

# ---------------- задачи ----------------
@app.get("/api/jobs")
def jobs(request: Request, tool: str = "", status: str = "", project_id: int = 0, favorite: bool = False, limit: int = 60, offset: int = 0):
    u = U(request); sql, args = "SELECT * FROM jobs WHERE user_id=?", [u["id"]]
    if tool: sql += " AND tool=?"; args.append(tool)
    if status: sql += " AND status=?"; args.append(status)
    if project_id: sql += " AND project_id=?"; args.append(project_id)
    if favorite: sql += " AND favorite=1"
    with db() as c: return [job_public(dict(j)) for j in c.execute(sql + " ORDER BY created DESC LIMIT ? OFFSET ?", args + [min(200, limit), offset])]

@app.get("/api/jobs/{jid}")
def job(jid: str, request: Request):
    u = U(request)
    with db() as c: j = c.execute("SELECT * FROM jobs WHERE id=? AND user_id=?", (jid, u["id"])).fetchone()
    if not j: raise HTTPException(404, "Задача не найдена")
    return job_public(dict(j))

@app.post("/api/jobs/{jid}/cancel")
def job_cancel(jid: str, request: Request):
    j = job(jid, request)
    if j["status"] in ("queued", "running"): core.CANCEL.add(jid)
    return {"ok": True}

@app.post("/api/jobs/{jid}/favorite")
def job_fav(jid: str, request: Request, on: bool = True):
    u = U(request)
    with db() as c: c.execute("UPDATE jobs SET favorite=? WHERE id=? AND user_id=?", (int(on), jid, u["id"]))
    return {"ok": True}

@app.delete("/api/jobs/{jid}")
def job_delete(jid: str, request: Request):
    u = U(request)
    with db() as c: c.execute("DELETE FROM jobs WHERE id=? AND user_id=? AND status NOT IN ('queued','running')", (jid, u["id"]))
    return {"ok": True}

@app.get("/api/stats")
def stats(request: Request):
    u = U(request)
    with db() as c:
        q = lambda s, *a: c.execute(s, (u["id"], *a)).fetchone()[0]
        return {"projects": q("SELECT COUNT(*) FROM projects WHERE user_id=?"),
                "images": q("SELECT COUNT(*) FROM assets WHERE user_id=? AND kind='image' AND meta NOT LIKE '%\"uploaded\": true%' AND meta NOT LIKE '%reference_frame%'"),
                "videos": q("SELECT COUNT(*) FROM assets WHERE user_id=? AND kind='video' AND meta NOT LIKE '%\"uploaded\": true%'"),
                "audio": q("SELECT COUNT(*) FROM assets WHERE user_id=? AND kind='audio' AND meta NOT LIKE '%\"uploaded\": true%'"),
                "scripts": q("SELECT COUNT(*) FROM assets WHERE user_id=? AND kind='script'"),
                "running": q("SELECT COUNT(*) FROM jobs WHERE user_id=? AND status IN ('queued','running')")}

# ---------------- инструменты ----------------
def start(request, tool, title, params, fn, project_id=None):
    u = U(request)
    if project_id: own_project(u["id"], project_id)
    jid = submit(u["id"], tool, title, params, fn, project_id or None)
    return {"job": jid}

def asset_path(uid, aid, kinds=("image",)):
    if not aid: return None
    a = get_asset(uid, aid)
    if not a or a["kind"] not in kinds: raise HTTPException(400, "Исходный файл не найден.")
    return asset_file(a)

class ScriptIn(BaseModel):
    topic: str; duration: int = Field(30, ge=5, le=600); language: str = "uk"; style: str = ""; audience: str = ""; goal: str = ""
    avoid: List[str] = []; extra: str = ""; project_id: Optional[int] = None; style_id: Optional[str] = None
@app.post("/api/tools/script")
def t_script(b: ScriptIn, request: Request):
    u = U(request); p = b.model_dump(); pid = p.pop("project_id"); sid = p.pop("style_id")
    if sid:   # сохранённый стиль Visual DNA: подсказываем приёмы хуков и подачу
        with db() as c: s = c.execute("SELECT name, dna FROM styles WHERE id=? AND user_id=?", (sid, u["id"])).fetchone()
        if s:
            d = jload(s["dna"])
            p["extra"] = (p["extra"] + " " if p["extra"] else "") + f"Следуй стилю «{s['name']}»: {d.get('summary', '')} Приёмы хука: {'; '.join(d.get('hook_patterns', [])[:4])}. Текст на экране: {d.get('text_style', '')}. Озвучка: {d.get('voice_style', '')}."
    return start(request, "script", "Сценарий: " + b.topic[:80], p, tools.script, pid)

class ImproveIn(BaseModel): text: str; target: str = "video"; ratio: str = "9:16"; style: str = ""; camera: str = ""; characters: str = ""
@app.post("/api/tools/improve")
def t_improve(b: ImproveIn, request: Request):
    U(request)
    if not b.text.strip(): raise HTTPException(400, "Опишите, что нужно получить.")
    class _J:   # короткая синхронная операция
        def progress(self, *a, **k): pass
        def provider(self, *a): pass
        _p = 0
    return tools.improve_prompt(_J(), **b.model_dump())

class ImageIn(BaseModel):
    prompt: str; ratio: str = "1:1"; seed: Optional[int] = None; source: Optional[str] = None; refs: List[str] = []
    strength: float = 0.65; negative: str = ""; preset: str = ""; count: int = Field(1, ge=1, le=4); project_id: Optional[int] = None; style_id: Optional[str] = None

PRESETS = {"character": "character design sheet, full body, consistent features, neutral background, ",
           "cover": "eye-catching TikTok cover, bold composition, strong subject, space for title text at top, ",
           "ad": "premium advertising photo, product hero shot, studio lighting, clean background, ",
           "frame": "cinematic vertical video frame, film still, ", "": ""}

@app.post("/api/tools/image")
def t_image(b: ImageIn, request: Request):
    u = U(request)
    if not b.prompt.strip(): raise HTTPException(400, "Опишите картинку.")
    refs = [str(asset_path(u["id"], a)) for a in ([b.source] if b.source else []) + b.refs[:3]]
    prompt = PRESETS.get(b.preset, "") + b.prompt.strip()
    sp, sn = intel.style_suffix(u["id"], b.style_id)
    if sp: prompt += ", " + sp
    if sn and not b.negative: b.negative = sn
    def run(job, prompt, ratio, seed, refs, strength, negative, count, source):
        out = []
        for i in range(count):
            job._p = i / count; job.progress(i / count, f"Генерирую {i + 1} из {count}…" if count > 1 else "Генерирую…")
            r = gen.image(prompt, ratio, (seed + i) if seed else None, refs=refs, job=job, strength=strength, negative=negative)
            out.append(job.asset(r["path"], kind="image", name=prompt[:60] + Path(r["path"]).suffix,
                                 meta={"prompt": prompt, "ratio": ratio, "seed": r["seed"], "provider": r["provider"], "source": source, "edited": bool(refs)}))
        return {"assets": out}
    return start(request, "image", ("Правка: " if refs else "Картинка: ") + b.prompt[:80],
                 {"prompt": prompt, "ratio": b.ratio, "seed": b.seed, "refs": refs, "strength": b.strength, "negative": b.negative, "count": b.count, "source": b.source}, run, b.project_id)

@app.get("/api/tools/voices")
def t_voices(request: Request): U(request); return {"voices": gen.voices(), "provider": P.chosen("tts")}

class VoiceIn(BaseModel):
    text: str; voice: str = "uk-UA-PolinaNeural"; rate: int = Field(0, ge=-50, le=100); pitch: int = Field(0, ge=-50, le=50)
    volume: int = Field(0, ge=-50, le=50); project_id: Optional[int] = None
@app.post("/api/tools/voice")
def t_voice(b: VoiceIn, request: Request):
    def run(job, text, voice, rate, pitch, volume):
        r = gen.tts(text, voice, rate, pitch, volume, job=job)
        a = job.asset(r["path"], kind="audio", name=text[:50].strip() + ".mp3", meta={"text": text, "voice": voice, "rate": rate, "pitch": pitch, "segments": r["segments"], "provider": r["provider"], "duration": media.probe(r["path"])["duration"]})
        return {"asset": a, "segments": r["segments"]}
    p = b.model_dump(); pid = p.pop("project_id")
    return start(request, "voice", "Озвучка: " + b.text[:80], p, run, pid)

class VideoIn(BaseModel):
    prompt: str; mode: str = "t2v"; ratio: str = "9:16"; duration: int = Field(5, ge=2, le=60); source: Optional[str] = None
    style: str = ""; camera: str = ""; characters: str = ""; resolution: str = "720p"; seed: Optional[int] = None; negative: str = ""
    project_id: Optional[int] = None; style_id: Optional[str] = None
@app.post("/api/tools/video")
def t_video(b: VideoIn, request: Request):
    u = U(request)
    if not b.prompt.strip(): raise HTTPException(400, "Опишите видео.")
    if b.mode == "v2v": raise HTTPException(400, "Видео → видео пока не поддерживает ни один из подключённых бесплатных провайдеров. Используйте «Воссоздание стиля» — оно анализирует ролик и создаёт новый.")
    img = str(asset_path(u["id"], b.source)) if b.mode == "i2v" else None
    if b.mode == "i2v" and not img: raise HTTPException(400, "Выберите стартовую картинку.")
    extras = ", ".join(x for x in (b.style and f"style: {b.style}", b.camera and f"camera: {b.camera}", b.characters and f"characters: {b.characters}") if x)
    prompt = b.prompt.strip() + (". " + extras if extras else "")
    sp, sn = intel.style_suffix(u["id"], b.style_id)
    if sp: prompt += ". " + sp
    if sn and not b.negative: b.negative = sn
    def run(job, prompt, ratio, duration, image, seed, negative, hd):
        r = gen.video(prompt, ratio, duration, image_path=image, seed=seed, job=job, negative=negative, hd=hd)
        path = r["path"]
        if hd and r.get("ai_video"):   # нейросеть выдаёт ~720p: честно увеличиваем до 1080p (помечаем в описании)
            job.progress(0.97, "Увеличиваю до 1080p…"); path = media.upscale(path, ratio); r["provider"] += " (увеличено до 1080p)"
        a = job.asset(path, kind="video", name=prompt[:60] + ".mp4", meta={"prompt": prompt, "ratio": ratio, "duration": duration, "provider": r["provider"], "ai_video": r.get("ai_video"), "seed": r["seed"], **media.probe(path)})
        return {"asset": a, "ai_video": r.get("ai_video"), "provider": r["provider"]}
    return start(request, "video", "Видео: " + b.prompt[:80], {"prompt": prompt, "ratio": b.ratio, "duration": b.duration, "image": img, "seed": b.seed, "negative": b.negative, "hd": b.resolution == "1080p"}, run, b.project_id)

class SourceIn(BaseModel): asset_id: Optional[str] = None; url: Optional[str] = None; language: str = "ru"; focus: str = ""; project_id: Optional[int] = None
@app.post("/api/tools/analyze")
def t_analyze(b: SourceIn, request: Request):
    if not b.asset_id and not (b.url or "").strip(): raise HTTPException(400, "Загрузите видео или вставьте ссылку.")
    def run(job, asset_id, url, language, focus): return tools.analyze(job, asset_id, url, language, uid=job.uid, focus=focus)
    return start(request, "analyze", "Анализ видео", {"asset_id": b.asset_id, "url": b.url, "language": b.language, "focus": b.focus}, run, b.project_id)

@app.post("/api/tools/recreate/analyze")
def t_rec_an(b: SourceIn, request: Request):
    if not b.asset_id and not (b.url or "").strip(): raise HTTPException(400, "Загрузите референсное видео или вставьте ссылку.")
    def run(job, asset_id, url): return tools.recreate_analyze(job, asset_id, url, uid=job.uid)
    return start(request, "recreate_analyze", "Разбор референса", {"asset_id": b.asset_id, "url": b.url}, run, b.project_id)

class PlanIn(BaseModel): dna: dict; locks: dict = {}; instructions: str = ""; duration: int = Field(15, ge=5, le=60); language: str = "ru"; ratio: str = "9:16"; project_id: Optional[int] = None
@app.post("/api/tools/recreate/plan")
def t_rec_plan(b: PlanIn, request: Request):
    p = b.model_dump(); pid = p.pop("project_id")
    return start(request, "recreate_plan", "План нового ролика", p, tools.recreate_plan, pid)

class ProduceIn(BaseModel): plan: dict; ratio: str = "9:16"; voice: str = "ru-RU-SvetlanaNeural"; with_voice: bool = True; with_subs: bool = True; seed: Optional[int] = None; project_id: Optional[int] = None
@app.post("/api/tools/recreate/produce")
def t_rec_prod(b: ProduceIn, request: Request):
    p = b.model_dump(); pid = p.pop("project_id")
    def run(job, **kw): return tools.recreate_produce(job, uid=job.uid, **kw)
    return start(request, "recreate", "Новый ролик: " + str(b.plan.get("title", ""))[:80], p, run, pid)

class RenderIn(BaseModel): spec: dict; name: str = "Монтаж"; hd: bool = False; project_id: Optional[int] = None
@app.post("/api/tools/editor/render")
def t_render(b: RenderIn, request: Request):
    def run(job, spec, name, hd): return tools.assemble(job, spec, job.uid, name=name, hd=hd)
    return start(request, "render", "Экспорт: " + b.name[:80], {"spec": b.spec, "name": b.name, "hd": b.hd}, run, b.project_id)

class SubsIn(BaseModel): asset_id: str; language: str = ""; project_id: Optional[int] = None
@app.post("/api/tools/editor/subtitles")
def t_subs(b: SubsIn, request: Request):
    def run(job, asset_id, language): return tools.auto_subtitles(job, asset_id, job.uid, language)
    return start(request, "subtitles", "Субтитры", {"asset_id": b.asset_id, "language": b.language}, run, b.project_id)

class MuxIn(BaseModel): video: str; audio: str; voice_volume: float = 1.0; orig_volume: float = 0.25; project_id: Optional[int] = None
@app.post("/api/tools/editor/mux")
def t_mux(b: MuxIn, request: Request):
    u = U(request); v = asset_path(u["id"], b.video, ("video",)); a = asset_path(u["id"], b.audio, ("audio",))
    def run(job, v, a, vv, ov):
        job.provider("ffmpeg на этом компьютере"); out = media.mux_voice(v, a, vv, ov); return {"asset": job.asset(out, kind="video", name="Видео с озвучкой.mp4")}
    return start(request, "mux", "Озвучка к видео", {"v": str(v), "a": str(a), "vv": b.voice_volume, "ov": b.orig_volume}, run, b.project_id)

class PhotosIn(BaseModel):
    asset_ids: List[str]; idea: str = ""; ratio: str = "9:16"; per_clip: float = Field(4.0, ge=2, le=8); ai_motion: bool = True
    voiceover: str = ""; auto_voice: bool = False; voice: str = "ru-RU-SvetlanaNeural"; language: str = "ru"; subtitles: bool = True
    captions: bool = False; music_id: Optional[str] = None; music_volume: float = Field(0.35, ge=0, le=1.5); transitions: bool = True; project_id: Optional[int] = None
@app.post("/api/tools/photos_video")
def t_photos(b: PhotosIn, request: Request):
    u = U(request)
    if not b.asset_ids: raise HTTPException(400, "Добавьте фото.")
    if len(b.asset_ids) > 20: raise HTTPException(400, "За один ролик — до 20 фото.")
    for aid in b.asset_ids:
        a = get_asset(u["id"], aid)
        if not a or a["kind"] != "image": raise HTTPException(400, "Один из файлов не является фото.")
    p = b.model_dump(); pid = p.pop("project_id")
    return start(request, "photos_video", f"Видео из {len(b.asset_ids)} фото", p, tools.photos_video, pid)

class AutoIn(BaseModel): project_id: int; ratio: str = "9:16"
@app.post("/api/tools/automontage")
def t_auto(b: AutoIn, request: Request):
    def run(job, ratio): return tools.automontage(job, job.uid, job.project_id, ratio)
    return start(request, "render", "Монтаж проекта", {"ratio": b.ratio}, run, b.project_id)

class AskIn(BaseModel): message: str; project_id: Optional[int] = None
@app.post("/api/assistant")
def t_ask(b: AskIn, request: Request):
    if not b.message.strip(): raise HTTPException(400, "Напишите сообщение.")
    def run(job, message): return tools.assistant(job.uid, job.project_id, message, job=job)
    return start(request, "assistant", "Ассистент: " + b.message[:80], {"message": b.message.strip()[:4000]}, run, b.project_id)

@app.get("/api/assistant/history")
def ask_history(request: Request, project_id: int = 0):
    u = U(request)
    with db() as c: hs = rows(c.execute("SELECT id, role, content, meta, created FROM chats WHERE user_id=? AND IFNULL(project_id,0)=? ORDER BY id DESC LIMIT 60", (u["id"], project_id)))[::-1]
    for h in hs:
        h["meta"] = jload(h["meta"])
        if h["role"] == "assistant":
            d = jload(h["content"], None)
            if isinstance(d, dict): h["content"] = d.get("reply", ""); h["ideas"] = d.get("ideas", [])
    return hs

@app.delete("/api/assistant/history")
def ask_clear(request: Request, project_id: int = 0):
    u = U(request)
    with db() as c: c.execute("DELETE FROM chats WHERE user_id=? AND IFNULL(project_id,0)=?", (u["id"], project_id))
    return {"ok": True}

import sys as _sys, cloud
cloud.install(app, _sys.modules[__name__])
remote.install(app, _sys.modules[__name__])
intel.install(app, _sys.modules[__name__])

# ---------------- интерфейс ----------------
STATIC = HERE / "static"
@app.get("/sw.js")
def sw(): return FileResponse(STATIC / "sw.js", media_type="application/javascript", headers={"Cache-Control": "no-cache"})
app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
