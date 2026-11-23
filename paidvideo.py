"""Платное видео напрямую у создателей моделей: Google Veo 3.1 (Gemini API) и Runway.

Как и fal.ai: цена считается до запуска, показывается пользователю, запуск только после подтверждения
и в пределах бюджета (billing.paid_call). Без автоповторов — повтор = повторная оплата.
Цены — официальные тарифы, проверено 21.11.2026:
  Veo 3.1 (Gemini API, за секунду, со звуком): Lite 720p $0.05, Fast 720p $0.10, Standard $0.40; длина 4/6/8 с.
  Runway API (1 кредит = $0.01): gen4_turbo 5 кр/с, gen4.5 12 кр/с, kling3.0_standard без звука 9 кр/с; длина 5 или 10 с.
"""
import base64, time
from pathlib import Path
import httpx
import providers as P
from core import UserError
import fal

CHECKED = "21.11.2026"

class PaidDown(UserError):
    """Сервис недоступен или закончился баланс — ничего не списано, можно перейти на бесплатный вариант."""

make_client = lambda timeout=httpx.Timeout(60, connect=15): httpx.Client(timeout=timeout, follow_redirects=True)

# ---------------- Google Veo 3.1 ----------------
VEO_BASE = "https://generativelanguage.googleapis.com/v1beta"
VEO = {
    "veo-3.1-lite-generate-preview": {"label": "Veo 3.1 Lite · 720p со звуком · дешевле всех у Google", "price": 0.05, "t2v": True, "i2v": True},
    "veo-3.1-fast-generate-preview": {"label": "Veo 3.1 Fast · 720p со звуком", "price": 0.10, "t2v": True, "i2v": True},
    "veo-3.1-generate-preview": {"label": "Veo 3.1 · лучшее качество Google, со звуком", "price": 0.40, "t2v": True, "i2v": True},
}
VEO_DUR = [4, 6, 8]

def veo_key() -> str:
    k = P.secret("veo", "key") or P.secret("gemini", "key")
    if not k: raise UserError("Не подключён Google Veo. Настройки → Провайдеры → Google Veo: вставьте ключ из aistudio.google.com/apikey (на проекте должна быть включена оплата).")
    return k

def _dur(seconds, allowed):
    for d in allowed:
        if d >= seconds - 0.01: return d
    return allowed[-1]

def veo_cost(model: str, seconds: float) -> dict:
    m = VEO.get(model) or VEO["veo-3.1-lite-generate-preview"]; d = _dur(seconds, VEO_DUR)
    return {"usd": round(m["price"] * d, 4), "units": d, "unit": "second", "price": m["price"], "source": f"тариф Google, проверено {CHECKED}", "label": m["label"]}

def _verr(r) -> UserError:
    try: msg = (r.json().get("error") or {}).get("message", "")
    except Exception: msg = r.text[:200]
    low = msg.lower()
    if r.status_code in (401, 403) and ("billing" in low or "paid" in low or "free tier" in low):
        return PaidDown("Google Veo доступен только с включённой оплатой в Google AI Studio (aistudio.google.com → Billing). Ничего не списано.")
    if r.status_code in (400, 401, 403) and "api key" in low: return UserError("Google не принял ключ Veo. Проверьте его в Настройках → Провайдеры.")
    if r.status_code == 429: return PaidDown("Google Veo: превышен лимит запросов или квота. Ничего не списано — попробуйте позже.")
    if r.status_code >= 500: return PaidDown(f"Google Veo временно недоступен (ошибка {r.status_code}). Ничего не списано.")
    return UserError(f"Google Veo: {msg[:250] or r.status_code}")

def veo_video(model: str, prompt: str, image_path, seconds: float, ratio: str = "9:16", negative: str = "", job=None) -> dict:
    k = veo_key(); h = {"x-goog-api-key": k, "Content-Type": "application/json"}; d = _dur(seconds, VEO_DUR)
    inst = {"prompt": prompt[:1800]}
    if image_path:
        uri = fal.data_uri(Path(image_path)); inst["image"] = {"bytesBase64Encoded": uri.split(",", 1)[1], "mimeType": "image/jpeg"}
    params = {"aspectRatio": "16:9" if ratio == "16:9" else "9:16", "durationSeconds": d}
    if negative: params["negativePrompt"] = negative[:500]
    with make_client() as c:
        try: r = c.post(f"{VEO_BASE}/models/{model}:predictLongRunning", json={"instances": [inst], "parameters": params}, headers=h)
        except httpx.HTTPError as e: raise PaidDown(f"Нет связи с Google ({type(e).__name__}). Ничего не списано.")
        if r.status_code != 200: raise _verr(r)
        op = r.json().get("name")
        if job: job.progress(0.15, "Google Veo принял задачу…")
        t0 = time.time()
        while True:
            if job: job.check()
            time.sleep(6)
            s = c.get(f"{VEO_BASE}/{op}", headers=h)
            if s.status_code != 200: raise _verr(s)
            o = s.json()
            if o.get("done"):
                if o.get("error"): raise UserError("Google Veo не смог сделать видео: " + str(o["error"].get("message", ""))[:250])
                resp = o.get("response") or {}
                samples = (resp.get("generateVideoResponse") or {}).get("generatedSamples") or resp.get("generatedVideos") or []
                if not samples:
                    why = (resp.get("generateVideoResponse") or {}).get("raiMediaFilteredReasons") or []
                    raise UserError("Google Veo не вернул видео" + (": " + "; ".join(why)[:200] if why else " (возможно, запрос отклонён фильтром безопасности)."))
                uri = (samples[0].get("video") or {}).get("uri"); break
            el = time.time() - t0
            if job: job.progress(min(0.9, 0.15 + 0.75 * (1 - 1 / (1 + el / 60))), "Google Veo генерирует…")
            if el > 900: raise UserError("Google Veo не закончил за 15 минут.")
        p = fal.tmp_path(".mp4")
        with make_client(httpx.Timeout(300, connect=20)) as c2:
            v = c2.get(uri, headers={"x-goog-api-key": k}); v.raise_for_status(); p.write_bytes(v.content)
    return {"path": p, "seconds": d, "request_id": op or ""}

def veo_test() -> dict:
    k = veo_key()
    with make_client() as c: r = c.get(f"{VEO_BASE}/models", params={"pageSize": 200}, headers={"x-goog-api-key": k})
    if r.status_code != 200: raise _verr(r)
    have = [m["name"].split("/")[-1] for m in r.json().get("models", []) if "veo" in m.get("name", "")]
    return {"ok": True, "detail": "Ключ работает. Доступно моделей Veo: " + (", ".join(have[:6]) or "не видно — включите оплату в AI Studio") + ". Генерации платные: цена показывается перед запуском."}

# ---------------- Runway ----------------
RW_BASE = "https://api.dev.runwayml.com/v1"
RW_VER = "2024-11-06"
RUNWAY = {
    "gen4_turbo": {"label": "Runway Gen-4 Turbo · быстро", "credits": 5, "i2v": True, "t2v": False},
    "kling3.0_standard": {"label": "Kling 3.0 Standard через Runway · без звука", "credits": 9, "i2v": True, "t2v": True},
    "gen4.5": {"label": "Runway Gen-4.5 · лучшее у Runway", "credits": 12, "i2v": True, "t2v": True},
}
RW_DUR = [5, 10]

def rw_key() -> str:
    k = P.secret("runway", "key")
    if not k: raise UserError("Не подключён Runway. Настройки → Провайдеры → Runway: вставьте ключ с dev.runwayml.com.")
    return k

def rw_cost(model: str, seconds: float) -> dict:
    m = RUNWAY.get(model) or RUNWAY["gen4_turbo"]; d = _dur(seconds, RW_DUR); price = m["credits"] / 100
    return {"usd": round(price * d, 4), "units": d, "unit": "second", "price": price, "source": f"тариф Runway API, проверено {CHECKED}", "label": m["label"]}

def _rerr(r) -> UserError:
    try: msg = str(r.json().get("error") or r.json())
    except Exception: msg = r.text[:200]
    if r.status_code == 401: return UserError("Runway не принял ключ. Проверьте его в Настройках → Провайдеры.")
    if r.status_code in (402, 403) or "credit" in msg.lower(): return PaidDown("На балансе Runway не хватает кредитов — ничего не списано. Пополните на dev.runwayml.com.")
    if r.status_code == 429: return PaidDown("Runway: слишком много запросов. Ничего не списано — повторите позже.")
    if r.status_code >= 500: return PaidDown(f"Runway временно недоступен (ошибка {r.status_code}). Ничего не списано.")
    return UserError(f"Runway: {msg[:250]}")

def rw_video(model: str, prompt: str, image_path, seconds: float, ratio: str = "9:16", job=None) -> dict:
    k = rw_key(); h = {"Authorization": f"Bearer {k}", "X-Runway-Version": RW_VER, "Content-Type": "application/json"}
    m = RUNWAY.get(model) or RUNWAY["gen4_turbo"]; d = _dur(seconds, RW_DUR)
    body = {"model": model, "promptText": prompt[:950], "ratio": "1280:720" if ratio == "16:9" else "720:1280", "duration": d}
    if image_path: body["promptImage"] = fal.data_uri(Path(image_path), max_side=1280); ep = "image_to_video"
    elif m["t2v"]: ep = "text_to_video"
    else: raise UserError("Эта модель Runway оживляет картинку — нужна стартовая картинка.")
    with make_client() as c:
        try: r = c.post(f"{RW_BASE}/{ep}", json=body, headers=h)
        except httpx.HTTPError as e: raise PaidDown(f"Нет связи с Runway ({type(e).__name__}). Ничего не списано.")
        if r.status_code not in (200, 201): raise _rerr(r)
        tid = r.json().get("id")
        if job: job.progress(0.15, "Runway принял задачу…")
        t0 = time.time()
        while True:
            if job:
                try: job.check()
                except Exception:
                    try: c.delete(f"{RW_BASE}/tasks/{tid}", headers=h)
                    except Exception: pass
                    raise
            time.sleep(5)
            s = c.get(f"{RW_BASE}/tasks/{tid}", headers=h)
            if s.status_code != 200: raise _rerr(s)
            t = s.json(); st = t.get("status")
            if st == "SUCCEEDED": url = (t.get("output") or [None])[0]; break
            if st in ("FAILED", "CANCELLED"): raise UserError("Runway не смог сделать видео: " + str(t.get("failure") or st)[:250])
            el = time.time() - t0
            if job: job.progress(min(0.9, 0.15 + 0.75 * float(t.get("progress") or (1 - 1 / (1 + el / 60)))), "Runway генерирует…")
            if el > 900: raise UserError("Runway не закончил за 15 минут.")
    if not url: raise UserError("Runway не вернул видео.")
    return {"path": fal.download(url, ".mp4"), "seconds": d, "request_id": tid or ""}

def rw_test() -> dict:
    k = rw_key()
    with make_client() as c: r = c.get(f"{RW_BASE}/organization", headers={"Authorization": f"Bearer {k}", "X-Runway-Version": RW_VER})
    if r.status_code != 200: raise _rerr(r)
    bal = r.json().get("creditBalance")
    return {"ok": True, "detail": f"Ключ Runway работает. Баланс: {bal} кредитов (1 кредит = $0.01)." if bal is not None else "Ключ Runway работает."}
