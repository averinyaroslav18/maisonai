"""fal.ai — платные модели видео и картинок. Каждый вызов проходит через billing: без подтверждённой цены не запускается.

Очередь fal: POST https://queue.fal.run/<endpoint> → request_id + status_url/response_url/cancel_url,
статус IN_QUEUE / IN_PROGRESS / COMPLETED (при ошибке — error). Файлы передаём как data URI.
Цены берём живыми из https://api.fal.ai/v1/models/pricing, при недоступности — из каталога ниже
(проверено по страницам моделей fal.ai 19.11.2026).
"""
import base64, io, time
from pathlib import Path
import httpx
import providers as P
from core import UserError, tmp_path

class FalDown(UserError):
    """fal.ai недоступен (сеть, 5xx, закончился баланс) — можно перейти на бесплатный вариант."""

QUEUE = "https://queue.fal.run/"
PRICING = "https://api.fal.ai/v1/models/pricing"
CHECKED = "19.11.2026"

# kind: video (картинка → видео), image (текст → картинка), image_edit (правка по картинкам)
MODELS = {
    "fal-ai/minimax/hailuo-02-fast/image-to-video": {
        "kind": "video", "label": "Hailuo 02 Fast · 512p · самый дешёвый", "unit": "second", "price": 0.017, "durations": [6, 10]},
    "fal-ai/kling-video/v2.5-turbo/pro/image-to-video": {
        "kind": "video", "label": "Kling 2.5 Turbo Pro · 1080p · лучшее качество", "unit": "second", "price": 0.07, "durations": [5, 10]},
    "fal-ai/flux/schnell": {"kind": "image", "label": "FLUX.1 schnell · быстро и дёшево", "unit": "megapixel", "price": 0.003},
    "fal-ai/nano-banana/edit": {"kind": "image_edit", "label": "Nano Banana · правка картинок", "unit": "image", "price": 0.0398},
}
DEFAULT = {"video": "fal-ai/minimax/hailuo-02-fast/image-to-video", "image": "fal-ai/flux/schnell", "image_edit": "fal-ai/nano-banana/edit"}

make_client = lambda timeout=httpx.Timeout(60, connect=15): httpx.Client(timeout=timeout, follow_redirects=True)   # подмена в тестах
_price_cache = {"t": 0.0, "v": {}}

def key() -> str:
    k = P.secret("fal", "key")
    if not k: raise UserError("Не подключён fal.ai. Настройки → Провайдеры → fal.ai: вставьте ключ (fal.ai/dashboard/keys).")
    return k

def model(kind: str) -> str:
    m = P.model_for("fal", kind, DEFAULT[kind])
    return m if m in MODELS and MODELS[m]["kind"] == kind else DEFAULT[kind]

def live_prices() -> dict:
    """{endpoint: (unit_price, unit)} — живые цены fal, кэш 6 часов. Без ключа или сети — пусто."""
    if time.time() - _price_cache["t"] < 6 * 3600 and _price_cache["v"]: return _price_cache["v"]
    k = P.secret("fal", "key")
    if not k: return {}
    try:
        with make_client() as c:
            r = c.get(PRICING, params={"endpoint_id": ",".join(MODELS)}, headers={"Authorization": f"Key {k}"})
            if r.status_code != 200: return {}
            out = {p["endpoint_id"]: (float(p["unit_price"]), str(p.get("unit", "")).lower()) for p in r.json().get("prices", []) if p.get("endpoint_id") in MODELS}
        _price_cache.update(t=time.time(), v=out); return out
    except Exception:
        return {}

def billed_duration(endpoint: str, seconds: float) -> int:
    """Модели принимают только фиксированные длины — берём ближайшую не короче нужной."""
    ds = MODELS[endpoint].get("durations") or [int(round(seconds))]
    for d in ds:
        if d >= seconds - 0.01: return d
    return ds[-1]

def cost(endpoint: str, seconds: float = 0, width: int = 1024, height: int = 1024, n: int = 1) -> dict:
    """Цена одного вызова. Возвращает {usd, units, unit, source}."""
    m = MODELS[endpoint]; live = live_prices().get(endpoint)
    price, unit, src = (live[0], live[1], "живая цена fal.ai") if live else (m["price"], m["unit"], f"каталог MaisonAI, проверено {CHECKED}")
    if "second" in unit: units = billed_duration(endpoint, seconds) if m["kind"] == "video" else seconds
    elif "megapixel" in unit or unit in ("mp", "megapixels"): units = max(1.0, round(width * height / 1e6, 3)) * n
    elif "video" in unit: units = n
    elif "image" in unit: units = n
    else:   # неизвестная единица — честно берём каталог
        price, unit, src = m["price"], m["unit"], f"каталог MaisonAI, проверено {CHECKED}"
        units = billed_duration(endpoint, seconds) if unit == "second" else (max(1.0, width * height / 1e6) if unit == "megapixel" else n)
    return {"usd": round(price * units, 4), "units": units, "unit": unit, "price": price, "source": src, "label": m["label"]}

def data_uri(path: Path, max_side=1536) -> str:
    from PIL import Image
    im = Image.open(path); im = im.convert("RGB")
    if max(im.size) > max_side: im.thumbnail((max_side, max_side))
    b = io.BytesIO(); im.save(b, "JPEG", quality=90)
    return "data:image/jpeg;base64," + base64.b64encode(b.getvalue()).decode()

def _err(r: httpx.Response) -> UserError:
    try: d = r.json()
    except Exception: d = {}
    detail = str(d.get("detail") or d.get("error") or r.text[:200])
    low = detail.lower()
    if r.status_code == 401: return UserError("fal.ai не принял ключ. Проверьте его в Настройках → Провайдеры → fal.ai.")
    if r.status_code in (402, 403) and ("balance" in low or "locked" in low or "exhausted" in low or r.status_code == 402):
        return FalDown("Баланс fal.ai закончился — запрос не выполнен и не оплачен. Пополните баланс на fal.ai/dashboard/billing или выберите бесплатный вариант.")
    if r.status_code == 403: return UserError("fal.ai отказал в доступе к этой модели: " + detail[:200])
    if r.status_code == 422: return UserError("fal.ai не принял параметры: " + detail[:250])
    if r.status_code == 429: return UserError("fal.ai: слишком много одновременных запросов (новому аккаунту доступно 2). Подождите и повторите.")
    if r.status_code >= 500: return FalDown(f"fal.ai временно недоступен (ошибка {r.status_code}). Ничего не списано за неудачный запуск — повторите позже.")
    return UserError(f"fal.ai вернул ошибку {r.status_code}: {detail[:200]}")

def run(endpoint: str, payload: dict, job=None, p0=0.1, p1=0.95, timeout=900) -> dict:
    """Запуск в очереди fal с честным статусом и отменой. Без автоповторов: повторный запуск = повторная оплата."""
    k = key(); h = {"Authorization": f"Key {k}", "Content-Type": "application/json"}
    with make_client() as c:
        try: r = c.post(QUEUE + endpoint, json=payload, headers=h)
        except httpx.HTTPError as e: raise FalDown(f"Нет связи с fal.ai ({type(e).__name__}). Ничего не списано.")
        if r.status_code not in (200, 201, 202): raise _err(r)
        sub = r.json(); rid = sub.get("request_id")
        status_url, resp_url, cancel_url = sub.get("status_url"), sub.get("response_url"), sub.get("cancel_url")
        if job: job.progress(p0, "fal.ai принял задачу…")
        t0 = time.time()
        while True:
            try:
                if job: job.check()
            except Exception:
                try: c.put(cancel_url, headers=h)
                except Exception: pass
                raise
            s = c.get(status_url, headers=h)
            if s.status_code >= 400: raise _err(s)
            st = s.json(); state = st.get("status")
            if state == "COMPLETED":
                if st.get("error"): raise UserError("fal.ai не смог выполнить задачу: " + str(st.get("error"))[:250])
                break
            el = time.time() - t0
            if job:
                msg = f"fal.ai: в очереди, позиция {st.get('queue_position')}" if state == "IN_QUEUE" else "fal.ai генерирует…"
                job.progress(min(p1 - 0.02, p0 + (p1 - p0) * (1 - 1 / (1 + el / 90))), msg)
            if el > timeout:
                try: c.put(cancel_url, headers=h)
                except Exception: pass
                raise UserError("fal.ai не закончил за отведённое время — задача отменена.")
            time.sleep(2.5)
        res = c.get(resp_url, headers=h)
        if res.status_code >= 400: raise _err(res)
        out = res.json(); out["_request_id"] = rid
        return out

def download(url: str, ext: str) -> Path:
    p = tmp_path(ext)
    if url.startswith("data:"):
        p.write_bytes(base64.b64decode(url.split(",", 1)[1])); return p
    with make_client(httpx.Timeout(300, connect=20)) as c:
        r = c.get(url); r.raise_for_status(); p.write_bytes(r.content)
    return p

def video(endpoint: str, prompt: str, image_path: Path, seconds: float, negative: str = "", job=None) -> dict:
    d = billed_duration(endpoint, seconds)
    payload = {"prompt": prompt[:2000], "image_url": data_uri(image_path), "duration": str(d)}
    if "kling" in endpoint and negative: payload["negative_prompt"] = negative[:500]
    if "hailuo" in endpoint: payload["prompt_optimizer"] = True
    out = run(endpoint, payload, job)
    url = (out.get("video") or {}).get("url")
    if not url: raise UserError("fal.ai не вернул видео.")
    return {"path": download(url, ".mp4"), "seconds": d, "request_id": out["_request_id"]}

def image(endpoint: str, prompt: str, width: int, height: int, seed=None, refs=None, ratio="1:1", job=None) -> dict:
    if MODELS[endpoint]["kind"] == "image_edit":
        payload = {"prompt": prompt[:2000], "image_urls": [data_uri(Path(r)) for r in (refs or [])[:4]], "num_images": 1, "output_format": "jpeg",
                   "aspect_ratio": ratio if ratio in ("21:9", "16:9", "3:2", "4:3", "5:4", "1:1", "4:5", "3:4", "2:3", "9:16") else "auto"}
    else:
        payload = {"prompt": prompt[:2000], "image_size": {"width": int(width), "height": int(height)}, "num_images": 1, "output_format": "jpeg", "enable_safety_checker": True}
    if seed: payload["seed"] = int(seed) % 2147483647
    out = run(endpoint, payload, job, p0=0.2, p1=0.9, timeout=300)
    imgs = out.get("images") or []
    if not imgs or not imgs[0].get("url"): raise UserError("fal.ai не вернул картинку.")
    return {"path": download(imgs[0]["url"], ".jpg"), "request_id": out["_request_id"], "width": imgs[0].get("width") or width, "height": imgs[0].get("height") or height}

def test() -> dict:
    """Проверка ключа без оплаты: запрос цен требует действующий ключ."""
    k = key()
    with make_client() as c:
        r = c.get(PRICING, params={"endpoint_id": DEFAULT["image"]}, headers={"Authorization": f"Key {k}"})
    if r.status_code == 401: raise UserError("fal.ai не принял ключ.")
    if r.status_code >= 400: raise _err(r)
    return {"ok": True, "detail": "Ключ fal.ai работает. Генерации платные: цена показывается перед каждым запуском."}
