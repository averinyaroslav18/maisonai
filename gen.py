"""Генерация медиа: картинки, озвучка, видео. Только реальные вызовы провайдеров — никаких имитаций."""
import asyncio, base64, copy, json, os, random, re, shutil, time, urllib.parse, uuid
from pathlib import Path
import httpx
import ai, media, providers as P
from core import UserError, tmp_path

RATIOS = {"1:1": (1024, 1024), "9:16": (768, 1344), "16:9": (1344, 768), "4:5": (896, 1120)}

def _fit(w, h, limit):
    k = min(1.0, limit / max(w, h)); return int(w * k) // 16 * 16, int(h * k) // 16 * 16

def _save_bytes(data: bytes, ext=".jpg") -> Path:
    if len(data) < 200: raise UserError("Сервис вернул пустую картинку. Попробуйте ещё раз.")
    p = tmp_path(ext); p.write_bytes(data); return p

def _image_ext(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n": return ".png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP": return ".webp"
    return ".jpg"

def _cf_url(model): return f"https://api.cloudflare.com/client/v4/accounts/{P.secret('cloudflare', 'account')}/ai/run/{model}"

def _cf_image(r: httpx.Response) -> bytes:
    if r.headers.get("content-type", "").startswith("image/"): return r.content
    d = r.json()
    if not d.get("success", True): raise UserError("Cloudflare: " + "; ".join(e.get("message", "") for e in d.get("errors", [])))
    b64 = (d.get("result") or {}).get("image") or d.get("image")
    if not b64: raise UserError("Cloudflare не вернул картинку.")
    return base64.b64decode(b64)

def free_alt(cap: str) -> str:
    """Запасной БЕСПЛАТНЫЙ вариант, если платный провайдер недоступен. На платный не переключаемся никогда."""
    order = {"image": ["cloudflare", "comfyui", "pollinations_free"], "image_edit": ["cloudflare", "comfyui"], "video": ["hf_spaces", "comfyui", "slideshow"]}[cap]
    c = P.load_cfg()
    for pid in order:
        if pid == "comfyui" and "comfyui" not in c["use"].values(): continue
        if P.configured(pid): return pid
    return ""

def _fal_image(prompt, ratio, seed, refs, job, W, H) -> dict:
    import fal, billing
    ep = fal.model("image_edit" if refs else "image"); c = fal.cost(ep, width=W, height=H)
    r = billing.paid_call(job, "fal.ai", ep, "правка картинки" if refs else "картинка", c["units"], c["unit"], c["usd"],
                          lambda: fal.image(ep, prompt, W, H, seed, refs, ratio, job))
    return {"path": r["path"], "provider": "fal.ai · " + c["label"], "seed": seed, "width": r["width"], "height": r["height"], "paid_usd": c["usd"]}

def image(prompt: str, ratio="1:1", seed=None, refs=None, job=None, strength=0.65, negative="", _pid=None) -> dict:
    """Генерация или редактирование картинки. refs — список путей к исходным картинкам (для правки)."""
    refs = [Path(r) for r in (refs or [])]
    cap = "image_edit" if refs else "image"
    pid = _pid or ai.need(cap)
    if pid == "fal":
        import fal
        W, H = RATIOS.get(ratio, RATIOS["1:1"])
        if job: job.provider("fal.ai")
        try: return _fal_image(prompt, ratio, int(seed) if seed not in (None, "", -1) else random.randint(1, 2_000_000_000), refs, job, W, H)
        except fal.FalDown as e:
            alt = free_alt(cap)
            if not alt: raise
            if job: job.progress(getattr(job, "_p", 0.3), f"{e} Делаю бесплатно: {P.PROVIDERS[alt]['label']}.")
            r = image(prompt, ratio, seed, refs, job, strength, negative, _pid=alt); r["note"] = str(e); return r
    seed = int(seed) if seed not in (None, "", -1) else random.randint(1, 2_000_000_000)
    W, H = RATIOS.get(ratio, RATIOS["1:1"])
    if job: job.provider(P.PROVIDERS[pid]["label"])
    if pid == "pollinations_free":
        if refs: raise UserError("Бесплатный Pollinations без ключа не умеет редактировать картинки. Подключите бесплатный Cloudflare или ComfyUI.")
        ai.wait_slot("pollinations_image", 46, job)
        w, h = _fit(W, H, 768)
        url = "https://image.pollinations.ai/prompt/" + urllib.parse.quote(prompt[:1500], safe="")
        with ai.make_client() as c:
            r = c.get(url, params={"width": w, "height": h, "seed": seed, "nologo": "true", "private": "true"})
            if r.status_code in (402, 429): raise UserError("Бесплатный Pollinations сейчас ограничил запросы. Подождите минуту или подключите бесплатный Cloudflare (≈90 картинок в день).")
            r.raise_for_status()
            if not r.headers.get("content-type", "").startswith("image/"): raise UserError("Pollinations вернул не картинку. Повторите позже.")
            data = r.content
        return {"path": _save_bytes(data, _image_ext(data)), "provider": "Pollinations (бесплатно)", "seed": seed, "width": w, "height": h}
    if pid == "cloudflare":
        model = P.model_for("cloudflare", "image", "@cf/black-forest-labs/flux-2-klein-4b")
        with ai.make_client() as c:
            if "flux-1-schnell" in model and not refs:
                r = c.post(_cf_url(model), headers=ai._auth("cloudflare"), json={"prompt": prompt[:2048], "steps": 4, "seed": seed})
            else:
                if "flux-1-schnell" in model: model = "@cf/black-forest-labs/flux-2-klein-4b"
                files = {"prompt": (None, prompt[:2048]), "width": (None, str(W)), "height": (None, str(H)), "seed": (None, str(seed))}
                for i, rp in enumerate(refs[:4]): files[f"input_image_{i}"] = (rp.name, rp.read_bytes(), "image/jpeg")
                r = c.post(_cf_url(model), headers=ai._auth("cloudflare"), files=files)
            if r.status_code >= 400:
                try: msg = "; ".join(e.get("message", "") for e in r.json().get("errors", []))
                except Exception: msg = ""
                if r.status_code == 429 or "neurons" in msg.lower() or "limit" in msg.lower():
                    raise UserError("Закончился дневной бесплатный лимит Cloudflare (10 000 нейронов). Он обновится завтра — или выберите другой генератор в Настройках.")
                if msg: raise UserError("Cloudflare: " + msg[:300])
                r.raise_for_status()
            data = _cf_image(r)
        return {"path": _save_bytes(data, _image_ext(data)), "provider": "Cloudflare " + model.split("/")[-1], "seed": seed, "width": W, "height": H}
    if pid == "pollinations":
        if refs: raise UserError("Редактирование через Pollinations требует публичную ссылку на картинку. Используйте Cloudflare или ComfyUI для правок.")
        model = P.model_for("pollinations", "image", "")
        params = {"width": W, "height": H, "seed": seed}
        if model: params["model"] = model
        with ai.make_client() as c:
            r = c.get("https://gen.pollinations.ai/image/" + urllib.parse.quote(prompt[:1500], safe=""), params=params, headers=ai._auth("pollinations"))
            if r.status_code == 402: raise UserError("На балансе Pollinations недостаточно Pollen для этой модели.")
            r.raise_for_status(); data = r.content
        return {"path": _save_bytes(data, _image_ext(data)), "provider": "Pollinations " + (model or "по умолчанию"), "seed": seed, "width": W, "height": H}
    if pid == "comfyui":
        return comfy_image(prompt, W, H, seed, refs[0] if refs else None, strength, negative, job)
    raise UserError("Выбранный провайдер не умеет делать картинки.")

# ---------------- озвучка ----------------
FALLBACK_VOICES = [  # используются, только если список голосов временно не загрузился
    ("uk-UA-PolinaNeural", "Female", "uk-UA"), ("uk-UA-OstapNeural", "Male", "uk-UA"),
    ("ru-RU-SvetlanaNeural", "Female", "ru-RU"), ("ru-RU-DmitryNeural", "Male", "ru-RU"),
    ("en-US-AriaNeural", "Female", "en-US"), ("en-US-GuyNeural", "Male", "en-US"),
    ("en-US-JennyNeural", "Female", "en-US"), ("en-GB-SoniaNeural", "Female", "en-GB"), ("en-GB-RyanNeural", "Male", "en-GB"),
    ("de-DE-KatjaNeural", "Female", "de-DE"), ("de-DE-ConradNeural", "Male", "de-DE"),
    ("fr-FR-DeniseNeural", "Female", "fr-FR"), ("fr-FR-HenriNeural", "Male", "fr-FR"),
    ("es-ES-ElviraNeural", "Female", "es-ES"), ("es-ES-AlvaroNeural", "Male", "es-ES"),
    ("pl-PL-ZofiaNeural", "Female", "pl-PL"), ("pl-PL-MarekNeural", "Male", "pl-PL"),
]
_voices = {"t": 0, "v": None}

def voices() -> list:
    gem = [{"id": "gemini:" + n, "gender": "Female" if g == "F" else "Male", "locale": "multi", "name": f"Gemini · {n} ({d})", "provider": "gemini"} for n, g, d in GEMINI_VOICES] if P.configured("gemini") else []
    return gem + _edge_voices()

def _edge_voices() -> list:
    if _voices["v"] and time.time() - _voices["t"] < 86400: return _voices["v"]
    try:
        import edge_tts
        vs = asyncio.run(edge_tts.list_voices())
        out = [{"id": v["ShortName"], "gender": v.get("Gender", ""), "locale": v.get("Locale", ""), "name": v.get("FriendlyName", v["ShortName"])} for v in vs]
        _voices.update(t=time.time(), v=out); return out
    except Exception:
        return [{"id": i, "gender": g, "locale": l, "name": i} for i, g, l in FALLBACK_VOICES]

GEMINI_VOICES = [("Kore", "F", "твёрдый"), ("Puck", "M", "бодрый"), ("Charon", "M", "информативный"), ("Zephyr", "F", "яркий"),
    ("Fenrir", "M", "возбуждённый"), ("Leda", "F", "молодой"), ("Orus", "M", "твёрдый"), ("Aoede", "F", "лёгкий"), ("Callirrhoe", "F", "непринуждённый"),
    ("Autonoe", "F", "яркий"), ("Enceladus", "M", "с придыханием"), ("Iapetus", "M", "чёткий"), ("Umbriel", "M", "непринуждённый"), ("Algieba", "M", "мягкий"),
    ("Despina", "F", "мягкий"), ("Erinome", "F", "чёткий"), ("Algenib", "M", "с хрипотцой"), ("Rasalgethi", "M", "информативный"), ("Laomedeia", "F", "бодрый"),
    ("Achernar", "F", "мягкий"), ("Alnilam", "M", "твёрдый"), ("Schedar", "M", "ровный"), ("Gacrux", "F", "зрелый"), ("Pulcherrima", "F", "уверенный"),
    ("Achird", "M", "дружелюбный"), ("Zubenelgenubi", "M", "разговорный"), ("Vindemiatrix", "F", "нежный"), ("Sadachbia", "M", "живой"),
    ("Sadaltager", "M", "знающий"), ("Sulafat", "F", "тёплый")]
EMOTIONS = {"": "", "calm": "Say calmly and warmly", "happy": "Say cheerfully and with energy", "excited": "Say with excitement, like a viral TikTok hook",
            "serious": "Say seriously and confidently", "sad": "Say softly and sadly", "whisper": "Whisper", "ad": "Say like a premium advertisement voiceover"}

def gemini_tts(text, voice="Kore", rate=0, emotion="", job=None) -> dict:
    """Озвучка Gemini (бесплатный уровень Google AI Studio, в пределах дневного лимита ключа)."""
    if not P.configured("gemini"): raise UserError("Голоса Gemini работают с бесплатным ключом Gemini: Настройки → Провайдеры → Google Gemini.")
    name = voice.split(":", 1)[1] if voice.startswith("gemini:") else voice
    if name not in [v[0] for v in GEMINI_VOICES]: name = "Kore"
    prompt = (EMOTIONS.get(emotion) or emotion or "").strip()
    body = {"contents": [{"parts": [{"text": (prompt + ": " if prompt else "") + text}]}],
            "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": name}}}}}
    models = [P.model_for("gemini", "tts", "gemini-2.5-flash-preview-tts")] + [m for m in ("gemini-2.5-flash-preview-tts", "gemini-3.1-flash-tts-preview") if m != P.model_for("gemini", "tts", "gemini-2.5-flash-preview-tts")]
    last = None
    with ai.make_client(httpx.Timeout(180, connect=15)) as c:
        for m in models:
            r = ai.post_retry(c, f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent", job=job, tries=2,
                              params={"key": P.secret("gemini")}, json=body)
            if r.status_code == 200:
                try: b64 = r.json()["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
                except Exception: raise UserError("Gemini не вернул звук. Попробуйте другой голос или сократите текст.")
                pcm = tmp_path(".pcm"); pcm.write_bytes(base64.b64decode(b64)); out = tmp_path(".mp3")
                tempo = max(0.5, min(2.0, 1 + int(rate) / 100))
                media.run(["-f", "s16le", "-ar", "24000", "-ac", "1", "-i", pcm, "-af", f"atempo={tempo:.3f}", "-b:a", "160k", out])
                dur = media.probe(out)["duration"]
                return {"path": out, "segments": media.split_caption_segments(text, dur), "provider": f"Gemini TTS · {name}", "approx": True}
            last = r
            if r.status_code not in (404, 429): break
    if last is not None and last.status_code == 429: raise UserError("Закончился бесплатный лимит голосов Gemini на сегодня. Выберите голос Microsoft — они без лимита.")
    if last is not None and last.status_code in (401, 403): raise UserError("Gemini не принял ключ для озвучки.")
    raise UserError(f"Голоса Gemini сейчас недоступны (ошибка {getattr(last, 'status_code', '?')}). Выберите голос Microsoft.")

def tts(text: str, voice="uk-UA-PolinaNeural", rate=0, pitch=0, volume=0, job=None, emotion="") -> dict:
    """Возвращает {'path': mp3, 'segments': точные тайминги фраз (для субтитров), 'provider'}."""
    text = (text or "").strip()
    if not text: raise UserError("Введите текст для озвучки.")
    if len(text) > 8000: raise UserError("Текст слишком длинный (больше 8000 символов). Разбейте его на части.")
    if (voice or "").startswith("gemini:"):
        if job: job.provider("Gemini TTS")
        return gemini_tts(text, voice, rate, emotion, job)
    pid = ai.need("tts")
    if pid == "gemini": pid = "edge_tts" if P.configured("edge_tts") else pid   # голос Microsoft выбран явно
    if job: job.provider(P.PROVIDERS[pid]["label"])
    out = tmp_path(".mp3")
    if pid == "edge_tts":
        import edge_tts
        async def go():
            com = edge_tts.Communicate(text, voice, rate=f"{int(rate):+d}%", pitch=f"{int(pitch):+d}Hz", volume=f"{int(volume):+d}%", boundary="WordBoundary")
            words = []
            with open(out, "wb") as f:
                async for ch in com.stream():
                    if ch["type"] == "audio": f.write(ch["data"])
                    elif ch["type"] in ("WordBoundary", "SentenceBoundary"):
                        words.append({"start": ch["offset"] / 1e7, "end": (ch["offset"] + ch["duration"]) / 1e7, "text": ch["text"]})
            return words
        try: words = asyncio.run(go())
        except Exception as e:
            if "NoAudioReceived" in type(e).__name__: raise UserError("Голос не вернул звук. Проверьте, что язык текста совпадает с языком голоса.")
            raise UserError("Сервис голосов Microsoft сейчас недоступен. Проверьте интернет и повторите.")
        if not out.exists() or out.stat().st_size < 500: raise UserError("Озвучка не получилась. Попробуйте другой голос.")
        return {"path": out, "segments": group_words(words), "provider": "Microsoft Edge", "approx": False}
    if pid == "cloudflare":
        lang = voice.split("-")[0] if voice and "-" in voice else "en"
        if lang not in ("en", "es", "fr", "zh", "ja", "ko"): raise UserError("Голоса Cloudflare не поддерживают этот язык. Для украинского и русского используйте голоса Microsoft Edge (бесплатно).")
        with ai.make_client() as c:
            r = c.post(_cf_url("@cf/myshell-ai/melotts"), headers=ai._auth("cloudflare"), json={"prompt": text, "lang": lang}); r.raise_for_status()
            d = r.json(); b = (d.get("result") or {}).get("audio")
            if not b: raise UserError("Cloudflare не вернул звук.")
            out.write_bytes(base64.b64decode(b))
        dur = media.probe(out)["duration"]
        return {"path": out, "segments": media.split_caption_segments(text, dur), "provider": "Cloudflare MeloTTS", "approx": True}
    if pid == "pollinations":
        v = voice if voice in ("alloy", "echo", "fable", "onyx", "nova", "shimmer") else "nova"
        with ai.make_client() as c:
            r = c.post("https://gen.pollinations.ai/v1/audio/speech", headers=ai._auth("pollinations"), json={"input": text, "voice": v, "response_format": "mp3"})
            if r.status_code == 402: raise UserError("На балансе Pollinations недостаточно Pollen для озвучки.")
            r.raise_for_status(); out.write_bytes(r.content)
        dur = media.probe(out)["duration"]
        return {"path": out, "segments": media.split_caption_segments(text, dur), "provider": "Pollinations", "approx": True}
    raise UserError("Выбранный провайдер не умеет озвучивать текст.")

def group_words(words, max_words=4, max_gap=0.45) -> list:
    """Слова → короткие субтитры по 2–4 слова с реальными таймингами."""
    out, cur = [], []
    for w in words:
        if cur and (len(cur) >= max_words or w["start"] - cur[-1]["end"] > max_gap or cur[-1]["text"][-1:] in ".!?,:;"):
            out.append({"start": round(cur[0]["start"], 2), "end": round(cur[-1]["end"], 2), "text": " ".join(x["text"] for x in cur)}); cur = []
        cur.append(w)
    if cur: out.append({"start": round(cur[0]["start"], 2), "end": round(cur[-1]["end"], 2), "text": " ".join(x["text"] for x in cur)})
    for i in range(len(out) - 1):   # без мигания между фразами
        if out[i + 1]["start"] - out[i]["end"] < 0.3: out[i]["end"] = out[i + 1]["start"]
    return out

# ---------------- видео ----------------
VIDEO_CAPS = {   # честно: что умеет каждый способ
    "slideshow": {"t2v": True, "i2v": True, "v2v": False, "durations": list(range(2, 61)), "note": "Анимированный монтаж из ИИ-кадров: движение камеры, без движения персонажей."},
    "comfyui": {"t2v": True, "i2v": True, "v2v": False, "durations": [2, 3, 4, 5], "note": "Настоящее нейросетевое видео Wan 2.2 5B на вашей видеокарте (до 5 сек за проход)."},
    "pollinations": {"t2v": True, "i2v": False, "v2v": False, "durations": [4, 6, 8], "note": "Облачные видеомодели за Pollen (платные кредиты). Цена показывается до запуска."},
    "hf_spaces": {"t2v": True, "i2v": True, "v2v": False, "durations": [2, 3, 4, 5], "note": "Настоящее нейросетевое видео Wan 2.2 через Hugging Face: фото оживает — двигаются люди, волосы, вода, свет. До 5 секунд за клип. Бесплатно ≈10 клипов по 3 с (или ≈6 по 5 с) в день на аккаунт."},
}

def video(prompt: str, ratio="9:16", duration=5, image_path=None, seed=None, job=None, negative="", scenes=None, hd=False, _pid=None) -> dict:
    pid = _pid or ai.need("video")
    if job: job.provider(P.PROVIDERS[pid]["label"])
    seed = int(seed) if seed not in (None, "", -1) else random.randint(1, 2_000_000_000)
    if pid == "slideshow":
        return slideshow(prompt, ratio, duration, image_path, seed, job, scenes, hd)
    if pid == "comfyui":
        return comfy_video(prompt, ratio, duration, image_path, seed, negative, job)
    if pid == "fal":
        import fal, billing
        if not image_path:   # модели fal оживляют картинку: стартовый кадр (его цена уже в подтверждённой сумме, если картинки тоже платные)
            if job: job.progress(0.06, "Рисую стартовый кадр…")
            image_path = image(prompt, ratio, seed, job=job)["path"]
        ep = fal.model("video"); c = fal.cost(ep, seconds=duration)
        try:
            r = billing.paid_call(job, "fal.ai", ep, f"видео {c['units']} с", c["units"], c["unit"], c["usd"],
                                  lambda: fal.video(ep, prompt, Path(image_path), duration, negative, job))
        except fal.FalDown as e:
            alt = free_alt("video")
            if job: job.progress(0.3, f"{e} Делаю бесплатно: {P.PROVIDERS[alt]['label']}.")
            r = video(prompt, ratio, duration, image_path, seed, job, negative, scenes, hd, _pid=alt); r["note"] = str(e); return r
        return {"path": r["path"], "provider": "fal.ai · " + c["label"], "seed": seed, "ai_video": True, "paid_usd": c["usd"], "seconds": r["seconds"]}
    if pid == "hf_spaces":
        if not image_path:   # Wan 2.2 оживляет картинку: сначала рисуем стартовый кадр
            if job: job.progress(0.08, "Рисую стартовый кадр…")
            image_path = image(prompt, ratio, seed, job=job)["path"]
        return hf_video(prompt, duration, image_path, seed, negative, job)
    if pid == "pollinations":
        if image_path: raise UserError("Pollinations принимает стартовый кадр только по публичной ссылке. Для «картинка → видео» используйте ComfyUI или монтаж.")
        model = P.model_for("pollinations", "video", "")
        params = {"duration": int(duration), "aspectRatio": "9:16" if ratio == "9:16" else "16:9", "seed": seed}
        if model: params["model"] = model
        if job: job.progress(0.1, "Облачная модель генерирует видео (обычно 1–4 минуты)…")
        with ai.make_client(httpx.Timeout(900, connect=20)) as c:
            r = c.get("https://gen.pollinations.ai/video/" + urllib.parse.quote(prompt[:1500], safe=""), params=params, headers=ai._auth("pollinations"))
            if r.status_code == 402: raise UserError("На балансе Pollinations недостаточно Pollen для видео.")
            r.raise_for_status()
            if "video" not in r.headers.get("content-type", ""): raise UserError("Pollinations вернул не видео. Попробуйте другую модель.")
            p = tmp_path(".mp4"); p.write_bytes(r.content)
        return {"path": p, "provider": "Pollinations " + (model or "по умолчанию"), "seed": seed, "ai_video": True}
    raise UserError("Выбранный провайдер не умеет делать видео.")

def slideshow(prompt, ratio, duration, image_path, seed, job, scenes=None, hd=False) -> dict:
    """Кадры рисует ИИ (по сценам), программа анимирует их и склеивает. Честно помечается как монтаж."""
    duration = max(2, min(60, int(duration)))
    if scenes: shots = [s for s in scenes if s.get("prompt")][:12]
    else:
        n = max(1, min(6, round(duration / 3)))
        if n == 1 or image_path: shots = [{"prompt": prompt}]
        else:
            try:
                plan = ai.chat_json("Ты раскадровщик коротких вертикальных видео. Пиши промпты на английском для генератора картинок.",
                    f"Разбей идею на {n} последовательных кадров одного ролика, сохраняя одного и того же персонажа и стиль. Идея: {prompt}\n"
                    'Верни JSON: {"shots": [{"prompt": "detailed English image prompt, same character description repeated"}]}', job=job, temperature=0.7)
                shots = [s for s in plan.get("shots", []) if s.get("prompt")][:n] or [{"prompt": prompt}]
            except UserError: shots = [{"prompt": prompt}]
    imgs = []
    if image_path: imgs.append(Path(image_path))
    for i, s in enumerate(shots[len(imgs):] if image_path else shots):
        if job: job.progress(0.1 + 0.6 * i / max(1, len(shots)), f"Рисую кадр {i + 1} из {len(shots)}…"); job._p = 0.1 + 0.6 * i / max(1, len(shots))
        imgs.append(image(s["prompt"], ratio, seed + i, job=job)["path"])
    W, H = (media.HD if hd else media.FORMATS).get(ratio, media.FORMATS["9:16"])
    per = duration / len(imgs); motions = ["zoom_in", "pan_right", "zoom_out", "pan_left"]; parts = []
    for i, im in enumerate(imgs):
        if job: job.progress(0.72 + 0.2 * i / len(imgs), "Анимирую кадры…")
        parts.append(media.image_clip(im, per, W, H, motions[i % 4]))
    out = media.concat(parts)
    return {"path": out, "provider": "Монтаж из ИИ-кадров", "seed": seed, "ai_video": False, "frames": [str(p) for p in imgs]}

# ---------------- ComfyUI (локально) ----------------
def _comfy():
    return P.base_url("comfyui") or "http://127.0.0.1:8188"

def _comfy_upload(c, path: Path) -> str:
    r = c.post(_comfy() + "/upload/image", files={"image": (f"maison_{uuid.uuid4().hex[:8]}{path.suffix}", path.read_bytes(), "image/png")}, data={"overwrite": "true"})
    r.raise_for_status(); d = r.json(); return (d.get("subfolder") + "/" if d.get("subfolder") else "") + d["name"]

def _comfy_run(graph: dict, job, p0=0.1, p1=0.95, expect=(".png", ".jpg", ".webp", ".mp4", ".webm")) -> tuple:
    with ai.make_client(httpx.Timeout(60, connect=5)) as c:
        try: r = c.post(_comfy() + "/prompt", json={"prompt": graph, "client_id": "maisonai"})
        except httpx.ConnectError: raise UserError("ComfyUI не запущен. Откройте ComfyUI на этом компьютере и повторите.")
        if r.status_code == 400:
            d = r.json(); errs = d.get("node_errors") or {}
            missing = []
            for ne in errs.values():
                for e in ne.get("errors", []):
                    if "not in" in str(e.get("details", "")) or e.get("type") == "value_not_in_list": missing.append(str(e.get("details", ""))[:160])
            if missing: raise UserError("В ComfyUI не хватает моделей: " + "; ".join(missing[:2]) + ". Скачайте их (ссылки в Настройках → ComfyUI).")
            raise UserError("ComfyUI отклонил задание: " + json.dumps(d.get("error", d), ensure_ascii=False)[:300])
        r.raise_for_status(); pid = r.json()["prompt_id"]
        t0 = time.time()
        while True:
            time.sleep(2)
            h = c.get(_comfy() + f"/history/{pid}").json()
            if pid in h:
                st = h[pid].get("status", {})
                if st.get("status_str") == "error":
                    msg = next((m[1].get("exception_message", "") for m in st.get("messages", []) if m[0] == "execution_error"), "")
                    if "out of memory" in msg.lower() or "OutOfMemory" in msg: raise UserError("Не хватило видеопамяти. Уменьшите длительность/разрешение или закройте другие программы.")
                    raise UserError("ComfyUI: " + (msg[:300] or "ошибка выполнения"))
                for out in h[pid].get("outputs", {}).values():
                    for key in ("images", "gifs", "videos", "video"):
                        for f in out.get(key, []) or []:
                            if str(f.get("filename", "")).lower().endswith(expect):
                                v = c.get(_comfy() + "/view", params={"filename": f["filename"], "subfolder": f.get("subfolder", ""), "type": f.get("type", "output")}, timeout=120)
                                v.raise_for_status(); ext = Path(f["filename"]).suffix
                                p = tmp_path(ext); p.write_bytes(v.content); return p, f["filename"]
                raise UserError("ComfyUI завершил работу, но не вернул файл.")
            el = int(time.time() - t0)
            if job:
                try:
                    q = c.get(_comfy() + "/queue").json(); ahead = len(q.get("queue_pending", []))
                    msg = f"ComfyUI: в очереди перед вами {ahead}" if ahead else f"ComfyUI генерирует… {el // 60}:{el % 60:02d}"
                except Exception: msg = f"ComfyUI генерирует… {el // 60}:{el % 60:02d}"
                job.progress(min(p1, p0 + (p1 - p0) * (1 - 1 / (1 + el / 120))), msg)
            if el > 3600: raise UserError("ComfyUI работает больше часа — задача остановлена.")

def comfy_models(kind="checkpoints") -> list:
    with ai.make_client(httpx.Timeout(10, connect=4)) as c:
        r = c.get(_comfy() + f"/models/{kind}"); r.raise_for_status(); return r.json()

def comfy_image(prompt, W, H, seed, ref, strength, negative, job) -> dict:
    ckpt = P.model_for("comfyui", "image", "")
    if not ckpt:
        try: ck = comfy_models("checkpoints")
        except httpx.ConnectError: raise UserError("ComfyUI не запущен. Откройте ComfyUI и повторите.")
        if not ck: raise UserError("В ComfyUI нет ни одной модели-чекпойнта для картинок. Скачайте, например, SDXL и выберите её в Настройках.")
        ckpt = ck[0]
    sd15 = "1.5" in ckpt or "sd15" in ckpt.lower()
    if sd15: W, H = _fit(W, H, 768)
    g = {"1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ckpt}},
         "2": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["1", 1]}},
         "3": {"class_type": "CLIPTextEncode", "inputs": {"text": negative or "lowres, blurry, watermark, text, deformed", "clip": ["1", 1]}},
         "5": {"class_type": "KSampler", "inputs": {"seed": seed, "steps": 28, "cfg": 6.0, "sampler_name": "dpmpp_2m", "scheduler": "karras", "denoise": 1.0,
               "model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0], "latent_image": ["4", 0]}},
         "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
         "7": {"class_type": "SaveImage", "inputs": {"filename_prefix": "MaisonAI", "images": ["6", 0]}}}
    with ai.make_client(httpx.Timeout(60, connect=5)) as c:
        if ref:
            name = _comfy_upload(c, Path(ref))
            g["8"] = {"class_type": "LoadImage", "inputs": {"image": name}}
            g["9"] = {"class_type": "ImageScale", "inputs": {"image": ["8", 0], "upscale_method": "lanczos", "width": W, "height": H, "crop": "center"}}
            g["4"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["9", 0], "vae": ["1", 2]}}
            g["5"]["inputs"]["denoise"] = max(0.2, min(0.95, float(strength)))
        else:
            g["4"] = {"class_type": "EmptyLatentImage", "inputs": {"width": W, "height": H, "batch_size": 1}}
    p, _ = _comfy_run(g, job, expect=(".png", ".jpg", ".webp"))
    return {"path": p, "provider": "ComfyUI " + ckpt, "seed": seed, "width": W, "height": H}

WAN = {"unet": "wan2.2_ti2v_5B_fp16.safetensors", "clip": "umt5_xxl_fp8_e4m3fn_scaled.safetensors", "vae": "wan2.2_vae.safetensors"}
WAN_NEG = "色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，最差质量，低质量，JPEG压缩残留，丑陋的，残缺的，多余的手指，画得不好的手部，画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合，静止不动的画面，杂乱的背景，三条腿，背景人很多，倒着走"

def comfy_video(prompt, ratio, duration, image_path, seed, negative, job) -> dict:
    """Wan 2.2 TI2V 5B — официальная схема ComfyUI (текст→видео и картинка→видео), 24 кадра/сек."""
    dims = {"9:16": (704, 1280), "16:9": (1280, 704), "1:1": (960, 960), "4:5": (832, 1040)}
    W, H = dims.get(ratio, dims["9:16"])
    length = min(121, int(max(1, duration) * 24) // 4 * 4 + 1)
    g = {"37": {"class_type": "UNETLoader", "inputs": {"unet_name": WAN["unet"], "weight_dtype": "default"}},
         "38": {"class_type": "CLIPLoader", "inputs": {"clip_name": WAN["clip"], "type": "wan", "device": "default"}},
         "39": {"class_type": "VAELoader", "inputs": {"vae_name": WAN["vae"]}},
         "48": {"class_type": "ModelSamplingSD3", "inputs": {"shift": 8, "model": ["37", 0]}},
         "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["38", 0]}},
         "7": {"class_type": "CLIPTextEncode", "inputs": {"text": negative or WAN_NEG, "clip": ["38", 0]}},
         "55": {"class_type": "Wan22ImageToVideoLatent", "inputs": {"width": W, "height": H, "length": length, "batch_size": 1, "vae": ["39", 0]}},
         "3": {"class_type": "KSampler", "inputs": {"seed": seed, "steps": 20, "cfg": 5, "sampler_name": "uni_pc", "scheduler": "simple", "denoise": 1,
               "model": ["48", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["55", 0]}},
         "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["39", 0]}},
         "57": {"class_type": "CreateVideo", "inputs": {"fps": 24, "images": ["8", 0]}},
         "58": {"class_type": "SaveVideo", "inputs": {"filename_prefix": "video/MaisonAI", "format": "auto", "codec": "auto", "video": ["57", 0]}}}
    if image_path:
        with ai.make_client(httpx.Timeout(60, connect=5)) as c:
            try: name = _comfy_upload(c, Path(image_path))
            except httpx.ConnectError: raise UserError("ComfyUI не запущен. Откройте ComfyUI и повторите.")
        g["56"] = {"class_type": "LoadImage", "inputs": {"image": name}}
        g["55"]["inputs"]["start_image"] = ["56", 0]
    if job: job.progress(0.05, "Отправляю задание в ComfyUI (Wan 2.2)…")
    p, _ = _comfy_run(g, job, expect=(".mp4", ".webm", ".mov"))
    return {"path": p, "provider": "ComfyUI · Wan 2.2 5B", "seed": seed, "ai_video": True}

def pollinations_price(kind="video") -> list:
    """Реальные цены моделей Pollinations из их каталога (для честного показа стоимости)."""
    with ai.make_client(httpx.Timeout(20, connect=8)) as c:
        r = c.get(f"https://gen.pollinations.ai/{kind}/models"); r.raise_for_status(); data = r.json()
    out = []
    for m in data if isinstance(data, list) else []:
        if isinstance(m, dict): out.append({"id": m.get("name") or m.get("id"), "description": m.get("description", ""), "pricing": m.get("pricing"), "paid_only": m.get("paid_only", False)})
    return out


# ---------------- Hugging Face Spaces (бесплатная квота ZeroGPU) ----------------
HF_SPACE = "zerogpu-aoti/wan2-2-fp8da-aoti-faster"
HF_NEG = "static, frozen, still image, blurry, distorted face, extra fingers, deformed hands, watermark, text, subtitles, low quality, jpeg artifacts, flicker"
make_hf_client = None   # для тестов

HF_EMPTY = {}   # токен → когда у него закончилась квота
# Hugging Face списывает лимит не по факту, а по оценке пространства: 10 с + шаги × время шага.
# 4 шага (так настроена ускоренная модель по умолчанию) — примерно в 1,5 раза больше клипов из того же лимита.
HF_STEPS = 4
class _HfQuota(Exception): pass

def _hf_once(space, token, prompt, duration, image_path, seed, negative, job):
    from gradio_client import Client, handle_file
    out_dir = tmp_path(""); out_dir.mkdir()
    if job: job.progress(getattr(job, "_p", 0.1), "Подключаюсь к Hugging Face…")
    try:
        client = (make_hf_client or Client)(space, token=token, verbose=False, download_files=str(out_dir))
        jb = client.submit(handle_file(str(image_path)), prompt[:1200], HF_STEPS, negative or HF_NEG, float(max(1, min(5, duration))), 1, 1, int(seed) % 2147483647, False, api_name="/generate_video")
        t0 = time.time()
        while not jb.done():
            if job:
                job.check()
                try:
                    st = jb.status(); rank = getattr(st, "rank", None); eta = getattr(st, "eta", None)
                    msg = f"Hugging Face: в очереди перед вами {rank}" if rank else ("Нейросеть оживляет фото…" + (f" ≈{int(eta)} с" if eta else ""))
                except Exception: msg = "Нейросеть оживляет фото…"
                el = time.time() - t0; job.progress(min(0.95, getattr(job, "_p", 0.1) + 0.5 * (1 - 1 / (1 + el / 60))), msg)
            if time.time() - t0 > 900: raise UserError("Hugging Face не ответил за 15 минут. Повторите позже.")
            time.sleep(1)
        return jb.result()
    except UserError: raise
    except Exception as e:
        s = str(e)
        if any(k in s.lower() for k in ("quota", "exceeded", "zerogpu")): raise _HfQuota(s)
        if any(k in s for k in ("401", "403", "Invalid token", "Unauthorized")): raise UserError("Hugging Face не принял токен. Проверьте его в Настройках → Провайдеры.")
        if any(k in s.lower() for k in ("could not fetch", "not found", "paused", "sleeping", "runtime error", "build error")):
            raise UserError(f"Пространство Hugging Face «{space}» сейчас недоступно. Повторите позже.")
        raise UserError("Hugging Face вернул ошибку: " + s.splitlines()[-1][:250] if s else "Hugging Face вернул ошибку.")

def hf_video(prompt, duration, image_path, seed, negative, job) -> dict:
    """Оживление фото моделью Wan 2.2 (14B) в публичном пространстве Hugging Face. Тратит вашу бесплатную дневную квоту."""
    try: from gradio_client import Client, handle_file
    except ImportError: raise UserError("Не установлен клиент Hugging Face. Запустите INSTALL.bat ещё раз.")
    space = P.model_for("hf_spaces", "video", HF_SPACE)
    toks = re.findall(r"hf_\w+", P.secret("hf_spaces") or "") or [None]
    if toks != [None] and not os.environ.get("MAISONAI_CLOUD"): toks.append(False)   # дома: потом гостевой лимит без аккаунта
    now = time.time()
    fresh = [t for t in toks if now - HF_EMPTY.get(t, 0) > 3600] or toks   # у кого лимит кончился — пробуем через час
    last = None
    for i, tok in enumerate(fresh):
        try:
            res = _hf_once(space, tok, prompt, duration, image_path, seed, negative, job)
            break
        except _HfQuota as e:
            HF_EMPTY[tok] = time.time(); last = e
            if job and i + 1 < len(fresh): job.progress(getattr(job, "_p", 0.1), "Лимит этого аккаунта кончился — пробую следующий…")
    else:
        raise UserError("Закончилась бесплатная дневная квота Hugging Face" + (" на всех подключённых аккаунтах" if len(fresh) > 1 else "")
                        + ". Она постепенно восстанавливается в течение суток — или ролик соберётся монтажом из фото.")
    vid = res[0] if isinstance(res, (list, tuple)) else res
    if isinstance(vid, dict): vid = vid.get("video") or vid.get("path") or vid.get("value")
    if not vid or not Path(str(vid)).exists(): raise UserError("Hugging Face не вернул видео. Повторите.")
    p = tmp_path(".mp4"); shutil.copy(str(vid), p)
    return {"path": p, "provider": "Hugging Face · Wan 2.2", "seed": seed, "ai_video": True}
