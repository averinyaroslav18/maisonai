"""Agnes AI (Sapiens AI, Сингапур) — настоящее ИИ-видео: персонажи двигаются, а не просто наезд камеры.

Agnes Video 2.5 Flash: 720P, 4–12 секунд, форматы 9:16/16:9/1:1/3:4. По официальной странице
(wiki.agnes-ai.com/en/docs/agnes-video-25-flash.md, проверено 22.11.2026) сейчас цена $0 за секунду
(«временно бесплатно», обычная цена $0.025/с). Ограничение бесплатного плана — около 1–2 запросов в минуту.
API: POST https://apihub.agnes-ai.com/v1/videos → video_id; GET /agnesapi?video_id=…&model_name=… → status/url.
Фото для оживления Agnes принимает ссылкой (first_frame). Сначала пробуем передать картинку напрямую (data URI);
если сервис требует ссылку из интернета — даём временную ссылку на 30 минут через облако или «доступ из любого места».
"""
import os, secrets, threading, time
from pathlib import Path
import httpx
import providers as P
from core import UserError

BASE = "https://apihub.agnes-ai.com"
MODEL = "agnes-video-2.5-flash"
CHECKED = "22.11.2026"
RATIOS = {"9:16": "9:16", "16:9": "16:9", "1:1": "1:1", "4:5": "3:4"}

make_client = lambda timeout=httpx.Timeout(60, connect=15): httpx.Client(timeout=timeout, follow_redirects=True)
_pub = {}; _lock = threading.Lock()

class AgnesBusy(UserError):
    """Лимит запросов/сервис недоступен — можно перейти на другой бесплатный вариант."""

def key() -> str:
    k = P.secret("agnes", "key")
    if not k: raise UserError("Не подключён Agnes AI. Настройки → Провайдеры ИИ → Agnes AI: вставьте бесплатный ключ с platform.agnes-ai.com.")
    return k

# ---------- временные публичные ссылки на картинку (для first_frame) ----------
def public_base() -> str:
    if os.environ.get("RENDER_EXTERNAL_URL"): return os.environ["RENDER_EXTERNAL_URL"].rstrip("/")
    if os.environ.get("MAISONAI_CLOUD") == "1" and P.load_cfg().get("cloud_url"): return P.load_cfg()["cloud_url"].rstrip("/")
    try:
        import remote
        if remote.S.get("status") == "on" and remote.S.get("url"): return remote.S["url"].rstrip("/")
    except Exception: pass
    return ""

def share(path: Path, minutes=30) -> str:
    base = public_base()
    if not base: return ""
    t = secrets.token_urlsafe(24)
    with _lock:
        for k in [k for k, v in _pub.items() if v[1] < time.time()]: _pub.pop(k, None)
        _pub[t] = (str(path), time.time() + minutes * 60)
    return f"{base}/pub/{t}.jpg"

def install(app):
    from fastapi import HTTPException
    from fastapi.responses import FileResponse

    @app.get("/pub/{token}.jpg")
    def pub(token: str):
        with _lock: v = _pub.get(token)
        if not v or v[1] < time.time() or not Path(v[0]).exists(): raise HTTPException(404, "Ссылка устарела")
        return FileResponse(v[0], media_type="image/jpeg", headers={"Cache-Control": "no-store"})

# ---------- генерация ----------
def _err(r) -> UserError:
    try: d = r.json(); msg = str((d.get("error") or {}).get("message") if isinstance(d.get("error"), dict) else d.get("error") or d.get("message") or d.get("detail") or d)
    except Exception: msg = r.text[:200]
    if r.status_code == 401: return UserError("Agnes AI не принял ключ. Проверьте его в Настройках → Провайдеры ИИ.")
    if r.status_code == 429: return AgnesBusy("Agnes AI: бесплатный лимит — примерно 1–2 видео в минуту. Подождите минуту и повторите.")
    if r.status_code == 402 or "balance" in msg.lower() or "insufficient" in msg.lower():
        return AgnesBusy("Agnes AI просит оплату — похоже, бесплатная акция для этой модели закончилась. Ничего не списано. Выберите другой бесплатный способ.")
    if r.status_code >= 500: return AgnesBusy(f"Agnes AI временно недоступен (ошибка {r.status_code}). Повторите позже.")
    return UserError(f"Agnes AI: {msg[:250]}")

def _create(c, h, body):
    for attempt in range(2):   # бесплатный план: ~1 запрос в минуту — ждём минуту один раз, потом клип сделает следующий бесплатный способ
        r = c.post(f"{BASE}/v1/videos", json=body, headers=h)
        if r.status_code != 429 or attempt == 1: return r
        time.sleep(62)
    return r

def video(prompt: str, image_path=None, seconds: float = 5, ratio: str = "9:16", seed=None, job=None, model: str = "") -> dict:
    import fal
    model = model or P.model_for("agnes", "video", MODEL)
    h = {"Authorization": f"Bearer {key()}", "Content-Type": "application/json"}
    secs = int(max(4, min(12, round(seconds))))
    body = {"model": model, "prompt": prompt[:2000], "mode": "text", "seconds": str(secs), "size": "720P", "aspect_ratio": RATIOS.get(ratio, "9:16")}
    if seed not in (None, "", -1): body["seed"] = int(seed) % 2147483647
    with make_client() as c:
        if image_path:
            body["mode"] = "keyframe"; body["first_frame"] = fal.data_uri(Path(image_path), max_side=1280)
            if job: job.progress(0.08, "Отправляю фото в Agnes AI…")
            r = _create(c, h, body)
            if r.status_code == 400:   # нужна ссылка из интернета
                link = share(Path(image_path)) if Path(image_path).suffix.lower() in (".jpg", ".jpeg") else ""
                if not link:
                    tmp = fal.tmp_path(".jpg")
                    from PIL import Image
                    Image.open(image_path).convert("RGB").save(tmp, "JPEG", quality=92); link = share(tmp)
                if not link:
                    raise UserError("Agnes AI принимает фото только ссылкой из интернета. Включите «Доступ из любого места» (Настройки) "
                                    "или работайте через облачную ссылку — тогда MaisonAI сам даст Agnes временную ссылку на фото. "
                                    "Без фото («Текст → видео») Agnes работает и так.")
                body["first_frame"] = link; r = _create(c, h, body)
        else:
            r = _create(c, h, body)
        if r.status_code not in (200, 201, 202): raise _err(r)
        d = r.json(); vid = d.get("video_id") or d.get("id")
        if not vid: raise UserError("Agnes AI не вернул номер задачи.")
        if job: job.progress(0.12, "Agnes AI принял задачу…")
        t0 = time.time(); url = ""
        while True:
            if job: job.check()
            time.sleep(3)
            s = c.get(f"{BASE}/agnesapi", params={"video_id": vid, "model_name": model}, headers={"Authorization": h["Authorization"]})
            if s.status_code == 429: time.sleep(5); continue
            if s.status_code != 200: raise _err(s)
            o = s.json(); o = o.get("data", o) if isinstance(o.get("data"), dict) else o
            st = str(o.get("status") or "").lower()
            if st == "completed": url = o.get("url") or (o.get("video") or {}).get("url", ""); break
            if st == "failed": raise UserError("Agnes AI не смог сделать видео: " + str(o.get("error") or "причина не указана")[:250])
            el = time.time() - t0
            if job:
                try: pr = float(o.get("progress") or 0) / (100 if float(o.get("progress") or 0) > 1 else 1)
                except Exception: pr = 0
                job.progress(min(0.92, 0.12 + 0.8 * max(pr, 1 - 1 / (1 + el / 90))), "Agnes AI в очереди…" if st == "queued" else "Agnes AI оживляет кадр…")
            if el > 1200: raise UserError("Agnes AI не закончил за 20 минут — попробуйте позже.")
    if not url: raise UserError("Agnes AI не вернул ссылку на видео.")
    return {"path": fal.download(url, ".mp4"), "seconds": secs, "request_id": vid}

def test() -> dict:
    with make_client() as c: r = c.get(f"{BASE}/v1/models", headers={"Authorization": f"Bearer {key()}"})
    if r.status_code == 401: raise UserError("Agnes AI не принял ключ.")
    if r.status_code >= 400: raise _err(r)
    try: ids = [m.get("id") for m in r.json().get("data", [])]
    except Exception: ids = []
    vids = [i for i in ids if i and "video" in i]
    return {"ok": True, "detail": "Ключ Agnes AI работает." + (" Видеомодели: " + ", ".join(vids[:5]) + "." if vids else "") + " Agnes Video 2.5 Flash сейчас бесплатна по акции (лимит ≈ 1–2 ролика в минуту)."}
