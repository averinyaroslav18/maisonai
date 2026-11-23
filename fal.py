"""fal.ai — платные модели видео и картинок. Каждый вызов проходит через billing: без подтверждённой цены не запускается.

Очередь fal: POST https://queue.fal.run/<endpoint> → request_id + status_url/response_url/cancel_url,
статус IN_QUEUE / IN_PROGRESS / COMPLETED (при ошибке — error). Файлы передаём как data URI.
Цены берём живыми из https://api.fal.ai/v1/models/pricing, при недоступности — из каталога ниже
(проверено по страницам моделей fal.ai 19.11.2026).
"""
import base64, io, json, threading, time
from pathlib import Path
import httpx
import providers as P
from core import UserError, tmp_path, DATA

class FalDown(UserError):
    """fal.ai недоступен (сеть, 5xx, закончился баланс) — можно перейти на бесплатный вариант."""

QUEUE = "https://queue.fal.run/"
PRICING = "https://api.fal.ai/v1/models/pricing"
MODELS_API = "https://api.fal.ai/v1/models"
CHECKED = "21.11.2026"

# kind: video (картинка → видео), image (текст → картинка), image_edit (правка по картинкам)
MODELS = {
    "fal-ai/minimax/hailuo-02-fast/image-to-video": {
        "kind": "video", "label": "Hailuo 02 Fast · 512p · самый дешёвый", "unit": "second", "price": 0.017, "durations": [6, 10]},
    "fal-ai/kling-video/v2.5-turbo/pro/image-to-video": {
        "kind": "video", "label": "Kling 2.5 Turbo Pro · 1080p · лучшее качество", "unit": "second", "price": 0.07, "durations": [5, 10]},
    "minimax/h3-max-turbo/image-to-video": {"kind": "video", "label": "MiniMax H3 Max Turbo · очень дёшево", "unit": "second", "price": 0.015},
    "minimax/h3-max/image-to-video": {"kind": "video", "label": "MiniMax H3 Max · дёшево и хорошо", "unit": "second", "price": 0.03},
    "fal-ai/kling-video/v3/pro/image-to-video": {"kind": "video", "label": "Kling 3.0 Pro · топ-качество", "unit": "second", "price": 0.14},
    "bytedance/seedance-2.0/image-to-video": {"kind": "video", "label": "Seedance 2.0 · кино-качество (цена по токенам)", "unit": "1000 tokens", "price": 0.014},
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
    if m in MODELS and MODELS[m]["kind"] == kind: return m
    if kind == "video" and m and "/" in m: return m   # любая видеомодель из живого каталога fal
    return DEFAULT[kind]

def is_t2v(endpoint: str) -> bool:
    return "text-to-video" in (info(endpoint).get("category") or endpoint)

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

# ---------- весь каталог видеомоделей fal (живой список + живые цены) ----------
_cat = {"t": 0.0, "v": [], "lock": threading.Lock()}
_schemas = {}
CAT_FILE = DATA / "fal_video_catalog.json"
VIDEO_CATS = ("image-to-video", "text-to-video")

def _list_models(c, category, h):
    out, cursor = [], None
    for _ in range(30):   # постранично, максимум ~3000 моделей
        params = {"category": category, "limit": 100, "status": "active"}
        if cursor: params["cursor"] = cursor
        r = c.get(MODELS_API, params=params, headers=h)
        if r.status_code != 200: break
        d = r.json()
        for m in d.get("models", []):
            md = m.get("metadata") or {}
            if md.get("status") in ("deprecated", "disabled") or md.get("deprecated"): continue
            out.append({"id": m["endpoint_id"], "label": md.get("display_name") or m["endpoint_id"], "category": md.get("category") or category,
                        "desc": (md.get("description") or "")[:240]})
        cursor = d.get("next_cursor")
        if not d.get("has_more") or not cursor: break
    return out

SEC_UNITS = ("second", "seconds", "sec", "s", "video second", "video seconds", "output second", "output seconds")
PER_UNITS = ("video", "videos", "request", "requests", "generation", "generations", "image", "images")
TOK_UNITS = ("token", "tokens", "1000 tokens", "1k tokens", "million tokens", "1m tokens")

def _tok_div(u): return 1e6 if "million" in u or "1m" in u else 1000 if ("1000" in u or "1k" in u) else 1

def per5(m: dict):
    """Цена 5-секундного ролика (для сравнения в списке). None — неизвестна (например, оплата за время видеокарты)."""
    p, u = m.get("price"), str(m.get("unit") or "").strip().lower()
    if p is None: return None
    if u in SEC_UNITS: return round(p * 5, 4)
    if u in TOK_UNITS: return round(p * (1280 * 720 * 24 * 5 / 1024) / _tok_div(u), 4)
    if u in PER_UNITS: return round(p, 4)
    return None

def catalog(force=False) -> list:
    """Все видеомодели fal: [{id, label, category, desc, price, unit}]. Кэш 6 часов (и на диске)."""
    with _cat["lock"]:
        if not force and _cat["v"] and time.time() - _cat["t"] < 6 * 3600: return _cat["v"]
        if not force and not _cat["v"] and CAT_FILE.exists():
            try:
                d = json.loads(CAT_FILE.read_text("utf-8"))
                if time.time() - d["t"] < 6 * 3600: _cat.update(t=d["t"], v=d["v"]); return d["v"]
            except Exception: pass
        k = P.secret("fal", "key"); h = {"Authorization": f"Key {k}"} if k else {}
        items = {}
        try:
            with make_client() as c:
                for cat in VIDEO_CATS:
                    for m in _list_models(c, cat, h): items.setdefault(m["id"], m)
                if k and items:
                    ids = list(items)
                    for n in range(0, len(ids), 40):
                        r = c.get(PRICING, params={"endpoint_id": ",".join(ids[n:n + 40])}, headers=h)
                        if r.status_code == 200:
                            for pr in r.json().get("prices", []):
                                if pr.get("endpoint_id") in items: items[pr["endpoint_id"]].update(price=float(pr["unit_price"]), unit=str(pr.get("unit", "")).lower())
        except Exception: pass
        for mid, m in MODELS.items():   # проверенные вручную — всегда в списке
            if m["kind"] == "video":
                cur = items.setdefault(mid, {"id": mid, "label": m["label"], "category": "image-to-video", "desc": ""})
                cur.setdefault("price", m["price"]); cur.setdefault("unit", m["unit"])
                if cur["label"] == mid: cur["label"] = m["label"]
        v = sorted(items.values(), key=lambda m: (per5(m) is None, per5(m) or 0))
        if v and len(v) > len([1 for m in MODELS.values() if m["kind"] == "video"]):
            _cat.update(t=time.time(), v=v)
            try: CAT_FILE.write_text(json.dumps({"t": _cat["t"], "v": v}, ensure_ascii=False), "utf-8")
            except Exception: pass
        return v or _cat["v"]

def info(endpoint: str) -> dict:
    if endpoint in MODELS: return {"id": endpoint, "category": "image-to-video", **MODELS[endpoint]}
    for m in _cat["v"] or catalog():
        if m["id"] == endpoint: return {"kind": "video", **m}
    return {}

def schema(endpoint: str) -> dict:
    """Входные поля модели из её OpenAPI (чтобы правильно передать длину, формат кадра и картинку)."""
    if endpoint in _schemas: return _schemas[endpoint]
    props = {}
    try:
        k = P.secret("fal", "key"); h = {"Authorization": f"Key {k}"} if k else {}
        with make_client() as c:
            r = c.get(MODELS_API, params={"endpoint_id": endpoint, "expand": "openapi-3.0"}, headers=h)
        spec = (r.json().get("models") or [{}])[0].get("openapi") or {}
        comps = (spec.get("components") or {}).get("schemas") or {}
        for path, ops in (spec.get("paths") or {}).items():
            post = (ops or {}).get("post") or {}
            ref = (((post.get("requestBody") or {}).get("content") or {}).get("application/json") or {}).get("schema", {}).get("$ref", "")
            if ref:
                props = comps.get(ref.split("/")[-1], {}).get("properties") or {}
                if props: break
    except Exception: props = {}
    if props: _schemas[endpoint] = props
    return props

def _enum(prop: dict) -> list:
    if not prop: return []
    if prop.get("enum"): return prop["enum"]
    for alt in prop.get("anyOf") or prop.get("allOf") or []:
        if alt.get("enum"): return alt["enum"]
    return []

def billed_duration(endpoint: str, seconds: float) -> int:
    """Модели принимают только фиксированные длины — берём ближайшую не короче нужной."""
    ds = MODELS.get(endpoint, {}).get("durations")
    if not ds:
        en = _enum(schema(endpoint).get("duration", {}))
        try: ds = sorted({int(float(str(x).rstrip("s"))) for x in en})
        except Exception: ds = []
    ds = ds or [int(max(1, round(seconds)))]
    for d in ds:
        if d >= seconds - 0.01: return d
    return ds[-1]

def cost(endpoint: str, seconds: float = 0, width: int = 1024, height: int = 1024, n: int = 1) -> dict:
    """Цена одного вызова. Возвращает {usd, units, unit, source}. Неизвестная единица цены — UserError (без угадывания)."""
    m = MODELS.get(endpoint) or info(endpoint)
    if not m: raise UserError("Модель fal.ai не найдена в каталоге. Выберите другую в «Все модели видео».")
    live = live_prices().get(endpoint) if endpoint in MODELS else None
    if live: price, unit, src = live[0], live[1], "живая цена fal.ai"
    elif m.get("price") is not None: price, unit, src = m["price"], str(m.get("unit") or ""), (f"каталог MaisonAI, проверено {CHECKED}" if endpoint in MODELS else "живая цена fal.ai")
    else: raise UserError(f"fal.ai не сообщает цену модели «{m.get('label', endpoint)}» — MaisonAI не запускает модели с неизвестной ценой. Выберите другую.")
    kind = m.get("kind", "video"); unit = unit.strip().lower()
    if unit in SEC_UNITS: units = billed_duration(endpoint, seconds) if kind == "video" else seconds
    elif unit in TOK_UNITS:   # Seedance: токены ≈ ширина×высота×кадры/1024 (720p, 24 к/с)
        d = billed_duration(endpoint, seconds); units = round(1280 * 720 * 24 * d / 1024 / _tok_div(unit), 2)
    elif unit in ("megapixel", "megapixels", "mp"): units = max(1.0, round(width * height / 1e6, 3)) * n
    elif unit in PER_UNITS: units = n
    else: raise UserError(f"Непонятная единица цены «{unit}» у модели {endpoint} — запуск отменён, чтобы не списать неожиданную сумму.")
    return {"usd": round(price * units, 4), "units": units, "unit": unit, "price": price, "source": src, "label": m.get("label", endpoint)}

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

IMG_FIELDS = ("image_url", "start_image_url", "first_frame_url", "first_frame_image", "image", "input_image_url")

def video(endpoint: str, prompt: str, image_path: Path, seconds: float, negative: str = "", job=None, ratio: str = "9:16") -> dict:
    d = billed_duration(endpoint, seconds); props = schema(endpoint)
    payload = {"prompt": prompt[:2000]}
    if not is_t2v(endpoint):
        if not image_path: raise UserError("Эта модель оживляет картинку — нужна стартовая картинка.")
        payload[next((f for f in IMG_FIELDS if f in props), "image_url")] = data_uri(Path(image_path))
    du = props.get("duration")
    if du is not None:
        en = _enum(du); typ = du.get("type") or next((a.get("type") for a in du.get("anyOf", []) if a.get("type")), "")
        if en and isinstance(en[0], str): payload["duration"] = next((x for x in en if str(x).rstrip("s") == str(d)), str(d))
        elif typ in ("integer", "number") or (en and not isinstance(en[0], str)): payload["duration"] = d
        else: payload["duration"] = str(d)
    elif endpoint in MODELS: payload["duration"] = str(d)
    ar = _enum(props.get("aspect_ratio", {}))
    want = {"9:16": "9:16", "4:5": "9:16", "1:1": "1:1", "16:9": "16:9"}.get(ratio, "9:16")
    if want in ar: payload["aspect_ratio"] = want
    res = _enum(props.get("resolution", {}))
    if res: payload["resolution"] = "720p" if "720p" in res else sorted(res, key=str)[0]
    if "generate_audio" in props: payload["generate_audio"] = False   # цена посчитана без звука
    if negative and ("negative_prompt" in props or "kling" in endpoint): payload["negative_prompt"] = negative[:500]
    if "prompt_optimizer" in props or "hailuo" in endpoint: payload["prompt_optimizer"] = True
    out = run(endpoint, payload, job)
    v = out.get("video") or (out.get("videos") or [None])[0]
    url = v.get("url") if isinstance(v, dict) else v
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
