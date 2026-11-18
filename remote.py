"""Доступ из любого места (без облака и без карты): бесплатный туннель Cloudflare к MaisonAI на компьютере.

• cloudflared (официальная программа Cloudflare) скачивается один раз и открывает защищённую ссылку
  https://….trycloudflare.com — она работает с любого устройства, пока компьютер включён.
• Такая ссылка меняется после перезапуска. Для постоянной ссылки в вашем аккаунте Cloudflare
  создаётся маленький Worker (https://maisonai.<ваше-имя>.workers.dev), который пересылает на текущую.
• Пока доступ включён: программа стартует вместе с Windows (без окна) и не даёт компьютеру уснуть.
Посторонние не войдут: из интернета — только вход по логину, регистрация — по коду приглашения.
"""
import os, re, shutil, subprocess, sys, threading, time, traceback
from pathlib import Path
import httpx
import providers as P
from core import HERE, UserError

PORT = int(os.environ.get("MAISONAI_PORT", "8790"))
BIN = HERE / "bin"
EXE = BIN / ("cloudflared.exe" if sys.platform == "win32" else "cloudflared")
DL = {"win32": "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe",
      "linux": "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64",
      "darwin": "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-amd64.tgz"}
CF_API = "https://api.cloudflare.com/client/v4"
WORKER = "maisonai"
NOWIN = 0x08000000 if sys.platform == "win32" else 0
S = {"status": "off", "url": "", "error": "", "proc": None, "stop": threading.Event(), "thread": None, "dl": 0.0, "since": None}
popen = subprocess.Popen   # подмена в тестах

def enabled() -> bool: return bool(P.load_cfg().get("remote_access"))

def via_tunnel(request) -> bool:
    """Запрос пришёл из интернета через Cloudflare (а не с самого компьютера)."""
    h = request.headers
    return "cf-connecting-ip" in h or "cf-ray" in h

def public_state() -> dict:
    c = P.load_cfg()
    return {"enabled": bool(c.get("remote_access")), "status": S["status"], "url": S["url"], "error": S["error"],
            "download": round(S["dl"], 2), "stable_url": c.get("remote_stable_url", ""), "stable_error": c.get("remote_stable_error", ""),
            "autostart": autostart_on(), "since": S["since"]}

# ---------------- cloudflared ----------------
def ensure_binary():
    w = shutil.which("cloudflared")
    if EXE.exists() and EXE.stat().st_size > 1_000_000: return EXE
    if w: return Path(w)
    url = DL.get(sys.platform)
    if not url: raise UserError("Для этой системы нет готовой программы туннеля.")
    S["status"] = "downloading"; BIN.mkdir(exist_ok=True)
    tmp = EXE.with_suffix(".part")
    try:
        with httpx.stream("GET", url, follow_redirects=True, timeout=60) as r:
            r.raise_for_status(); total = int(r.headers.get("content-length") or 0); done = 0
            with open(tmp, "wb") as f:
                for chunk in r.iter_bytes(1 << 16):
                    f.write(chunk); done += len(chunk); S["dl"] = done / total if total else 0
                    if S["stop"].is_set(): raise UserError("Отменено")
    except UserError: raise
    except Exception as e:
        tmp.unlink(missing_ok=True)
        raise UserError(f"Не удалось скачать программу туннеля Cloudflare ({type(e).__name__}). Проверьте интернет и нажмите «Включить» ещё раз.")
    if url.endswith(".tgz"):
        import tarfile
        with tarfile.open(tmp) as t: t.extract("cloudflared", BIN)
        tmp.unlink()
    else: tmp.replace(EXE)
    try: os.chmod(EXE, 0o755)
    except Exception: pass
    return EXE

def _keep_awake(on: bool):
    """Windows: не засыпать, пока включён доступ (экран при этом гаснуть может)."""
    if sys.platform != "win32": return
    try:
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | (0x00000001 if on else 0))
    except Exception: pass

def _run_once(exe):
    S["status"] = "starting"; S["url"] = ""
    p = popen([str(exe), "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{PORT}"],
              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, creationflags=NOWIN, text=True, encoding="utf-8", errors="replace")
    S["proc"] = p; tail = []
    for line in p.stdout:
        tail = (tail + [line.strip()])[-15:]
        m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
        if m and not S["url"]:
            S.update(url=m.group(0), status="on", error="", since=time.strftime("%Y-%m-%d %H:%M"))
            threading.Thread(target=_after_url, daemon=True).start()
        if S["stop"].is_set(): break
    try: p.wait(timeout=5)
    except Exception: p.kill()
    return "\n".join(tail)

def _after_url():
    if (P.load_secrets().get("_cfworker") or {}).get("token"):
        try: update_link()
        except Exception as e:
            c = P.load_cfg(); c["remote_stable_error"] = str(e)[:300]; P.save_cfg(c)

def _loop():
    fails = 0
    while not S["stop"].is_set():
        _keep_awake(True)
        try:
            exe = ensure_binary()
            tail = _run_once(exe)
            if S["stop"].is_set(): break
            fails += 1
            S.update(status="error", url="", error="Туннель остановился, перезапускаю…" + (f" ({tail.splitlines()[-1][:160]})" if tail.strip() else ""))
        except UserError as e:
            fails += 1; S.update(status="error", url="", error=str(e))
        except Exception as e:
            fails += 1; traceback.print_exc(); S.update(status="error", url="", error=f"{type(e).__name__}: {str(e)[:200]}")
        S["stop"].wait(min(10 * fails, 120))
    _keep_awake(False)
    S.update(status="off", url="", proc=None, since=None)

def start():
    if S["thread"] and S["thread"].is_alive(): return
    S["stop"] = threading.Event(); S["error"] = ""
    S["thread"] = threading.Thread(target=_loop, daemon=True, name="remote-tunnel"); S["thread"].start()

def stop():
    S["stop"].set()
    p = S.get("proc")
    if p and p.poll() is None:
        try: p.terminate()
        except Exception: pass
    S.update(status="off", url="")

def set_enabled(on: bool):
    c = P.load_cfg(); c["remote_access"] = bool(on); P.save_cfg(c)
    set_autostart(on)
    start() if on else stop()

# ---------------- автозапуск с Windows ----------------
def _startup_lnk():
    ap = os.environ.get("APPDATA")
    return Path(ap) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "MaisonAI.lnk" if ap else None

def autostart_on() -> bool:
    l = _startup_lnk(); return bool(l and l.exists())

def set_autostart(on: bool):
    if sys.platform != "win32": return
    l = _startup_lnk()
    if not l: return
    try:
        if not on: l.unlink(missing_ok=True); return
        vbs = HERE / "MaisonAI.vbs"
        ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%s');$s.TargetPath='wscript.exe';"
              "$s.Arguments='\"%s\" background';$s.WorkingDirectory='%s';$s.IconLocation='%s';$s.Save()") % (
              str(l).replace("'", "''"), str(vbs).replace("'", "''"), str(HERE).replace("'", "''"), str(HERE / "maisonai.ico").replace("'", "''"))
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps], creationflags=NOWIN, timeout=30, capture_output=True)
    except Exception: traceback.print_exc()

# ---------------- постоянная ссылка: Cloudflare Worker ----------------
WORKER_JS = r"""const TARGET = %s;
const OFF = `<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MaisonAI</title><body style="margin:0;min-height:100vh;display:grid;place-items:center;background:#07080a;color:#e9ecef;font:16px system-ui;text-align:center;padding:24px">
<div><h1 style="font-size:26px;margin:0 0 12px">MaisonAI сейчас недоступна</h1><p style="color:#9aa0a6;max-width:420px">Компьютер с программой выключен, спит или нет интернета.
Включите компьютер — MaisonAI запустится сама, и эта ссылка снова заработает через 1–2 минуты.</p></div></body></html>`;
const off = () => new Response(OFF, { status: 503, headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" } });
export default {
  async fetch(req) {
    if (!TARGET) return off();
    const u = new URL(req.url), t = new URL(TARGET);
    u.protocol = t.protocol; u.hostname = t.hostname; u.port = "";
    try {
      const r = await fetch(new Request(u, req), { redirect: "manual" });
      if ([502, 503, 504, 521, 522, 523, 530].includes(r.status) && !u.pathname.startsWith("/api/")) return off();
      return r;
    } catch (e) { return off(); }
  }
};
"""

def _cf(method, path, token, **kw):
    r = httpx.request(method, CF_API + path, headers={"Authorization": f"Bearer {token}"}, timeout=30, **kw)
    try: j = r.json()
    except Exception: j = {}
    if r.status_code in (401, 403) or (j.get("errors") and any(e.get("code") in (10000, 9109) for e in j["errors"])):
        raise UserError("Cloudflare не принял токен для Workers. Создайте токен по шаблону «Edit Cloudflare Workers» и вставьте его целиком.")
    return r.status_code, j

def _account(token):
    acc = P.secret("cloudflare", "account")
    if acc: return acc
    code, j = _cf("GET", "/accounts", token)
    res = j.get("result") or []
    if not res: raise UserError("Не нашёл аккаунт Cloudflare для этого токена. При создании токена в «Account Resources» выберите свой аккаунт.")
    return res[0]["id"]

def update_link(token=None) -> str:
    sec = P.load_secrets()
    token = token or (sec.get("_cfworker") or {}).get("token")
    if not token: raise UserError("Нет токена Cloudflare для постоянной ссылки.")
    acc = _account(token)
    import json
    js = WORKER_JS % json.dumps(S["url"] or "")
    files = {"metadata": (None, json.dumps({"main_module": "worker.js", "compatibility_date": "2024-09-23"}), "application/json"),
             "worker.js": ("worker.js", js.encode(), "application/javascript+module")}
    code, j = _cf("PUT", f"/accounts/{acc}/workers/scripts/{WORKER}", token, files=files)
    if not j.get("success"): raise UserError("Cloudflare не сохранил Worker: " + "; ".join(e.get("message", "") for e in j.get("errors") or [])[:200])
    _cf("POST", f"/accounts/{acc}/workers/scripts/{WORKER}/subdomain", token, json={"enabled": True, "previews_enabled": False})
    code, j = _cf("GET", f"/accounts/{acc}/workers/subdomain", token)
    sub = (j.get("result") or {}).get("subdomain")
    if not sub:   # у аккаунта ещё нет адреса workers.dev — создаём
        base = re.sub(r"[^a-z0-9-]", "", (P.load_cfg().get("owner_name") or "maisonai").lower())[:20] or "maisonai"
        for cand in [base + "-" + acc[:6], "maisonai-" + acc[:10]]:
            code, j = _cf("PUT", f"/accounts/{acc}/workers/subdomain", token, json={"subdomain": cand})
            if j.get("success"): sub = cand; break
    if not sub: raise UserError("Не удалось включить адрес workers.dev. Откройте dash.cloudflare.com → Workers & Pages один раз и повторите.")
    url = f"https://{WORKER}.{sub}.workers.dev"
    c = P.load_cfg(); c["remote_stable_url"] = url; c["remote_stable_error"] = ""; P.save_cfg(c)
    if token != (sec.get("_cfworker") or {}).get("token"):
        sec["_cfworker"] = {"token": token}; P.save_secrets(sec)
    return url

def remove_link():
    sec = P.load_secrets(); sec.pop("_cfworker", None); P.save_secrets(sec)
    c = P.load_cfg(); c.pop("remote_stable_url", None); c.pop("remote_stable_error", None); P.save_cfg(c)

def install(app, A):
    from fastapi import HTTPException, Request
    from pydantic import BaseModel

    @app.get("/api/remote")
    def remote_state(request: Request):
        A.U(request); s = public_state(); s["local"] = A.is_local(request); s["cloud"] = A.CLOUD; return s

    class OnIn(BaseModel): enabled: bool
    @app.post("/api/remote")
    def remote_set(b: OnIn, request: Request):
        A.U(request)
        if A.CLOUD or not A.is_local(request): raise HTTPException(403, "Включать доступ можно только на самом компьютере.")
        set_enabled(b.enabled); A._rem["t"] = 0; return remote_state(request)

    class LinkIn(BaseModel): token: str = ""
    @app.post("/api/remote/link")
    def remote_link(b: LinkIn, request: Request):
        A.U(request)
        if A.CLOUD or not A.is_local(request): raise HTTPException(403, "Настраивать ссылку можно только на самом компьютере.")
        t = b.token.strip()
        if not t: remove_link(); return remote_state(request)
        if not re.fullmatch(r"[A-Za-z0-9_\-]{30,80}", t): raise HTTPException(400, "Вставьте токен Cloudflare целиком (длинная строка из букв и цифр).")
        update_link(t); return remote_state(request)

    @app.on_event("startup")
    def _auto():
        if not A.CLOUD and enabled() and not os.environ.get("MAISONAI_NO_REMOTE"): start()

    @app.on_event("shutdown")
    def _bye(): stop()
