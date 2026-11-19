"""Инструменты MaisonAI: сценарии, анализ TikTok, воссоздание стиля, монтаж, ассистент. Все шаги — реальные вызовы ИИ и ffmpeg."""
import json, random, re, shutil
from pathlib import Path
import ai, gen, media, providers as P
from core import UserError, asset_file, db, get_asset, jload, rows, tmp_path

LANGS = {"uk": "украинском", "ru": "русском", "en": "английском", "de": "немецком", "pl": "польском", "es": "испанском", "fr": "французском"}
ANGLES = ["личная история от первого лица", "разрушение популярного мифа", "топ-3 с неожиданным последним пунктом", "до/после с резким контрастом",
          "провокационный вопрос к зрителю", "POV-сценка", "быстрый туториал по шагам", "закулисье процесса", "ошибка, которую делают все",
          "мини-эксперимент с результатом", "сторителлинг с поворотом в конце", "сравнение двух подходов", "реакция на распространённое мнение"]

# ---------------- сценарии ----------------
SCRIPT_SYS = """Ты — сильный сценарист коротких вертикальных видео (TikTok, Reels, Shorts).
Пиши живо, конкретно, без воды и без клише вроде «в этом видео я расскажу». Никаких выдуманных фактов и статистики:
если нужна цифра, которую ты не можешь гарантировать, формулируй без неё. Ответ — строго JSON."""

def script(job, topic, duration=30, language="uk", style="", audience="", goal="", avoid=None, extra=""):
    if not str(topic).strip(): raise UserError("Опишите тему видео.")
    angle = random.choice(ANGLES)
    lang = LANGS.get(language, language)
    avoid_txt = ("\nУже были варианты с такими названиями — придумай принципиально другой подход: " + "; ".join(avoid[:8])) if avoid else ""
    user = f"""Тема: {topic}
Длительность: {duration} секунд
Язык текста: {lang}
Стиль подачи: {style or 'на твой выбор, под тему'}
Целевая аудитория: {audience or 'определи сам по теме'}
Желаемый результат: {goal or 'удержание и вовлечение'}
Угол подачи для этой версии: {angle}{avoid_txt}
{('Дополнительно: ' + extra) if extra else ''}

Верни JSON:
{{"idea": "суть идеи в 1–2 предложениях",
 "hook": "первая фраза/действие на 0–3 секунде, которая останавливает скролл",
 "script": "полный сценарий с ремарками",
 "voiceover": "только текст для озвучки, без ремарок, ровно под {duration} сек (≈2.3 слова в секунду)",
 "scenes": [{{"time": "0–3 с", "visual": "что в кадре", "voiceover": "что звучит", "on_screen_text": "текст на экране"}}],
 "visual_tips": ["рекомендации по свету, кадру, монтажу"],
 "subtitles": ["короткие строки субтитров по 2–5 слов в порядке звучания"],
 "title": "заголовок ролика",
 "description": "описание публикации 1–3 предложения",
 "hashtags": ["#..."],
 "image_prompts": ["detailed English prompt for each scene, same character & style"],
 "video_prompt": "one detailed English prompt for an AI video model describing the whole clip"}}
Все тексты, кроме image_prompts и video_prompt, — на {lang} языке."""
    job.progress(0.15, "Пишу сценарий…")
    d = ai.chat_json(SCRIPT_SYS, user, job=job, temperature=0.95)
    for k in ("idea", "hook", "script", "voiceover", "title", "description"): d.setdefault(k, "")
    for k in ("scenes", "visual_tips", "subtitles", "hashtags", "image_prompts"): d[k] = d.get(k) if isinstance(d.get(k), list) else []
    d["hashtags"] = [h if str(h).startswith("#") else "#" + str(h).replace(" ", "") for h in d["hashtags"]]
    d["angle"] = angle; d["params"] = {"topic": topic, "duration": duration, "language": language, "style": style, "audience": audience, "goal": goal}
    p = tmp_path(".json"); p.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    a = job.asset(p, kind="script", name=(d["title"] or topic)[:120] + ".json", mime="application/json", meta={"title": d["title"]})
    return {"script": d, "asset": a}

def improve_prompt(job, text, target="video", ratio="9:16", style="", camera="", characters=""):
    sys = "Ты — промпт-инженер для генеративных моделей. Пишешь точные визуальные промпты на английском."
    user = f"""Преобразуй запрос пользователя в качественный промпт для {'видеомодели' if target == 'video' else 'генератора изображений'}.
Запрос: {text}
Формат кадра: {ratio}. Стиль: {style or 'по смыслу'}. Камера: {camera or 'по смыслу'}. Персонажи: {characters or 'из запроса'}.
Опиши: субъект и внешность, одежду, действие, окружение, свет, цветовую палитру, {'движение камеры и темп, ' if target == 'video' else 'ракурс и объектив, '}атмосферу.
Без имён реальных людей и брендов. Верни JSON: {{"prompt": "English prompt, 60-120 words", "negative": "short English negative prompt", "summary_ru": "1 предложение по-русски: что получится"}}"""
    return ai.chat_json(sys, user, job=job, temperature=0.6)

# ---------------- получение видео (загрузка или ссылка) ----------------
def fetch_video(job, uid, asset_id=None, url=None) -> tuple:
    if asset_id:
        a = get_asset(uid, asset_id)
        if not a or a["kind"] != "video": raise UserError("Видео не найдено. Загрузите его ещё раз.")
        return asset_file(a), a["name"], None
    url = (url or "").strip()
    if not re.match(r"^https?://", url): raise UserError("Вставьте ссылку на видео (начинается с https://) или загрузите файл.")
    job.progress(0.05, "Скачиваю видео по ссылке…")
    path, info, note = download_link(job, url)
    meta = {k: info.get(k) for k in ("title", "uploader", "view_count", "like_count", "comment_count", "duration", "upload_date", "webpage_url") if info.get(k) is not None}
    if note: meta["note"] = note
    title = (info.get("title") or info.get("description") or "Видео по ссылке").strip().splitlines()[0][:100] or "Видео по ссылке"
    a = job.asset(path, kind="video", name=title + ".mp4", meta={"source_url": url, "public_stats": meta, "photo_post": bool(note)})
    return asset_file(get_asset(uid, a["id"])), a["name"], meta

MEDIA_EXT = (".mp4", ".webm", ".mkv", ".mov", ".m4v", ".flv", ".ts", ".3gp", ".m4a", ".mp3", ".aac", ".opus", ".ogg", ".wav", ".unknown_video")

def download_link(job, url):
    """Скачивание по ссылке с несколькими попытками. Фото-посты TikTok (слайдшоу) собираются в видео из их картинок и звука."""
    try: import yt_dlp
    except ImportError: raise UserError("Не установлен загрузчик видео. Запустите INSTALL.bat ещё раз.")
    base = {"noplaylist": True, "quiet": True, "no_warnings": True, "ffmpeg_location": media.ffmpeg_bin(),
            "merge_output_format": "mp4", "retries": 3, "extractor_retries": 3, "socket_timeout": 30, "max_filesize": 400 * 1024 * 1024,
            "http_headers": {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"}}
    try:   # маскировка под браузер (помогает с TikTok), если установлен curl_cffi
        from yt_dlp.networking.impersonate import ImpersonateTarget
        import curl_cffi  # noqa
        base["impersonate"] = ImpersonateTarget.from_str("chrome")
    except Exception: pass
    attempts = ["bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b", "best", "bestaudio/best"]
    last_err, info = "", {}
    for i, fmt in enumerate(attempts):
        out_dir = tmp_path(""); out_dir.mkdir()
        opts = {**base, "format": fmt, "outtmpl": str(out_dir / "v.%(ext)s")}
        job.progress(0.05 + i * 0.02, "Скачиваю по ссылке…" if i == 0 else f"Пробую другой способ загрузки ({i + 1} из {len(attempts)})…")
        try:
            with yt_dlp.YoutubeDL(opts) as y:
                info = y.extract_info(url, download=True) or {}
                if info.get("_type") == "playlist" and info.get("entries"): info = next((e for e in info["entries"] if e), info)
                files = [f for f in out_dir.iterdir() if f.is_file() and not f.name.endswith((".part", ".ytdl")) and f.suffix.lower() in MEDIA_EXT and f.stat().st_size > 1000]
                vids = [f for f in files if _has_video(f)]
                if vids: return vids[0], info, ""
                # фото-пост TikTok: картинки + музыка → собираем ролик сами
                imgs = _post_images(info)
                if imgs:
                    job.progress(0.1, f"Это фото-пост TikTok: собираю видео из {len(imgs)} картинок…")
                    return _slideshow(y, imgs, files[0] if files else None), info, f"Фото-пост (слайдшоу): видео собрано из {len(imgs)} картинок" + (" и звука поста." if files else ".")
                last_err = "сайт отдал только звук без картинки" if files else "сайт не отдал файл"
        except Exception as e:
            last_err = str(e).splitlines()[-1].replace("ERROR: ", "")[:220]
            if any(s in last_err for s in ("Unsupported URL", "is not a valid URL")): break
            if "Private" in last_err or "login" in last_err.lower(): break
    hint = ""
    if "ffmpeg" in last_err.lower(): hint = " Не хватает ffmpeg — запустите INSTALL.bat ещё раз."
    elif any(s in last_err for s in ("Private", "login", "Log in")): hint = " Ролик закрыт или требует входа в аккаунт."
    elif "Unsupported URL" in last_err: hint = " Этот адрес не похож на ссылку на ролик — скопируйте ссылку через «Поделиться» → «Копировать ссылку»."
    raise UserError("Не удалось скачать видео по ссылке (" + (last_err or "неизвестная причина") + ")." + hint +
                    " Загрузчик TikTok часто ломается, когда TikTok меняет сайт: запустите INSTALL.bat — он обновит загрузчик. "
                    "Самый надёжный способ: в TikTok «Поделиться» → «Сохранить видео» и загрузить файл сюда.")

def _has_video(f) -> bool:
    try: return media.probe(f)["has_video"] and media.probe(f)["duration"] > 0.3
    except Exception: return False

def _post_images(info) -> list:
    urls = []
    for key in ("images", "image_post_info"):
        v = info.get(key)
        if isinstance(v, list):
            for it in v:
                u = it.get("url") if isinstance(it, dict) else it
                if isinstance(u, str): urls.append(u)
    if not urls:   # у фото-постов картинки приходят как миниатюры
        th = [t for t in (info.get("thumbnails") or []) if t.get("url")]
        big = sorted(th, key=lambda t: -(t.get("width") or 0) * (t.get("height") or 0))
        seen = set()
        for t in big:
            k = t["url"].split("?")[0]
            if k not in seen: seen.add(k); urls.append(t["url"])
        urls = urls[:1] if len(urls) and not info.get("formats") else urls[:12]
    return urls[:12]

def _slideshow(y, imgs, audio):
    from PIL import Image
    parts = []
    W, H = media.FORMATS["9:16"]
    for i, u in enumerate(imgs):
        try:
            data = y.urlopen(u).read()
            p = tmp_path(".jpg")
            with Image.open(__import__("io").BytesIO(data)) as im: im.convert("RGB").save(p, quality=92)
            parts.append(media.image_clip(p, 2.5, W, H, ["zoom_in", "pan_right", "zoom_out", "pan_left"][i % 4]))
        except Exception: continue
    if not parts: raise UserError("Это фото-пост TikTok, но его картинки не скачались. Сделайте скриншоты и загрузите их в TikTok Intelligence.")
    video = media.concat(parts)
    return media.mux_voice(video, audio, 1.0, 0.0) if audio else video

def measure(video: Path) -> dict:
    """Реальные измерения ролика (не догадки ИИ)."""
    info = media.probe(video); d = info["duration"] or 0.01
    cuts = media.scene_cuts(video)
    shots = [b - a for a, b in zip([0.0] + cuts, cuts + [d])] if d else []
    return {"duration": round(d, 2), "width": info["width"], "height": info["height"], "fps": info["fps"], "has_audio": info["has_audio"],
            "vertical": info["height"] > info["width"], "cuts": cuts, "cut_count": len(cuts),
            "cuts_per_10s": round(len(cuts) / d * 10, 2), "avg_shot": round(sum(shots) / len(shots), 2) if shots else round(d, 2),
            "first_cut": cuts[0] if cuts else None, "cuts_first_3s": len([c for c in cuts if c <= 3]), "loudness": media.loudness_profile(video)}

# ---------------- анализ TikTok ----------------
ANALYZE_JSON = """{"overall": {"score": число 1-10, "verdict": "1 предложение"},
 "first_seconds": "что происходит в первые 3 секунды и работает ли это",
 "hook": "в чём крючок и насколько он сильный",
 "script": "структура и драматургия",
 "editing": "монтаж, переходы, ритм (опирайся на реальные измерения склеек)",
 "visual_style": "визуальный стиль, свет, цвет, композиция",
 "subtitles": "есть ли субтитры/текст на экране и как оформлены",
 "voiceover": "голос/музыка/звук",
 "pace": "темп видео",
 "retention": "качественная оценка удержания внимания БЕЗ цифр",
 "strengths": ["..."], "weaknesses": ["..."],
 "why_interesting": "почему видео может заинтересовать зрителя",
 "how_to_make_similar": ["шаги, как сделать похожее, но оригинальное видео"],
 "new_script": {"title": "...", "hook": "...", "voiceover": "...", "scenes": [{"time": "0–3 с", "visual": "...", "on_screen_text": "..."}]},
 "generation_prompt": "готовый детальный English prompt для генерации нового оригинального ролика"}"""

def analyze(job, asset_id=None, url=None, language="ru", uid=None, focus=""):
    video, name, public = fetch_video(job, uid, asset_id, url)
    job.progress(0.15, "Измеряю ролик: длительность, склейки, громкость…")
    m = measure(video)
    transcript = None
    if m["has_audio"] and P.chosen("stt"):
        job.progress(0.3, "Распознаю речь…")
        try: transcript = ai.transcribe(media.extract_audio(video), job=job)
        except UserError: transcript = None
        except Exception: transcript = None
    if transcript and transcript.get("text"):
        words = len(transcript["text"].split()); m["words_per_min"] = round(words / max(m["duration"], 1) * 60)
    facts = json.dumps({k: v for k, v in m.items() if k != "loudness"}, ensure_ascii=False)
    lang = LANGS.get(language, "русском")
    base = (f"Ты — эксперт по коротким видео. Проанализируй ролик честно и конкретно. Пиши на {lang} языке.\n"
            f"РЕАЛЬНЫЕ ИЗМЕРЕНИЯ ролика (используй их, не придумывай другие цифры): {facts}\n"
            + (f"Расшифровка речи: {transcript['text'][:4000]}\n" if transcript and transcript.get('text') else "")
            + (f"Пользователь просит обратить внимание: {focus}\n" if focus else "")
            + "ЗАПРЕЩЕНО выдумывать просмотры, лайки, проценты удержания и любую статистику TikTok — её у тебя нет.\n"
            + "Верни строго JSON:\n" + ANALYZE_JSON)
    mode = ""
    if P.chosen("video_understanding"):
        job.progress(0.45, "ИИ смотрит видео целиком…"); mode = "video"
        small = media.compress_for_ai(video)
        res = ai.gemini_video_json(small, base, job=job)
    elif P.chosen("vision"):
        job.progress(0.45, "ИИ изучает кадры ролика…"); mode = "frames"
        fr = media.frames(video, 8)
        parts = [{"type": "text", "text": base + "\nНиже 8 равномерных кадров ролика с отметками времени."}]
        for t, p in fr: parts += [{"type": "text", "text": f"Кадр на {t} с:"}, ai.image_part(p)]
        res = ai.parse_json(ai.chat([{"role": "user", "content": parts}], cap="vision", json_mode=True, job=job, temperature=0.4))
    else:
        job.progress(0.45, "Анализирую по измерениям и речи (без просмотра картинки)…"); mode = "text"
        if not transcript: raise UserError("Для анализа видео подключите бесплатный ключ Gemini (смотрит видео целиком) — Настройки → Провайдеры. Без него ИИ не видит, что в кадре.")
        res = ai.chat_json("Ты эксперт по коротким видео.", base + "\nВНИМАНИЕ: картинку ролика ты не видишь — оценивай визуал осторожно и прямо пиши, что он не проверен.", job=job, temperature=0.4)
    thumb = job.asset(media.thumbnail(video), kind="image", name="Обложка " + name[:60] + ".jpg")
    return {"report": res, "measured": m, "transcript": transcript, "mode": mode, "public_stats": public, "thumbnail": thumb, "video_name": name}

# ---------------- воссоздание стиля (Character & Video Recreation) ----------------
DNA_JSON = """{"characters": [{"id": "c1", "role": "главный герой", "appearance": "внешность без узнаваемых личных данных", "clothing": "одежда", "hair": "причёска", "expression": "мимика и поведение"}],
 "environment": "окружение и локации",
 "lighting": "освещение",
 "palette": ["#hex", "#hex", "#hex", "#hex"],
 "palette_words": "цветовая палитра словами",
 "camera_style": "стиль съёмки (объектив, план, стабилизация)",
 "camera_moves": "движения камеры",
 "editing": "монтаж и темп",
 "scenes": [{"time": "0–3 с", "description": "что происходит"}],
 "mood": "общая визуальная атмосфера",
 "audio": "звук/голос/музыка"}"""

def recreate_analyze(job, asset_id=None, url=None, uid=None):
    video, name, _ = fetch_video(job, uid, asset_id, url)
    m = measure(video)
    prompt = ("Ты — оператор-постановщик. Разбери визуальную ДНК ролика, чтобы потом снять НОВЫЙ оригинальный ролик в похожем стиле "
              "(не копию). Описывай внешность обобщённо, без имён и без узнаваемых личных данных. Пиши по-русски, палитру — hex-кодами. "
              f"Реальные измерения: длительность {m['duration']} с, склеек {m['cut_count']}, средний план {m['avg_shot']} с. Верни строго JSON:\n" + DNA_JSON)
    if P.chosen("video_understanding"):
        job.progress(0.35, "ИИ смотрит референс целиком…")
        dna = ai.gemini_video_json(media.compress_for_ai(video), prompt, job=job)
    elif P.chosen("vision"):
        job.progress(0.35, "ИИ изучает кадры референса…")
        parts = [{"type": "text", "text": prompt}]
        for t, p in media.frames(video, 8): parts += [{"type": "text", "text": f"Кадр {t} с:"}, ai.image_part(p)]
        dna = ai.parse_json(ai.chat([{"role": "user", "content": parts}], cap="vision", json_mode=True, job=job, temperature=0.3))
    else:
        raise UserError("Для анализа референса подключите бесплатный ключ Gemini (Настройки → Провайдеры) — без него ИИ не видит видео.")
    fr = []
    for t, p in media.frames(video, 4, width=480): fr.append(job.asset(p, kind="image", name=f"Кадр референса {t} с.jpg", meta={"reference_frame": True}))
    return {"dna": dna, "measured": {k: v for k, v in m.items() if k != "loudness"}, "frames": fr, "video_name": name}

PLAN_SYS = """Ты — режиссёр коротких видео. Создаёшь НОВЫЙ оригинальный ролик, вдохновлённый визуальной ДНК референса.
Нельзя покадрово копировать чужое видео, использовать реальных людей, логотипы и чужие тексты. Ответ — строго JSON."""

def recreate_plan(job, dna, locks=None, instructions="", duration=15, language="ru", ratio="9:16"):
    locks = locks or {}
    keep = [k for k, v in locks.items() if v]
    user = f"""Визуальная ДНК референса: {json.dumps(dna, ensure_ascii=False)[:6000]}
Сохранить без изменений (заблокировано пользователем): {', '.join(keep) if keep else 'ничего не заблокировано'}
Пожелания пользователя: {instructions or 'сохрани общий стиль, придумай новый сюжет'}
Длительность: {duration} с. Формат кадра: {ratio}. Язык озвучки и текста: {LANGS.get(language, language)}.

Верни JSON:
{{"title": "название ролика",
 "concept": "о чём новый ролик (2–3 предложения)",
 "changes": ["что изменено относительно референса"],
 "character_sheet": "English: consistent detailed description of the main character (appearance, clothing, hair) — repeat it in every scene prompt",
 "style": "English: lighting, palette, lens, camera style",
 "scenes": [{{"duration": секунды, "image_prompt": "English, full standalone prompt incl. character_sheet + style + action + environment",
             "motion_prompt": "English, what moves and how the camera moves", "voiceover": "фраза озвучки", "on_screen_text": "текст на экране или пусто"}}],
 "voiceover_full": "весь текст озвучки подряд, под {duration} с"}}
Сумма duration сцен = {duration}. Сцен 3–6."""
    job.progress(0.2, "Пишу новый оригинальный сценарий…")
    plan = ai.chat_json(PLAN_SYS, user, job=job, temperature=0.85)
    if not plan.get("scenes"): raise UserError("ИИ не составил сцены. Повторите.")
    return {"plan": plan}

def recreate_produce(job, plan, ratio="9:16", voice="ru-RU-SvetlanaNeural", with_voice=True, with_subs=True, seed=None, uid=None):
    scenes = [s for s in plan.get("scenes", []) if s.get("image_prompt")]
    if not scenes: raise UserError("В плане нет сцен.")
    seed = int(seed) if seed else random.randint(1, 2_000_000_000)
    vp = ai.need("video"); n = len(scenes); clips = []
    for i, s in enumerate(scenes):
        job.check(); job._p = 0.05 + 0.6 * i / n
        job.progress(job._p, f"Сцена {i + 1} из {n}: кадр…")
        img = gen.image(s["image_prompt"], ratio, seed + i, job=job)
        ia = job.asset(img["path"], kind="image", name=f"Сцена {i + 1}.jpg", meta={"prompt": s["image_prompt"], "provider": img["provider"], "seed": img["seed"]})
        dur = float(s.get("duration") or 3)
        if vp == "slideshow":
            clips.append({"asset": ia["id"], "duration": dur, "motion": ["zoom_in", "pan_right", "zoom_out", "pan_left"][i % 4]})
        else:
            job.progress(job._p + 0.3 / n, f"Сцена {i + 1} из {n}: оживляю кадр…")
            v = gen.video(s.get("image_prompt", "") + ". " + s.get("motion_prompt", ""), ratio, min(5, dur) if vp == "comfyui" else dur,
                          image_path=img["path"] if vp in ("comfyui", "fal", "hf_spaces") else None, seed=seed + i, job=job)
            va = job.asset(v["path"], kind="video", name=f"Сцена {i + 1}.mp4", meta={"provider": v["provider"], "ai_video": v.get("ai_video")})
            clips.append({"asset": va["id"], "start": 0, "end": dur})
    spec = {"format": ratio, "clips": clips, "audio": [], "subtitles": [], "texts": [], "clip_volume": 0.4 if vp != "slideshow" else 1.0}
    if with_voice and plan.get("voiceover_full"):
        job.progress(0.75, "Озвучиваю…")
        t = gen.tts(plan["voiceover_full"], voice, job=job)
        aa = job.asset(t["path"], kind="audio", name="Озвучка.mp3", meta={"text": plan["voiceover_full"], "voice": voice, "segments": t["segments"]})
        spec["audio"].append({"asset": aa["id"], "at": 0, "volume": 1.0})
        if with_subs: spec["subtitles"] = t["segments"]
    else:
        t0 = 0.0
        for s in scenes:
            d = float(s.get("duration") or 3)
            if s.get("on_screen_text"): spec["texts"].append({"start": t0, "end": t0 + d, "text": s["on_screen_text"], "position": "top"})
            t0 += d
    out = assemble(job, spec, uid, name=(plan.get("title") or "Новый ролик")[:80])
    out["spec"] = spec
    return out

# ---------------- монтаж ----------------
def resolver(uid):
    def r(aid):
        a = get_asset(uid, aid)
        if not a: raise UserError("Один из файлов на таймлайне был удалён. Уберите его и повторите экспорт.")
        return asset_file(a), a["kind"]
    return r

def assemble(job, spec, uid, name="Видео", hd=False):
    job.provider("ffmpeg на этом компьютере")
    path, info = media.render(spec, resolver(uid), job=job, hd=hd)
    a = job.asset(path, kind="video", name=f"{name}.mp4", meta={"render": info, "edit_spec": spec})
    return {"video": a, "info": info}

def auto_subtitles(job, asset_id, uid, language=""):
    a = get_asset(uid, asset_id)
    if not a or a["kind"] not in ("audio", "video"): raise UserError("Выберите видео или аудио для субтитров.")
    meta = jload(a.get("meta"))
    if meta.get("segments"):
        job.provider("тайминги озвучки"); return {"segments": meta["segments"], "provider": "тайминги озвучки", "approx": False}
    src = asset_file(a)
    audio = media.extract_audio(src) if a["kind"] == "video" else src
    job.progress(0.3, "Распознаю речь…")
    t = ai.transcribe(audio, language=language, job=job)
    if not t["segments"]: raise UserError("Речь не найдена — субтитры добавьте вручную.")
    return {"segments": t["segments"], "provider": t["provider"], "approx": t.get("approx", False)}

# ---------------- единый ассистент ----------------
ASSIST_SYS = """Ты — MaisonAI, ассистент видеостудии. Пользователь пишет задачи обычным языком. Ты понимаешь цель и
предлагаешь конкретные действия с инструментами студии. Отвечай кратко и по делу, на языке пользователя.
Не придумывай статистику и факты. Если чего-то не хватает (например, референсного видео) — попроси загрузить.

Доступные инструменты (tool) и их params:
- "script": {"topic", "duration" (сек), "language" (uk/ru/en/...), "style", "audience", "goal"} — сценарий, хук, озвучка, хештеги
- "image": {"prompt" (English), "ratio" ("9:16"|"1:1"|"16:9"|"4:5")} — картинка/кадр/обложка
- "video": {"prompt" (English), "ratio", "duration"} — видеоролик
- "voice": {"text", "voice" (например uk-UA-PolinaNeural, ru-RU-SvetlanaNeural, en-US-AriaNeural)} — озвучка
- "analyze": {} — TikTok Intelligence: анализ роликов/ссылок/скриншотов, Visual DNA и тренды (нужны файлы или ссылки от пользователя)
- "recreate": {"instructions"} — новый оригинальный ролик по проанализированному референсу или сохранённому стилю Visual DNA
- "montage": {"ratio"} — собрать ролик из материалов проекта (кадры/клипы + озвучка + субтитры)

Верни строго JSON: {"reply": "текст ответа пользователю (можно списки)", "ideas": ["если уместно: 2–4 идеи"],
"actions": [{"tool": "...", "title": "что сделает кнопка", "params": {...}}]}
Действий 0–4, в логичном порядке (сценарий → кадры → озвучка → монтаж). Не предлагай действие, если для него нет данных."""

def project_context(uid, project_id) -> str:
    try:
        with db() as c: ss = [r["name"] for r in c.execute("SELECT name FROM styles WHERE user_id=? ORDER BY updated DESC LIMIT 8", (uid,))]
    except Exception: ss = []
    styles = ("Сохранённые стили Visual DNA (TikTok Intelligence): " + ", ".join(ss) + "\n") if ss else ""
    return styles + _project_context(uid, project_id)

def _project_context(uid, project_id) -> str:
    if not project_id: return "Проект не выбран."
    with db() as c:
        p = c.execute("SELECT title, data FROM projects WHERE id=? AND user_id=?", (project_id, uid)).fetchone()
        assets = rows(c.execute("SELECT kind, name, meta FROM assets WHERE project_id=? AND user_id=? ORDER BY created DESC LIMIT 20", (project_id, uid)))
    if not p: return "Проект не найден."
    lines = [f"Проект: {p['title']}"]
    for a in assets:
        m = jload(a["meta"]); extra = m.get("title") or m.get("prompt", "")[:80] or m.get("text", "")[:80]
        lines.append(f"- {a['kind']}: {a['name']}" + (f" ({extra})" if extra else ""))
    return "\n".join(lines)

def assistant(uid, project_id, message, job=None):
    with db() as c:
        hist = rows(c.execute("SELECT role, content FROM chats WHERE user_id=? AND IFNULL(project_id,0)=? ORDER BY id DESC LIMIT 16", (uid, project_id or 0)))[::-1]
    msgs = [{"role": "system", "content": ASSIST_SYS + "\n\nКонтекст проекта:\n" + project_context(uid, project_id)}]
    msgs += [{"role": h["role"], "content": h["content"]} for h in hist]
    msgs.append({"role": "user", "content": message})
    out = ai.chat(msgs, json_mode=True, temperature=0.7, job=job)
    try: d = ai.parse_json(out)
    except ValueError: d = {"reply": out.strip(), "actions": []}
    if not isinstance(d, dict): d = {"reply": str(d), "actions": []}
    valid = {"script", "image", "video", "voice", "analyze", "recreate", "montage"}
    d["actions"] = [a for a in (d.get("actions") or []) if isinstance(a, dict) and a.get("tool") in valid][:4]
    d["ideas"] = [str(i) for i in (d.get("ideas") or [])][:4]
    d["reply"] = str(d.get("reply") or "Готово.")
    with db() as c:
        c.execute("INSERT INTO chats(user_id, project_id, role, content) VALUES(?,?,?,?)", (uid, project_id, "user", message))
        c.execute("INSERT INTO chats(user_id, project_id, role, content, meta) VALUES(?,?,?,?,?)",
                  (uid, project_id, "assistant", json.dumps({"reply": d["reply"], "ideas": d["ideas"]}, ensure_ascii=False), json.dumps({"actions": d["actions"]}, ensure_ascii=False)))
    return d

def automontage(job, uid, project_id, ratio="9:16", seconds_per_image=3.0):
    if not project_id: raise UserError("Откройте проект, чтобы собрать ролик из его материалов.")
    with db() as c:
        items = rows(c.execute("SELECT id, kind, name, meta FROM assets WHERE project_id=? AND user_id=? ORDER BY created", (project_id, uid)))
    visual = [a for a in items if a["kind"] in ("image", "video") and not jload(a["meta"]).get("reference_frame") and not jload(a["meta"]).get("render")]
    audio = [a for a in items if a["kind"] == "audio"]
    if not visual: raise UserError("В проекте пока нет картинок или клипов. Сгенерируйте кадры, затем соберите ролик.")
    clips = [{"asset": a["id"], "duration": seconds_per_image, "motion": ["zoom_in", "pan_right", "zoom_out", "pan_left"][i % 4]} if a["kind"] == "image"
             else {"asset": a["id"], "start": 0, "end": None} for i, a in enumerate(visual)]
    spec = {"format": ratio, "clips": clips, "audio": [], "subtitles": []}
    if audio:
        last = audio[-1]; m = jload(last["meta"])
        spec["audio"].append({"asset": last["id"], "at": 0, "volume": 1.0})
        if m.get("segments"): spec["subtitles"] = m["segments"]
        dur = media.probe(asset_file(get_asset(uid, last["id"])))["duration"]
        imgs = [c for c in clips if "duration" in c]
        if imgs and dur:
            vids = sum(media.probe(asset_file(get_asset(uid, c["asset"])))["duration"] for c in clips if "duration" not in c)
            per = max(1.5, (dur - vids) / len(imgs))
            for c in imgs: c["duration"] = round(per, 2)
    out = assemble(job, spec, uid, name="Монтаж проекта")
    out["spec"] = spec
    return out

# ---------------- много фото → полноценное видео ----------------
PHOTOS_JSON = """{"clips": [{"motion": "English, 25-45 words: how this exact photo comes alive — what the people/objects do, facial expression, hair/clothes/water/light movement, camera move. Keep the same person and scene.", "caption": "короткая подпись к кадру (2–5 слов) или пусто"}],
 "voiceover": "текст озвучки на весь ролик или пусто", "title": "название ролика"}"""

def photos_video(job, asset_ids, idea="", ratio="9:16", per_clip=4.0, ai_motion=True, voiceover="", auto_voice=False, voice="ru-RU-SvetlanaNeural",
                 language="ru", subtitles=True, captions=False, music_id=None, music_volume=0.35, transitions=True, uid=None):
    """Каждое фото оживает в отдельный клип (нейросеть Wan 2.2 или динамичный монтаж), затем клипы склеиваются переходами, добавляются озвучка, музыка и субтитры."""
    uid = uid or job.uid
    photos = []
    for aid in asset_ids[:20]:
        a = get_asset(uid, aid)
        if a and a["kind"] == "image": photos.append(asset_file(a))
    if not photos: raise UserError("Добавьте хотя бы одно фото.")
    per_clip = max(2.0, min(8.0, float(per_clip)))
    vp = P.chosen("video") or "slideshow"
    use_ai = ai_motion and vp in ("hf_spaces", "comfyui", "fal")
    plan = {"clips": [], "voiceover": "", "title": ""}
    want_voice = auto_voice and not voiceover.strip()
    if (use_ai or want_voice or captions) and P.chosen("vision"):
        job._p = 0.04; job.progress(0.04, f"ИИ изучает {len(photos)} фото и придумывает движение…")
        total = round(len(photos) * per_clip)
        text = (f"Это {len(photos)} фото для одного вертикального ролика (по порядку). Идея пользователя: {idea or 'на твой выбор, по содержанию фото'}.\n"
                f"Для КАЖДОГО фото опиши, как его естественно оживить в видео (motion, на английском). "
                + (f"Напиши текст озвучки на {LANGS.get(language, language)} языке примерно на {total} секунд (≈{int(total * 2.3)} слов), связывающий фото в историю. " if want_voice else "Озвучку не пиши (пустая строка). ")
                + "Не придумывай имена реальных людей. Верни строго JSON:\n" + PHOTOS_JSON)
        parts = [{"type": "text", "text": text}]
        for i, p in enumerate(photos[:16]): parts += [{"type": "text", "text": f"Фото {i + 1}:"}, ai.image_part(p)]
        try:
            plan = ai.parse_json(ai.chat([{"role": "user", "content": parts}], cap="vision", json_mode=True, job=job, temperature=0.7, max_tokens=4000))
        except Exception:
            plan = {"clips": [], "voiceover": "", "title": ""}
    clips_plan = plan.get("clips") or []
    W, H = media.FORMATS.get(ratio, media.FORMATS["9:16"])
    parts, durs, n_ai, notes = [], [], 0, []
    for i, p in enumerate(photos):
        job.check()
        job._p = 0.1 + 0.6 * i / len(photos)
        motion = (clips_plan[i].get("motion") if i < len(clips_plan) and isinstance(clips_plan[i], dict) else "") or \
                 f"{idea}. The scene comes alive with natural subtle motion of the people and environment, gentle cinematic camera movement"
        clip = None
        if use_ai:
            job.progress(job._p, f"Фото {i + 1} из {len(photos)}: нейросеть оживляет кадр…")
            try:
                r = gen.video(motion, ratio, min(5, per_clip), image_path=p, job=job)
                clip = media.video_clip(r["path"], 0, min(per_clip, float(r.get("seconds") or per_clip)), W, H, volume=0.0)
                n_ai += 1
            except UserError as e:
                notes.append(f"Фото {i + 1}: {e}")
                if "квота" in str(e).lower() or "квоту" in str(e).lower():
                    use_ai = False   # лимит кончился — остальные фото собираем монтажом
        if clip is None:
            job.progress(job._p, f"Фото {i + 1} из {len(photos)}: динамичный монтаж…")
            clip = media.image_clip(p, per_clip, W, H, media.MOTIONS[i % len(media.MOTIONS)])
        parts.append(clip); durs.append(media.probe(clip)["duration"] or per_clip)
    job.progress(0.74, "Склеиваю клипы с переходами…")
    merged = media.concat_xfade(parts, durs) if transitions and len(parts) > 1 else media.concat(parts)
    ma = job.asset(merged, kind="video", name="Клипы из фото.mp4", meta={"intermediate": True})
    spec = {"format": ratio, "clips": [{"asset": ma["id"], "start": 0, "end": None, "volume": 1.0}], "audio": [], "subtitles": [], "texts": [], "clip_volume": 1.0, "fade": True}
    vo = voiceover.strip() or ((plan.get("voiceover") or "").strip() if want_voice else "")
    if vo:
        job.progress(0.8, "Озвучиваю…")
        t = gen.tts(vo, voice, job=job)
        aa = job.asset(t["path"], kind="audio", name="Озвучка ролика.mp3", meta={"text": vo, "voice": voice, "segments": t["segments"]})
        spec["audio"].append({"asset": aa["id"], "at": 0.3, "volume": 1.0})
        if subtitles: spec["subtitles"] = [{"start": s["start"] + 0.3, "end": s["end"] + 0.3, "text": s["text"]} for s in t["segments"]]
    if music_id:
        mu = get_asset(uid, music_id)
        if mu and mu["kind"] in ("audio", "video"): spec["audio"].append({"asset": music_id, "at": 0, "volume": float(music_volume) if vo else 0.9})
    if captions and clips_plan:
        t0, step = 0.0, (sum(durs) - (0.45 * (len(durs) - 1) if transitions else 0)) / len(durs)
        for i, c in enumerate(clips_plan[:len(durs)]):
            if isinstance(c, dict) and c.get("caption"): spec["texts"].append({"start": round(t0 + 0.2, 2), "end": round(t0 + step - 0.2, 2), "text": c["caption"], "position": "top"})
            t0 += step
    out = assemble(job, spec, uid, name=(plan.get("title") or idea or "Видео из фото")[:80])
    out.update({"ai_clips": n_ai, "montage_clips": len(parts) - n_ai, "notes": notes, "spec": spec, "voiceover": vo})
    return out
