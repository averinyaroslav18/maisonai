"""Облако: перенос данных (экспорт/импорт), приглашения и установка MaisonAI на свой сервер одной кнопкой."""
import io, json, os, re, secrets, shutil, sqlite3, tarfile, time, zipfile
from pathlib import Path
from typing import Optional
import httpx
from fastapi import File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
import core, providers as P
from core import DATA, FILES, HERE, UserError, db, jload, rows, tmp_path

INTEL_TABLES = ("intel_videos", "styles", "characters", "blueprints", "trend_reports")
CODE_SKIP = {"data", "venv", "app_profile", "__pycache__", "tests", ".git"}

def install(app, A):
    U, can_admin = A.U, A.can_admin

    # ---------- приглашения (облако) ----------
    @app.get("/api/account/invite")
    def invite(request: Request):
        U(request)
        if not can_admin(request): raise HTTPException(403, "Только владелец видит код приглашения.")
        c = P.load_cfg()
        if not c.get("invite_code"): c["invite_code"] = secrets.token_hex(4).upper(); P.save_cfg(c)
        import remote
        return {"code": c["invite_code"], "open": bool(c.get("open_registration")), "cloud": A.CLOUD, "remote": remote.enabled()}

    class InvIn(BaseModel): regenerate: bool = False; open: Optional[bool] = None
    @app.post("/api/account/invite")
    def invite_set(b: InvIn, request: Request):
        U(request)
        if not can_admin(request): raise HTTPException(403, "Только владелец.")
        c = P.load_cfg()
        if b.regenerate: c["invite_code"] = secrets.token_hex(4).upper()
        if b.open is not None: c["open_registration"] = b.open
        P.save_cfg(c); return invite(request)

    # ---------- экспорт / импорт данных пользователя ----------
    @app.get("/api/account/export")
    def export(request: Request):
        u = U(request); uid = u["id"]
        with db() as c:
            data = {"version": core.VERSION, "exported": time.time(), "user": u["username"],
                    "projects": rows(c.execute("SELECT * FROM projects WHERE user_id=?", (uid,))),
                    "assets": rows(c.execute("SELECT * FROM assets WHERE user_id=?", (uid,))),
                    "jobs": rows(c.execute("SELECT * FROM jobs WHERE user_id=? AND status NOT IN ('queued','running')", (uid,))),
                    "chats": rows(c.execute("SELECT * FROM chats WHERE user_id=?", (uid,)))}
            for t in INTEL_TABLES: data[t] = rows(c.execute(f"SELECT * FROM {t} WHERE user_id=?", (uid,)))
        out = tmp_path(".zip")
        with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as z:
            z.writestr("maisonai.json", json.dumps(data, ensure_ascii=False))
            for a in data["assets"]:
                p = FILES / a["path"]
                if p.exists(): z.write(p, "files/" + a["id"] + p.suffix)
        return FileResponse(out, media_type="application/zip", filename=f"MaisonAI_{u['username']}_{time.strftime('%Y-%m-%d')}.zip")

    @app.post("/api/account/import")
    async def import_(request: Request, file: UploadFile = File(...)):
        u = U(request)
        tmp = tmp_path(".zip")
        with open(tmp, "wb") as f:
            while chunk := await file.read(1024 * 1024): f.write(chunk)
        try: return import_zip(u["id"], tmp)
        finally: tmp.unlink(missing_ok=True)

    # ---------- установка на свой сервер (только с компьютера) ----------
    class DeployIn(BaseModel): host: str; user: str = "ubuntu"; key: str = ""; password: str = ""; migrate: bool = True; domain: str = ""; port: int = 22
    @app.post("/api/cloud/deploy")
    def deploy(b: DeployIn, request: Request):
        U(request)
        if A.CLOUD or not A.is_local(request): raise HTTPException(403, "Устанавливать облако можно только с самого компьютера.")
        host = b.host.strip()
        if not re.fullmatch(r"[A-Za-z0-9.\-]{3,253}", host): raise HTTPException(400, "Укажите IP-адрес сервера, например 140.238.12.34")
        if not b.key.strip() and not b.password: raise HTTPException(400, "Выберите файл ключа SSH (.key), который Oracle дал при создании сервера.")
        params = {"host": host, "user": b.user.strip() or "ubuntu", "key": b.key, "password": b.password, "migrate": b.migrate, "domain": b.domain.strip(), "port": b.port}
        def run(job, **kw): return deploy_job(job, **kw)
        jid = core.submit(U(request)["id"], "deploy", "Установка в облако: " + host, params, run)
        with db() as c: c.execute("UPDATE jobs SET params='{}' WHERE id=?", (jid,))   # ключ SSH не храним в истории
        return {"job": jid}

    class RenderIn(BaseModel): hf_token: str; gh_token: str; migrate: bool = True
    @app.post("/api/cloud/render/prepare")
    def render_prepare(b: RenderIn, request: Request):
        u = U(request)
        if A.CLOUD or not A.is_local(request): raise HTTPException(403, "Готовить облако можно только с самого компьютера.")
        hf, gh = b.hf_token.strip(), b.gh_token.strip()
        if not re.fullmatch(r"hf_[A-Za-z0-9]{20,}", hf): raise HTTPException(400, "Вставьте токен Hugging Face целиком — он начинается с hf_")
        if not re.fullmatch(r"(ghp_|github_pat_)[A-Za-z0-9_]{20,}", gh): raise HTTPException(400, "Вставьте токен GitHub целиком — он начинается с ghp_")
        import hfspace
        def run(job, migrate): return hfspace.prepare_job(job, hf, gh, migrate)
        return {"job": core.submit(u["id"], "deploy", "Подготовка облака Render", {"migrate": b.migrate}, run)}

    class SaveUrlIn(BaseModel): url: str
    @app.post("/api/cloud/render/url")
    def render_url(b: SaveUrlIn, request: Request):
        U(request)
        if A.CLOUD or not A.is_local(request): raise HTTPException(403, "Только с компьютера.")
        url = b.url.strip().rstrip("/")
        if not re.fullmatch(r"https://[a-z0-9\-]+\.onrender\.com", url): raise HTTPException(400, "Вставьте адрес из Render целиком, вида https://maisonai-xxxx.onrender.com")
        c = P.load_cfg(); c["cloud_url"] = url; c["cloud_host"] = "Render"; P.save_cfg(c)
        try:
            r = httpx.get(url + "/api/info", timeout=90)
            ok = r.status_code == 200 and r.json().get("name") == "MaisonAI"
        except Exception: ok = False
        return {"ok": ok, "url": url}

    class UrlIn(BaseModel): url: str
    @app.post("/api/cloud/check")
    def cloud_check(b: UrlIn, request: Request):
        U(request)
        if not re.match(r"^https://[A-Za-z0-9.\-]+$", b.url.strip()): raise HTTPException(400, "Некорректный адрес")
        try:
            r = httpx.get(b.url.strip() + "/api/info", timeout=12)
            return {"ok": r.status_code == 200 and r.json().get("name") == "MaisonAI", "detail": f"ответ {r.status_code}"}
        except Exception as e: return {"ok": False, "detail": type(e).__name__}

    @app.get("/api/cloud/state")
    def cloud_state(request: Request):
        U(request); c = P.load_cfg()
        import hfspace
        return {"cloud": A.CLOUD, "cloud_url": c.get("cloud_url", ""), "cloud_host": c.get("cloud_host", ""), "deployed": c.get("cloud_deployed"),
                "kind": c.get("cloud_kind", "server" if c.get("cloud_url") else ""), "repo": c.get("gh_repo", ""),
                "backup": {k: v for k, v in hfspace.STATE.items() if k in ("repo", "last", "error", "enabled", "restored")}}

def import_zip(uid: int, path: Path) -> dict:
    try: z = zipfile.ZipFile(path)
    except zipfile.BadZipFile: raise UserError("Это не архив MaisonAI.")
    with z:
        try: data = json.loads(z.read("maisonai.json"))
        except KeyError: raise UserError("В архиве нет данных MaisonAI (maisonai.json).")
        names = set(z.namelist()); pmap = {}; added = {"projects": 0, "assets": 0, "jobs": 0}
        with db() as c:
            for p in data.get("projects", []):
                cur = c.execute("INSERT INTO projects(user_id,title,kind,data,favorite,created,updated) VALUES(?,?,?,?,?,?,?)",
                                (uid, p["title"], p.get("kind", "general"), p.get("data", "{}"), p.get("favorite", 0), p.get("created"), p.get("updated")))
                pmap[p["id"]] = cur.lastrowid; added["projects"] += 1
            for a in data.get("assets", []):
                if c.execute("SELECT 1 FROM assets WHERE id=?", (a["id"],)).fetchone(): continue
                ext = Path(a["path"]).suffix; member = "files/" + a["id"] + ext
                if member not in names: continue
                dst = core.new_path(uid, ext)
                with z.open(member) as src, open(dst, "wb") as out: shutil.copyfileobj(src, out)
                c.execute("INSERT INTO assets(id,user_id,project_id,kind,name,path,mime,size,meta,favorite,created) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                          (a["id"], uid, pmap.get(a.get("project_id")), a["kind"], a["name"], dst.resolve().relative_to(FILES.resolve()).as_posix(),
                           a.get("mime"), a.get("size"), a.get("meta", "{}"), a.get("favorite", 0), a.get("created")))
                added["assets"] += 1
            for j in data.get("jobs", []):
                if c.execute("SELECT 1 FROM jobs WHERE id=?", (j["id"],)).fetchone(): continue
                c.execute("INSERT INTO jobs(id,user_id,project_id,tool,title,params,status,progress,message,result,error,provider,favorite,created,started,finished) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (j["id"], uid, pmap.get(j.get("project_id")), j["tool"], j.get("title"), j.get("params", "{}"), j["status"], j.get("progress", 1), j.get("message", ""),
                           j.get("result"), j.get("error"), j.get("provider"), j.get("favorite", 0), j.get("created"), j.get("started"), j.get("finished")))
                added["jobs"] += 1
            for t in INTEL_TABLES:   # память TikTok Intelligence: стили, персонажи, планы, анализы, тренды
                for r in data.get(t, []):
                    if c.execute(f"SELECT 1 FROM {t} WHERE id=?", (r["id"],)).fetchone(): continue
                    r = dict(r); r["user_id"] = uid
                    if "project_id" in r: r["project_id"] = pmap.get(r["project_id"])
                    cols = [k for k in r if re.fullmatch(r"[a-z_]+", k)]
                    c.execute(f"INSERT INTO {t}({','.join(cols)}) VALUES({','.join('?' * len(cols))})", [r[k] for k in cols])
                    added[t] = added.get(t, 0) + 1
            for m in data.get("chats", []):
                c.execute("INSERT INTO chats(user_id,project_id,role,content,meta,created) VALUES(?,?,?,?,?,?)",
                          (uid, pmap.get(m.get("project_id")), m["role"], m["content"], m.get("meta", "{}"), m.get("created")))
    return {"ok": True, **added}

# ---------------- установка на сервер по SSH ----------------
def _code_tar() -> Path:
    out = tmp_path(".tgz")
    with tarfile.open(out, "w:gz") as t:
        for p in HERE.iterdir():
            if p.name in CODE_SKIP or p.suffix in (".log", ".lnk") or p.name in ("maisonai_secret.key",): continue
            t.add(p, arcname=p.name, filter=lambda ti: None if "__pycache__" in ti.name else ti)
    return out

def _data_tar() -> Path:
    """Снимок всех данных компьютера (база + файлы + настройки), без ключей Windows."""
    out = tmp_path(".tgz"); snap = tmp_path(".db")
    src = sqlite3.connect(core.DB); dst = sqlite3.connect(snap)
    with dst: src.backup(dst)
    src.close(); dst.close()
    with tarfile.open(out, "w:gz") as t:
        t.add(snap, arcname="maisonai.db")
        if (DATA / "config.json").exists():
            cfg = json.loads((DATA / "config.json").read_text(encoding="utf-8"))
            cfg.pop("lan_access", None); cfg.pop("cloud_url", None); cfg.pop("cloud_host", None)
            for pid in ("comfyui", "ollama"): cfg["base"].pop(pid, None)
            b = json.dumps(cfg, ensure_ascii=False).encode(); ti = tarfile.TarInfo("config.json"); ti.size = len(b); t.addfile(ti, io.BytesIO(b))
        t.add(FILES, arcname="files", filter=lambda ti: None if ti.name.endswith(".thumb.jpg") else ti)
    snap.unlink(missing_ok=True)
    return out

def _connect(host, user, key, password, port=22):
    import paramiko
    cli = paramiko.SSHClient(); cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    pkey = None
    if key.strip():
        for cls in (paramiko.Ed25519Key, paramiko.RSAKey, paramiko.ECDSAKey):
            try: pkey = cls.from_private_key(io.StringIO(key.strip() + "\n")); break
            except Exception: continue
        if pkey is None: raise UserError("Не удалось прочитать файл ключа. Нужен приватный ключ (файл ssh-key-….key), а не .pub.")
    try: cli.connect(host, port=port, username=user, pkey=pkey, password=password or None, timeout=20, banner_timeout=30, auth_timeout=30, allow_agent=False, look_for_keys=False)
    except paramiko.AuthenticationException: raise UserError(f"Сервер не принял ключ для пользователя «{user}». Для Ubuntu на Oracle пользователь — ubuntu, для Oracle Linux — opc.")
    except Exception as e: raise UserError(f"Не удалось подключиться к {host}: {e}. Проверьте IP-адрес и что сервер запущен.")
    return cli

def _exec(cli, cmd, job=None, p0=0.0, p1=1.0, timeout=1800):
    """Выполняем команду и показываем строки прогресса вида '##P 0.4 сообщение' из скрипта установки."""
    chan = cli.get_transport().open_session(); chan.set_combine_stderr(True); chan.exec_command(cmd)
    buf, out, t0 = b"", [], time.time()
    while True:
        if chan.recv_ready():
            buf += chan.recv(65536)
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1); s = line.decode("utf-8", "replace").rstrip(); out.append(s)
                m = re.match(r"##P ([\d.]+) (.*)", s)
                if m and job: job.progress(p0 + (p1 - p0) * float(m.group(1)), m.group(2))
        elif chan.exit_status_ready() and not chan.recv_ready(): break
        else: time.sleep(0.2)
        if time.time() - t0 > timeout: raise UserError("Установка на сервере идёт слишком долго.")
    code = chan.recv_exit_status()
    return code, out

def deploy_job(job, host, user, key, password, migrate, domain, port=22, verify=True):
    job.provider("SSH → ваш сервер")
    job.progress(0.02, "Подключаюсь к серверу…")
    cli = _connect(host, user, key, password, port)
    try:
        sftp = cli.open_sftp()
        code, out = _exec(cli, "test -f /var/lib/maisonai/data/maisonai.db && echo HASDATA || echo NODATA")
        has_data = "HASDATA" in out
        job.progress(0.06, "Отправляю программу…")
        sftp.put(str(_code_tar()), "/tmp/maisonai_code.tgz")
        sftp.put(str(HERE / "deploy" / "install_server.sh"), "/tmp/maisonai_install.sh")
        send_data = migrate and not has_data
        if send_data:
            job.progress(0.1, "Отправляю ваши проекты и файлы…")
            dt = _data_tar(); size = dt.stat().st_size
            sftp.put(str(dt), "/tmp/maisonai_data.tgz", callback=lambda done, total: job.progress(0.1 + 0.2 * done / max(total, 1), f"Отправляю данные: {done // 1048576} из {size // 1048576} МБ"))
        keys = {k: v for k, v in P.load_secrets().items() if v and not k.startswith("_")}
        with sftp.open("/tmp/maisonai_keys.json", "w") as f: f.write(json.dumps(keys))
        sftp.chmod("/tmp/maisonai_keys.json", 0o600)
        sftp.close()
        dom = domain or (host.replace(".", "-") + ".sslip.io" if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", host) else host)
        job.progress(0.32, "Устанавливаю на сервере (5–10 минут)…")
        code, out = _exec(cli, f"sudo -n bash /tmp/maisonai_install.sh {dom} {'1' if send_data else '0'} 2>&1", job, 0.32, 0.92)
        if code != 0:
            tail = "\n".join(l for l in out[-12:] if not l.startswith("##P"))
            raise UserError("Установка на сервере не удалась:\n" + tail[-900:])
    finally:
        cli.close()
    url = f"https://{dom}"
    job.progress(0.94, "Проверяю доступ из интернета…")
    ok, why = False, ""
    for _ in range(18 if verify else 0):
        try:
            r = httpx.get(url + "/api/info", timeout=10)
            if r.status_code == 200 and r.json().get("name") == "MaisonAI": ok = True; break
            why = f"ответ {r.status_code}"
        except Exception as e: why = type(e).__name__
        time.sleep(5)
    c = P.load_cfg(); c["cloud_url"] = url; c["cloud_host"] = host; c["cloud_deployed"] = time.strftime("%Y-%m-%d %H:%M"); P.save_cfg(c)
    return {"url": url, "reachable": ok, "migrated": send_data, "note": "" if ok else
            "Программа установлена, но из интернета пока не открывается (" + why + "). Почти всегда причина — закрытые порты 80 и 443 в Oracle: "
            "откройте их по инструкции в Настройки → Облако и нажмите «Проверить адрес»."}
