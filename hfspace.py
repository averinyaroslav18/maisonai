"""Облако без карты: MaisonAI на бесплатном сервере Render + ваши данные в закрытом архиве Hugging Face.

У бесплатного сервера Render диск временный: после «сна» (15 минут без посетителей) или перезапуска всё
стирается. Поэтому сервер при запуске забирает данные из закрытого архива (private dataset на Hugging Face),
а потом каждые полторы минуты отправляет туда изменения: базу, настройки, файлы и зашифрованные ключи ИИ.
Ключ шифрования выводится из токена Hugging Face, который хранится только в настройках сервера Render.

На компьютере кнопка «Подготовить» переносит данные в архив и выкладывает программу на GitHub,
откуда Render её собирает (Dockerfile). Токены не сохраняются в истории.
"""
import base64, hashlib, json, os, re, shutil, sqlite3, tempfile, threading, time, traceback
from pathlib import Path
import core, providers as P
from core import DATA, FILES, HERE, UserError

BACKUP_REPO = os.environ.get("MAISONAI_BACKUP_REPO", "")
DATA_NAME = "maisonai-data"
STATE = {"repo": BACKUP_REPO, "restored": None, "last": None, "error": "", "enabled": False}
CODE_SKIP = {"data", "venv", "app_profile", "__pycache__", "tests", ".git", "deploy", ".cache", "bin"}
CODE_SKIP_SUFFIX = {".log", ".lnk", ".bat", ".vbs", ".ps1", ".pyc", ".part"}
make_api = None   # подмена в тестах
gh_request = None # подмена в тестах

def _api(token=None):
    if make_api: return make_api(token)
    from huggingface_hub import HfApi
    return HfApi(token=token)

def _token(): return os.environ.get("HF_TOKEN", "").strip()

def derive_secret(tok: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(b"maisonai-keys:" + tok.encode()).digest()).decode()

def _setup_env():
    """На сервере достаточно одной настройки HF_TOKEN: из неё — ключ шифрования и имя архива."""
    global BACKUP_REPO
    tok = _token()
    if os.environ.get("MAISONAI_CLOUD") != "1" or not tok: return
    os.environ.setdefault("MAISONAI_SECRET", derive_secret(tok))
    if not BACKUP_REPO:
        try: BACKUP_REPO = (_api(tok).whoami().get("name") or "") + "/" + DATA_NAME
        except Exception as e:
            STATE["error"] = f"Hugging Face не принял HF_TOKEN: {type(e).__name__}. Проверьте переменную HF_TOKEN в настройках Render."
            BACKUP_REPO = ""
    STATE["repo"] = BACKUP_REPO

# ====================== на сервере: восстановление и резервные копии ======================
def restore():
    """Вызывается до открытия базы. Забирает данные из закрытого архива, если диск пустой."""
    _setup_env()
    if not BACKUP_REPO: return
    if core.DB.exists():
        STATE.update(restored=False, enabled=True); return
    try:
        api = _api(_token())
        files = set(api.list_repo_files(BACKUP_REPO, repo_type="dataset"))
        if "maisonai.db" not in files:   # архив ещё пустой — новая установка
            STATE.update(restored=False, enabled=True); return
        if make_api: api.download_to(BACKUP_REPO, DATA)
        else:
            from huggingface_hub import snapshot_download
            snapshot_download(BACKUP_REPO, repo_type="dataset", local_dir=str(DATA), token=_token(),
                              allow_patterns=["maisonai.db", "config.json", "keys.dat", "files/**"])
        shutil.rmtree(DATA / ".cache", ignore_errors=True)
        STATE.update(restored=True, enabled=True)
        print(f"[MaisonAI] данные восстановлены из {BACKUP_REPO}", flush=True)
    except Exception as e:
        # не включаем резервное копирование: иначе пустая база затёрла бы настоящие данные в архиве
        STATE.update(enabled=False, error=f"Не удалось забрать данные из архива: {type(e).__name__}: {str(e)[:200]}")
        traceback.print_exc()

_known = {}           # путь в архиве → (размер, время изменения) уже отправленных файлов
_sig = {"v": None}
_lock = threading.Lock()

def _signature():
    parts = []
    for p in (core.DB, Path(str(core.DB) + "-wal"), DATA / "config.json", DATA / "keys.dat"):
        try: st = p.stat(); parts.append((p.name, st.st_size, int(st.st_mtime)))
        except FileNotFoundError: pass
    n = sz = mt = 0
    for p in FILES.rglob("*"):
        if p.is_file() and not p.name.endswith(".thumb.jpg"):
            st = p.stat(); n += 1; sz += st.st_size; mt = max(mt, int(st.st_mtime))
    return tuple(parts) + ((n, sz, mt),)

def backup_now(force=False):
    if not STATE["enabled"]: return False
    with _lock:
        sig = _signature()
        if sig == _sig["v"] and not force: return False
        from huggingface_hub import CommitOperationAdd, CommitOperationDelete
        api = _api(_token())
        tmp = Path(tempfile.mkdtemp(prefix="mai_bk_"))
        try:
            snap = tmp / "maisonai.db"
            src = sqlite3.connect(core.DB); dst = sqlite3.connect(snap)
            with dst: src.backup(dst)
            src.close(); dst.close()
            ops = [CommitOperationAdd("maisonai.db", str(snap))]
            for name in ("config.json", "keys.dat"):
                if (DATA / name).exists():
                    shutil.copy2(DATA / name, tmp / name); ops.append(CommitOperationAdd(name, str(tmp / name)))
            local = {}
            for p in FILES.rglob("*"):
                if p.is_file() and not p.name.endswith(".thumb.jpg"):
                    st = p.stat(); local["files/" + p.relative_to(FILES).as_posix()] = ((st.st_size, int(st.st_mtime)), p)
            if not STATE.get("listed"):   # первый раз: что уже лежит в архиве, повторно не отправляем
                for f in api.list_repo_files(BACKUP_REPO, repo_type="dataset"):
                    if f.startswith("files/"): _known[f] = local[f][0] if f in local else None
                STATE["listed"] = True
            now = {rel: v[0] for rel, v in local.items()}
            for rel, (stat, p) in local.items():
                if _known.get(rel) != stat: ops.append(CommitOperationAdd(rel, str(p)))
            gone = [f for f in _known if f not in now]
            ops += [CommitOperationDelete(f) for f in gone]
            api.create_commit(BACKUP_REPO, ops, commit_message="MaisonAI: автосохранение", repo_type="dataset")
            for f in gone: _known.pop(f, None)
            _known.update(now); _sig["v"] = sig
            STATE.update(last=time.strftime("%Y-%m-%d %H:%M:%S"), error="")
            return True
        except Exception as e:
            STATE["error"] = f"Автосохранение не удалось: {type(e).__name__}: {str(e)[:200]}"
            traceback.print_exc(); return False
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

def start_backups(interval=90):
    if not STATE["enabled"]: return
    def loop():
        time.sleep(30)
        while True:
            try: backup_now()
            except Exception: traceback.print_exc()
            time.sleep(interval)
    threading.Thread(target=loop, daemon=True, name="hf-backup").start()

# ====================== на компьютере: подготовка облака Render ======================
DOCKERFILE = """FROM python:3.11-slim
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH PYTHONUNBUFFERED=1 \\
    MAISONAI_CLOUD=1 MAISONAI_DATA=/home/user/data MAISONAI_KEYFILE=/home/user/unused.key MAISONAI_WORKERS=1 MAISONAI_LOWMEM=1
WORKDIR /home/user/app
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt
COPY --chown=user . .
EXPOSE 10000
CMD ["sh", "-c", "exec python -m uvicorn app:app --host 0.0.0.0 --port ${PORT:-10000} --proxy-headers --forwarded-allow-ips '*'"]
"""
REPO_README = """# MaisonAI (личный сервер)

Код личной студии MaisonAI для бесплатного сервера Render. Секретов здесь нет:
ключи и данные хранятся в закрытом архиве Hugging Face и в настройках сервера.
"""

def _code_files() -> dict:
    """Путь в репозитории → байты."""
    out = {}
    for p in sorted(HERE.rglob("*")):
        if not p.is_file(): continue
        rel = p.relative_to(HERE)
        if rel.parts[0] in CODE_SKIP or "__pycache__" in rel.parts or p.suffix.lower() in CODE_SKIP_SUFFIX: continue
        if p.name in ("maisonai_secret.key", "maisonai.ico") or p.name.startswith("README_"): continue
        out[rel.as_posix()] = p.read_bytes()
    out["Dockerfile"] = DOCKERFILE.encode(); out["README.md"] = REPO_README.encode()
    out[".dockerignore"] = b"__pycache__\n*.pyc\ndata\n.git\n"
    return out

def _upload_data(api, repo, job, hf_token):
    """Перенос: база (копия), настройки без локальных адресов, файлы и ключи ИИ (зашифрованы)."""
    from huggingface_hub import CommitOperationAdd
    from cryptography.fernet import Fernet
    tmp = Path(tempfile.mkdtemp(prefix="mai_mig_"))
    try:
        snap = tmp / "maisonai.db"
        src = sqlite3.connect(core.DB); dst = sqlite3.connect(snap)
        with dst: src.backup(dst)
        src.close(); dst.close()
        ops = [CommitOperationAdd("maisonai.db", str(snap))]
        if (DATA / "config.json").exists():
            cfg = json.loads((DATA / "config.json").read_text(encoding="utf-8"))
            for k in ("lan_access", "remote_access", "remote_stable_url", "remote_stable_error", "cloud_url", "cloud_host", "cloud_kind", "gh_repo", "cloud_deployed"): cfg.pop(k, None)
            for pid in ("comfyui", "ollama"): (cfg.get("base") or {}).pop(pid, None)
            (tmp / "config.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
            ops.append(CommitOperationAdd("config.json", str(tmp / "config.json")))
        keys = {k: v for k, v in P.load_secrets().items() if v and not k.startswith("_")}
        keys["hf_spaces"] = keys.get("hf_spaces") or {"key": hf_token}
        (tmp / "keys.dat").write_bytes(b"F" + Fernet(derive_secret(hf_token).encode()).encrypt(json.dumps(keys).encode()))
        ops.append(CommitOperationAdd("keys.dat", str(tmp / "keys.dat")))
        size = 0
        for p in FILES.rglob("*"):
            if p.is_file() and not p.name.endswith(".thumb.jpg"):
                ops.append(CommitOperationAdd("files/" + p.relative_to(FILES).as_posix(), str(p))); size += p.stat().st_size
        job.progress(0.15, f"Переношу проекты, файлы и ключи ({size // 1048576} МБ)…")
        api.create_commit(repo, ops, commit_message="MaisonAI: перенос с компьютера", repo_type="dataset")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

def _gh(method, path, token, **kw):
    import httpx
    if gh_request: return gh_request(method, path, token, **kw)
    r = httpx.request(method, "https://api.github.com" + path, timeout=60, headers={"Authorization": f"Bearer {token}",
                      "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}, **kw)
    try: j = r.json()
    except Exception: j = {}
    return r.status_code, j

def push_github(token, name, job, p0=0.45, p1=0.9):
    code, me = _gh("GET", "/user", token)
    if code == 401: raise UserError("GitHub не принял токен. Создайте его заново по ссылке в инструкции и вставьте целиком (начинается с ghp_).")
    if code != 200: raise UserError(f"GitHub ответил ошибкой {code}. Попробуйте ещё раз через минуту.")
    owner = me["login"]
    code, repo = _gh("GET", f"/repos/{owner}/{name}", token)
    if code == 404:
        code, repo = _gh("POST", "/user/repos", token, json={"name": name, "private": False, "auto_init": True, "description": "MaisonAI — личный сервер"})
        if code not in (200, 201):
            raise UserError("Не удалось создать репозиторий на GitHub" + (": у токена нет права «public_repo» — создайте токен по ссылке из инструкции." if code in (403, 404) else f" (ошибка {code})."))
        time.sleep(2)
    branch = repo.get("default_branch") or "main"
    code, ref = _gh("GET", f"/repos/{owner}/{name}/git/ref/heads/{branch}", token)
    parent = (ref.get("object") or {}).get("sha") if code == 200 else None
    files = _code_files(); tree = []
    for i, (path, data) in enumerate(files.items()):
        code, b = _gh("POST", f"/repos/{owner}/{name}/git/blobs", token, json={"content": base64.b64encode(data).decode(), "encoding": "base64"})
        if code not in (200, 201): raise UserError(f"GitHub не принял файл {path} (ошибка {code}).")
        tree.append({"path": path, "mode": "100644", "type": "blob", "sha": b["sha"]})
        if i % 5 == 0: job.progress(p0 + (p1 - p0) * 0.9 * i / len(files), f"Выкладываю программу на GitHub: {i + 1} из {len(files)}")
    code, t = _gh("POST", f"/repos/{owner}/{name}/git/trees", token, json={"tree": tree})
    if code not in (200, 201): raise UserError(f"GitHub: не удалось собрать файлы (ошибка {code}).")
    code, cm = _gh("POST", f"/repos/{owner}/{name}/git/commits", token, json={"message": f"MaisonAI {core.VERSION}", "tree": t["sha"], "parents": [parent] if parent else []})
    if code not in (200, 201): raise UserError(f"GitHub: не удалось сохранить версию (ошибка {code}).")
    if parent: code, _ = _gh("PATCH", f"/repos/{owner}/{name}/git/refs/heads/{branch}", token, json={"sha": cm["sha"], "force": True})
    else: code, _ = _gh("POST", f"/repos/{owner}/{name}/git/refs", token, json={"ref": f"refs/heads/{branch}", "sha": cm["sha"]})
    if code not in (200, 201): raise UserError(f"GitHub: не удалось обновить ветку (ошибка {code}).")
    return f"https://github.com/{owner}/{name}"

def prepare_job(job, hf_token, gh_token, migrate=True, name="maisonai"):
    job.provider("Hugging Face + GitHub → Render")
    job.progress(0.02, "Проверяю токен Hugging Face…")
    api = _api(hf_token)
    try: who = api.whoami()
    except Exception as e:
        raise UserError("Hugging Face не принял токен. Скопируйте его ещё раз целиком (начинается с hf_)." + (f" ({str(e)[:120]})" if "401" not in str(e) else ""))
    tok = ((who.get("auth") or {}).get("accessToken") or {})
    if tok.get("role") == "read":
        raise UserError("Этот токен Hugging Face только для чтения (Read). Нужен токен с типом «Write»: "
                        "huggingface.co/settings/tokens → Create new token → вкладка «Write» → Create token.")
    data_id = f"{who.get('name')}/{DATA_NAME}"
    job.progress(0.06, "Создаю закрытый архив для ваших данных…")
    try: api.create_repo(data_id, repo_type="dataset", private=True, exist_ok=True)
    except Exception as e:
        raise UserError(f"Не удалось создать закрытый архив на Hugging Face: {str(e)[:200]}")
    migrated = kept = False
    if migrate:
        if "maisonai.db" in set(api.list_repo_files(data_id, repo_type="dataset")): kept = True
        else: _upload_data(api, data_id, job, hf_token); migrated = True
    job.progress(0.45, "Выкладываю программу на GitHub…")
    repo_url = push_github(gh_token, name, job)
    c = P.load_cfg(); c.update(cloud_kind="render", gh_repo=repo_url, cloud_deployed=time.strftime("%Y-%m-%d %H:%M")); P.save_cfg(c)
    job.progress(0.98, "Готово — осталось 6 кликов в Render")
    return {"repo": repo_url, "dataset": data_id, "migrated": migrated, "kept": kept}
