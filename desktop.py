"""MaisonAI как отдельная программа: своё окно без вкладок и адресной строки, без окна терминала."""
import ctypes, os, shutil, socket, subprocess, sys, time, threading, traceback, urllib.request, webbrowser
from pathlib import Path

HOST, PORT = "127.0.0.1", int(os.environ.get("MAISONAI_PORT", "8790"))
URL = f"http://{HOST}:{PORT}"
HERE = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
os.chdir(HERE)
NO_WINDOW = bool(os.environ.get("MAISONAI_NO_WINDOW")) or "background" in sys.argv[1:]   # автозапуск с Windows — без окна
LOG = HERE / "maisonai.log"
if LOG.exists() and LOG.stat().st_size > 2_000_000: LOG.unlink()
if sys.stdout is None: sys.stdout = open(LOG, "a", encoding="utf-8")   # pythonw: консоли нет
if sys.stderr is None: sys.stderr = sys.stdout

def alert(msg):
    try: ctypes.windll.user32.MessageBoxW(0, msg, "MaisonAI", 0x10)
    except Exception: print(msg)

def running():
    try: urllib.request.urlopen(URL + "/api/info", timeout=2).read(); return True
    except Exception: return False

def port_busy():
    s = socket.socket(); s.settimeout(0.5)
    try: return s.connect_ex((HOST, PORT)) == 0
    finally: s.close()

def find_browser():
    for b in filter(None, (os.environ.get(k) for k in ("ProgramFiles", "ProgramFiles(x86)", "LocalAppData"))):
        for rel in ("Microsoft/Edge/Application/msedge.exe", "Google/Chrome/Application/chrome.exe", "BraveSoftware/Brave-Browser/Application/brave.exe"):
            if (Path(b) / rel).exists(): return str(Path(b) / rel)
    return next(filter(None, (shutil.which(x) for x in ("msedge", "chrome", "google-chrome", "chromium"))), None)

def open_window():
    b = find_browser()
    if not b: return None
    return subprocess.Popen([b, f"--app={URL}", f"--user-data-dir={HERE / 'app_profile'}", "--window-size=1440,920",
                             "--no-first-run", "--no-default-browser-check", "--disable-features=Translate", "--autoplay-policy=no-user-gesture-required"])

def busy_jobs(app):
    try:
        with app.db() as c: return c.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0]
    except Exception: return 0

def main():
    ow = lambda: None if NO_WINDOW else open_window()
    if running():                      # уже запущено: просто ещё одно окно
        if ow() is None: webbrowser.open(URL)
        return 0
    if port_busy():
        alert(f"Порт {PORT} занят другой программой. Закройте её и запустите MaisonAI снова."); return 1
    import uvicorn, app
    # слушаем сеть, но устройства по Wi-Fi пускаются, только если доступ включён в Настройках
    threading.Thread(target=lambda: uvicorn.run(app.app, host="0.0.0.0", port=PORT, log_level="warning", log_config=None), daemon=True).start()
    for _ in range(120):
        if running(): break
        time.sleep(0.25)
    else:
        alert("Не удалось запустить MaisonAI. Подробности в файле maisonai.log."); return 1
    p = ow()
    if p is None and not NO_WINDOW:
        alert("Не найден браузер Edge или Chrome для окна программы. MaisonAI откроется в обычном браузере."); webbrowser.open(URL)
    t0 = time.time()
    while True:   # закрываемся, только когда окна нет, задачи не идут и к серверу давно не обращались
        time.sleep(3)
        if p is not None and p.poll() is None: continue
        if busy_jobs(app): continue
        idle = time.time() - app.LAST_SEEN[0]
        if app.remote_enabled(): continue   # включён доступ из любого места — работаем всегда
        lan = app.lan_enabled()
        # окно шлёт «пульс» каждые 20 с; браузер мог отдать окно уже открытому Edge, поэтому ориентируемся на пульс
        limit = 1800 if lan else (900 if time.time() - t0 < 120 else 240)
        if idle > limit:
            print("[%s] остановлено: окно закрыто, задач нет, простой %d сек" % (time.strftime("%Y-%m-%d %H:%M:%S"), idle)); return 0

if __name__ == "__main__":
    try: code = main()
    except Exception:
        traceback.print_exc(); alert("Ошибка запуска MaisonAI. Подробности в файле maisonai.log."); code = 1
    sys.stdout.flush(); os._exit(code)
