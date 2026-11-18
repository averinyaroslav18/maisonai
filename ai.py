"""Единый слой ИИ: текст, анализ картинок/видео, распознавание речи. Все провайдеры за одним интерфейсом."""
import base64, json, re, threading, time
from pathlib import Path
import httpx
import providers as P
from core import UserError

TIMEOUT = httpx.Timeout(180, connect=15)
_slot_lock = threading.Lock()
_last_call = {}

def client(timeout=TIMEOUT) -> httpx.Client:
    return httpx.Client(timeout=timeout, follow_redirects=True, headers={"User-Agent": "MaisonAI/1.0"})

# создание клиента вынесено в функцию, чтобы тесты могли подменить сеть
make_client = client

def wait_slot(pid: str, gap: float, job=None):
    """Бесплатные сервисы без ключа требуют паузы между запросами — ждём честно, показывая это пользователю."""
    with _slot_lock:
        left = gap - (time.time() - _last_call.get(pid, 0))
        _last_call[pid] = time.time() + max(0, left)
    while left > 0:
        if job: job.progress(getattr(job, "_p", 0.05), f"Бесплатный режим: жду очереди ещё {int(left) + 1} сек…")
        s = min(1.0, left); time.sleep(s); left -= s

def post_retry(c, url, job=None, tries=3, **kw):
    """Запрос с повтором при перегрузке или лимите провайдера (429, 5xx) — честно сообщаем, что ждём."""
    for i in range(tries):
        r = c.post(url, **kw)
        if r.status_code not in (429, 500, 502, 503, 504) or i == tries - 1: return r
        try: wait = min(40, float(r.headers.get("retry-after", 0)) or 0)
        except ValueError: wait = 0
        wait = wait or (8, 20, 35)[i]
        for left in range(int(wait), 0, -1):
            if job: job.progress(getattr(job, "_p", 0.3), f"Провайдер перегружен или лимит ({r.status_code}) — повтор через {left} с…")
            time.sleep(1)
    return r

def need(cap: str) -> str:
    pid = P.chosen(cap)
    if not pid:
        names = {"text": "текста", "vision": "анализа картинок", "video_understanding": "анализа видео", "image": "картинок",
                 "image_edit": "редактирования картинок", "tts": "озвучки", "stt": "распознавания речи", "video": "видео"}
        raise UserError(f"Не настроен провайдер для {names.get(cap, cap)}. Откройте Настройки → Провайдеры ИИ и подключите бесплатный вариант.")
    return pid

# ---------------- модели ----------------
GEMINI_SKIP = ("embedding", "image", "tts", "live", "audio", "aqa", "imagen", "veo", "learnlm", "robotics", "computer-use")

def _ver(name):
    nums = re.findall(r"\d+(?:\.\d+)?", name)
    try: return float(nums[0]) if nums else 0.0
    except ValueError: return 0.0

def list_models(pid: str) -> list:
    """Живой список моделей у провайдера (ничего не придумываем)."""
    with make_client(httpx.Timeout(25, connect=10)) as c:
        if pid == "gemini":
            r = c.get("https://generativelanguage.googleapis.com/v1beta/models", params={"key": P.secret("gemini"), "pageSize": 200}); r.raise_for_status()
            out = []
            for m in r.json().get("models", []):
                if "generateContent" in m.get("supportedGenerationMethods", []):
                    out.append(m["name"].split("/", 1)[-1])
            return out
        if pid == "ollama":
            r = c.get(P.base_url("ollama").replace("/v1", "") + "/api/tags"); r.raise_for_status()
            return [m["name"] for m in r.json().get("models", [])]
        if pid in ("pollinations", "pollinations_free"):
            r = c.get("https://gen.pollinations.ai/text/models"); r.raise_for_status()
            return [m.get("name") or m.get("id") for m in r.json() if isinstance(m, dict)]
        if pid == "cloudflare":
            if not P.secret("cloudflare", "account"): raise UserError("Не указан Account ID Cloudflare. Вставьте его в поле «Account ID» и нажмите «Сохранить».")
            r = c.get(f"https://api.cloudflare.com/client/v4/accounts/{P.secret('cloudflare', 'account')}/ai/models/search",
                      params={"task": "Text Generation", "per_page": 100}, headers={"Authorization": f"Bearer {P.secret('cloudflare')}"}); r.raise_for_status()
            return [m["name"] for m in r.json().get("result", [])]
        base = P.base_url(pid)
        r = c.get(base + "/models", headers=_auth(pid)); r.raise_for_status()
        ids = [m["id"] for m in r.json().get("data", [])]
        if pid == "openrouter": ids = [i for i in ids if i.endswith(":free")]
        if pid == "groq": ids = [i for i in ids if "whisper" not in i and "guard" not in i and "orpheus" not in i and "tts" not in i]
        return ids

def default_model(pid: str, cap: str = "text") -> str:
    saved = P.model_for(pid, cap)
    if saved: return saved
    fixed = {("cloudflare", "text"): "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
             ("cloudflare", "vision"): "@cf/mistralai/mistral-small-3.1-24b-instruct",
             ("pollinations_free", "text"): "openai", ("pollinations", "text"): "openai"}
    if (pid, cap) in fixed: return fixed[(pid, cap)]
    if pid == "custom": raise UserError("Укажите модель для своего сервера в Настройках.")
    try: ms = list_models(pid)
    except httpx.HTTPStatusError as e:
        raise UserError("Провайдер отклонил запрос списка моделей — проверьте ключ в Настройках." if e.response.status_code in (400, 401, 403) else f"Провайдер вернул ошибку {e.response.status_code} при получении списка моделей.")
    if not ms: raise UserError("У провайдера не найдено ни одной доступной модели. Выберите модель вручную в Настройках.")
    if pid == "gemini":
        good = [m for m in ms if "flash" in m and not any(s in m for s in GEMINI_SKIP) and "preview" not in m and "exp" not in m] \
            or [m for m in ms if "flash" in m and not any(s in m for s in GEMINI_SKIP)] or ms
        good.sort(key=lambda m: (_ver(m), "lite" not in m), reverse=True); m = good[0]
    elif pid == "groq":
        pref = [x for x in ms if "gpt-oss-120b" in x] or [x for x in ms if "70b" in x or "qwen" in x] or ms; m = pref[0]
    elif pid == "openrouter":
        pref = [x for x in ms if any(k in x for k in ("deepseek", "llama-3.3", "qwen", "gemma"))] or ms; m = pref[0]
    else: m = ms[0]
    cfg = P.load_cfg(); cfg["models"][f"{pid}:{cap}"] = m; P.save_cfg(cfg)
    return m

def _auth(pid):
    k = P.secret(pid)
    return {"Authorization": f"Bearer {k}"} if k else {}

# ---------------- чат ----------------
def chat(messages, cap="text", json_mode=False, temperature=0.8, job=None, max_tokens=4096, pid=None) -> str:
    """messages в формате OpenAI. Картинки — части {'type':'image_url','image_url':{'url':'data:...'}}."""
    pid = pid or need(cap)
    if job: job.provider(P.PROVIDERS[pid]["label"])
    if pid == "pollinations_free": return _pollinations_free(messages, json_mode, job)
    url = ("https://gen.pollinations.ai/v1" if pid == "pollinations" else P.base_url(pid)) + "/chat/completions"
    model = default_model(pid, "vision" if cap == "vision" and pid == "cloudflare" else "text")
    if cap == "vision" and P.model_for(pid, "vision"): model = P.model_for(pid, "vision")
    body = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    if json_mode and pid in ("gemini", "groq", "openrouter", "ollama", "pollinations"): body["response_format"] = {"type": "json_object"}
    with make_client() as c:
        r = post_retry(c, url, job, json=body, headers=_auth(pid))
        if pid == "gemini" and r.status_code in (429, 500, 503):
            for m in gemini_fallbacks(body["model"])[1:]:
                if job: job.progress(getattr(job, "_p", 0.4), f"Модель Gemini перегружена — пробую другую ({m})…")
                body["model"] = m; r = post_retry(c, url, job, tries=2, json=body, headers=_auth(pid))
                if r.status_code not in (429, 500, 503): break
        if r.status_code == 400 and "response_format" in body:   # не все модели поддерживают JSON-режим
            body.pop("response_format"); r = post_retry(c, url, job, json=body, headers=_auth(pid))
        r.raise_for_status()
        d = r.json()
    try: return d["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        raise UserError("Провайдер вернул пустой ответ. Попробуйте ещё раз или другую модель.")

def _pollinations_free(messages, json_mode, job):
    wait_slot("pollinations_text", 31, job)
    flat = []
    for m in messages:   # бесплатный режим — только текст
        cont = m["content"] if isinstance(m["content"], str) else " ".join(p.get("text", "") for p in m["content"] if p.get("type") == "text")
        flat.append({"role": m["role"], "content": cont})
    body = {"model": "openai", "messages": flat, "private": True}
    if json_mode: body["jsonMode"] = True
    with make_client() as c:
        r = c.post("https://text.pollinations.ai/openai", json=body)
        if r.status_code in (402, 429):
            raise UserError("Бесплатный сервис Pollinations сейчас занят (лимит запросов). Подождите минуту или подключите бесплатный ключ Gemini/Groq в Настройках — они быстрее.")
        r.raise_for_status()
        try: return r.json()["choices"][0]["message"]["content"]
        except Exception: return r.text

def parse_json(text: str):
    t = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if m: t = m.group(1).strip()
    try: return json.loads(t)
    except Exception: pass
    for opener, closer in (("{", "}"), ("[", "]")):
        a, b = t.find(opener), t.rfind(closer)
        if a != -1 and b > a:
            try: return json.loads(t[a:b + 1])
            except Exception: continue
    raise ValueError("bad json")

def chat_json(system: str, user, cap="text", temperature=0.8, job=None, max_tokens=4096):
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    out = chat(msgs, cap=cap, json_mode=True, temperature=temperature, job=job, max_tokens=max_tokens)
    try: return parse_json(out)
    except ValueError:
        msgs += [{"role": "assistant", "content": out[:6000]}, {"role": "user", "content": "Ответ не является корректным JSON. Верни ТОЛЬКО исправленный JSON, без пояснений."}]
        try: return parse_json(chat(msgs, cap=cap, json_mode=True, temperature=0.2, job=job, max_tokens=max_tokens))
        except ValueError: raise UserError("ИИ вернул ответ в неправильном формате. Нажмите «Повторить» — обычно со второго раза получается.")

def image_part(path: Path, mime="image/jpeg"):
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64," + base64.b64encode(Path(path).read_bytes()).decode()}}

# ---------------- анализ видео (Gemini понимает видео целиком) ----------------
def gemini_video_json(video: Path, prompt: str, job=None, temperature=0.4):
    key = P.secret("gemini")
    model = default_model("gemini", "text")
    data = Path(video).read_bytes()
    if len(data) > 19 * 1024 * 1024: raise UserError("Видео слишком большое для анализа (больше 19 МБ после сжатия).")
    body = {"contents": [{"role": "user", "parts": [{"inline_data": {"mime_type": "video/mp4", "data": base64.b64encode(data).decode()}}, {"text": prompt}]}],
            "generationConfig": {"temperature": temperature, "responseMimeType": "application/json"}}
    if job: job.provider("Google Gemini (видео)")
    with make_client(httpx.Timeout(300, connect=20)) as c:
        for i, m in enumerate(gemini_fallbacks(model)):
            if i and job: job.progress(getattr(job, "_p", 0.5), f"Модель Gemini перегружена — пробую другую ({m})…")
            r = post_retry(c, f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent", job, tries=2, params={"key": key}, json=body)
            if r.status_code not in (429, 500, 503, 404): break
            if job: job.provider("Google Gemini (видео) · " + m)
        if r.status_code in (429, 500, 503):
            raise UserError("Google Gemini сейчас перегружен (так бывает на бесплатном ключе в часы пик). Нажмите «Повторить» через пару минут — ролик заново загружать не нужно.")
        r.raise_for_status(); d = r.json()
    try: text = "".join(p.get("text", "") for p in d["candidates"][0]["content"]["parts"])
    except Exception:
        reason = (d.get("promptFeedback") or {}).get("blockReason")
        raise UserError("Gemini отказался анализировать это видео" + (f" ({reason})." if reason else ". Попробуйте другое видео."))
    try: return parse_json(text)
    except ValueError: raise UserError("Анализ видео вернулся в неправильном формате. Повторите попытку.")

def gemini_fallbacks(first: str) -> list:
    """Основная модель + 2 запасные модели Gemini (если основная перегружена)."""
    out = [first]
    try:
        ms = [m for m in list_models("gemini") if "flash" in m and not any(s in m for s in GEMINI_SKIP) and m != first]
        ms.sort(key=lambda m: (_ver(m), "lite" not in m, "preview" not in m), reverse=True)
        out += ms[:2]
    except Exception: pass
    return out

# ---------------- распознавание речи ----------------
def transcribe(audio: Path, language: str = "", job=None) -> dict:
    """Возвращает {'text':..., 'segments':[{'start','end','text'}], 'provider':..., 'approx': bool}."""
    pid = need("stt")
    if job: job.provider(P.PROVIDERS[pid]["label"] + " (речь)")
    audio = Path(audio)
    with make_client(httpx.Timeout(300, connect=20)) as c:
        if pid == "groq":
            files = {"file": (audio.name, audio.read_bytes(), "audio/mpeg")}
            data = {"model": "whisper-large-v3-turbo", "response_format": "verbose_json"}
            if language: data["language"] = language
            r = c.post("https://api.groq.com/openai/v1/audio/transcriptions", headers=_auth("groq"), files=files, data=data); r.raise_for_status()
            d = r.json()
            segs = [{"start": float(s["start"]), "end": float(s["end"]), "text": s["text"].strip()} for s in d.get("segments", [])]
            return {"text": d.get("text", "").strip(), "segments": segs, "provider": "Groq Whisper", "approx": False}
        if pid == "cloudflare":
            acc = P.secret("cloudflare", "account")
            body = {"audio": base64.b64encode(audio.read_bytes()).decode()}
            if language: body["language"] = language
            r = c.post(f"https://api.cloudflare.com/client/v4/accounts/{acc}/ai/run/@cf/openai/whisper-large-v3-turbo", headers=_auth("cloudflare"), json=body); r.raise_for_status()
            d = r.json().get("result", {})
            segs = [{"start": float(s.get("start", 0)), "end": float(s.get("end", 0)), "text": (s.get("text") or "").strip()} for s in d.get("segments", [])]
            return {"text": (d.get("text") or "").strip(), "segments": segs, "provider": "Cloudflare Whisper", "approx": False}
        if pid == "gemini":
            model = default_model("gemini", "text")
            prompt = ("Транскрибируй речь из аудио дословно, на языке оригинала. Верни JSON: "
                      '{"text": "весь текст", "segments": [{"start": секунды, "end": секунды, "text": "фраза"}]}. '
                      "Фразы по 3–8 слов. Если речи нет — пустые значения.")
            body = {"contents": [{"role": "user", "parts": [{"inline_data": {"mime_type": "audio/mpeg", "data": base64.b64encode(audio.read_bytes()).decode()}}, {"text": prompt}]}],
                    "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}}
            r = c.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent", params={"key": P.secret("gemini")}, json=body); r.raise_for_status()
            text = "".join(p.get("text", "") for p in r.json()["candidates"][0]["content"]["parts"])
            d = parse_json(text)
            segs = [{"start": float(s["start"]), "end": float(s["end"]), "text": str(s["text"]).strip()} for s in d.get("segments", []) if str(s.get("text", "")).strip()]
            return {"text": d.get("text", ""), "segments": segs, "provider": "Google Gemini", "approx": True}
    raise UserError("Этот провайдер не умеет распознавать речь.")

def test_provider(pid: str) -> dict:
    """Реальная проверка подключения: запрос списка моделей / короткий ответ."""
    t0 = time.time()
    if pid == "edge_tts":
        import edge_tts, asyncio
        vs = asyncio.run(edge_tts.list_voices()); return {"ok": True, "detail": f"Доступно голосов: {len(vs)}", "ms": int((time.time() - t0) * 1000)}
    if pid == "slideshow":
        import media; media.ffmpeg_bin(); return {"ok": True, "detail": "ffmpeg найден, монтаж доступен", "ms": 0}
    if pid == "comfyui":
        with make_client(httpx.Timeout(8, connect=4)) as c:
            r = c.get(P.base_url("comfyui") + "/system_stats"); r.raise_for_status(); d = r.json()
        dev = (d.get("devices") or [{}])[0]
        vram = dev.get("vram_total")
        return {"ok": True, "detail": f"ComfyUI работает. {dev.get('name', 'Устройство')}" + (f", видеопамять {vram / 1024 ** 3:.1f} ГБ" if vram else ""), "ms": int((time.time() - t0) * 1000)}
    if pid == "pollinations_free":
        with make_client(httpx.Timeout(20, connect=10)) as c: r = c.get("https://image.pollinations.ai/models"); r.raise_for_status()
        return {"ok": True, "detail": "Сервис доступен", "ms": int((time.time() - t0) * 1000)}
    if pid == "pollinations":
        with make_client(httpx.Timeout(20, connect=10)) as c:
            r = c.get("https://gen.pollinations.ai/account/balance", headers=_auth("pollinations"))
            if r.status_code == 200:
                b = r.json(); return {"ok": True, "detail": f"Ключ работает. Баланс: {b.get('balance', b)} Pollen", "ms": int((time.time() - t0) * 1000)}
            r.raise_for_status()
        return {"ok": True, "detail": "Ключ принят", "ms": int((time.time() - t0) * 1000)}
    ms = list_models(pid)
    return {"ok": True, "detail": f"Подключено. Доступно моделей: {len(ms)}", "models": ms[:300], "ms": int((time.time() - t0) * 1000)}
