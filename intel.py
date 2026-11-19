"""TikTok Intelligence: пакетный анализ роликов и скриншотов, Visual DNA (профили стилей), тренды,
blueprint (план ролика) и память стилей/персонажей. Всё — реальные измерения кадров + мультимодальная модель ИИ."""
import json, random, time, uuid
from pathlib import Path
from typing import List, Optional
from fastapi import HTTPException, Request
from pydantic import BaseModel, Field
import ai, core, media, providers as P, tools
from core import UserError, asset_file, db, get_asset, jload, rows, submit

SCHEMA = """
CREATE TABLE IF NOT EXISTS intel_videos(id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, project_id INTEGER, kind TEXT DEFAULT 'video',
  asset_id TEXT, image_ids TEXT DEFAULT '[]', source_url TEXT, title TEXT, status TEXT DEFAULT 'queued', job_id TEXT, analysis TEXT, measured TEXT,
  vision TEXT, transcript TEXT, public_stats TEXT, keyframes TEXT DEFAULT '[]', thumb TEXT, mode TEXT, error TEXT, favorite INTEGER DEFAULT 0, created REAL);
CREATE TABLE IF NOT EXISTS styles(id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, name TEXT, dna TEXT, sources TEXT DEFAULT '[]', measured TEXT DEFAULT '{}',
  cover TEXT, favorite INTEGER DEFAULT 0, uses INTEGER DEFAULT 0, created REAL, updated REAL);
CREATE TABLE IF NOT EXISTS characters(id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, name TEXT, sheet TEXT DEFAULT '{}', image TEXT, source TEXT, created REAL);
CREATE TABLE IF NOT EXISTS blueprints(id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, project_id INTEGER, title TEXT, kind TEXT DEFAULT 'new',
  style_id TEXT, source_id TEXT, data TEXT DEFAULT '{}', status TEXT DEFAULT 'draft', result TEXT, created REAL, updated REAL);
CREATE TABLE IF NOT EXISTS trend_reports(id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, title TEXT, sources TEXT DEFAULT '[]', data TEXT, created REAL);
CREATE INDEX IF NOT EXISTS ix_iv ON intel_videos(user_id, created);
"""

def init():
    with db() as c: c.executescript(SCHEMA)

new_id = lambda: uuid.uuid4().hex[:14]

# ---------------- промпты ----------------
INTEL_JSON = """{"title": "короткое название концепции ролика",
 "concept": "общая концепция в 1–2 предложениях",
 "visual_style": "подробное описание визуального стиля", "aesthetic_tags": ["3–6 коротких тегов эстетики"],
 "characters": [{"role": "кто это", "appearance": "внешность без узнаваемых личных данных", "clothing": "одежда", "hair": "причёска", "accessories": "аксессуары", "expression": "мимика, поведение"}],
 "environment": "окружение и фон",
 "camera": {"shots": "крупность планов", "movement": "движение камеры", "angle": "ракурсы", "lens": "ощущение объектива"},
 "lighting": "освещение", "palette_words": "цветовая палитра словами",
 "editing": {"pace": "ритм монтажа", "transitions": "переходы", "patterns": "повторяющиеся приёмы монтажа"},
 "on_screen_text": {"subtitles": "есть ли субтитры и как оформлены", "overlays": ["тексты на экране, если читаются"]},
 "hook": {"time": "0–3 с", "visual": "что видит зритель", "why": "почему цепляет"},
 "script_structure": [{"time": "0–3 с", "beat": "что происходит по смыслу"}],
 "pace": "темп повествования", "voice": "стиль озвучки (голос, подача) или «без голоса»", "music": "музыка/звук",
 "blueprint": {"concept_name": "...", "visual_style": "...", "characters": "...", "script": "...", "hook": "...", "voiceover": "текст озвучки, если есть",
   "subtitles": ["строки субтитров"], "scenes": [{"time": "0–3 с", "frame": "описание кадра", "camera": "движение камеры", "lighting": "свет", "voiceover": "фраза", "subtitle": "текст на экране", "prompt": "English prompt to generate a similar ORIGINAL shot"}]}}"""

IMAGES_JSON = """{"title": "название набора референсов", "concept": "что объединяет эти кадры",
 "visual_style": "...", "aesthetic_tags": ["..."], "characters": [{"role": "...", "appearance": "...", "clothing": "...", "hair": "...", "accessories": "...", "expression": "..."}],
 "environment": "...", "camera": {"shots": "...", "movement": "по статичным кадрам не определяется — напиши «не видно на скриншотах»", "angle": "...", "lens": "..."},
 "lighting": "...", "palette_words": "...", "on_screen_text": {"subtitles": "...", "overlays": ["..."]}}"""

DNA_JSON = """{"name": "короткое название стиля", "summary": "подробное описание общего визуального стиля (4–6 предложений)",
 "character_style": "общий стиль персонажей", "visual_presentation": "особенности подачи", "lighting": "тип освещения",
 "palette_words": "палитра", "camera": "съёмка и движение камеры", "editing_patterns": ["повторяющиеся приёмы монтажа"],
 "atmosphere": "атмосфера и эстетика", "recurring_elements": ["повторяющиеся элементы"], "hook_patterns": ["как построены первые секунды"],
 "text_style": "субтитры и текст на экране", "voice_style": "озвучка", "do": ["что обязательно сохранять"], "avoid": ["чего избегать"],
 "prompt_style": "English: compact style descriptor (40-70 words) to append to image/video prompts",
 "negative_prompt": "English negative prompt"}"""

BLUEPRINT_JSON = """{"concept_name": "название новой концепции", "logline": "о чём ролик в одном предложении",
 "visual_style": "визуальный стиль (что сохранено от референса)", "changes": ["что изменено по запросу"],
 "character": {"name": "имя персонажа", "appearance": "...", "clothing": "...", "hair": "...", "accessories": "...", "sheet_en": "English consistent character description used in every prompt"},
 "hook": "первые 3 секунды", "script": "сценарий целиком", "voiceover": "весь текст озвучки",
 "subtitles": ["строки субтитров"],
 "scenes": [{"duration": секунды, "frame": "описание кадра", "camera": "движение камеры", "lighting": "свет", "voiceover": "фраза", "subtitle": "текст на экране или пусто",
   "prompt": "English full standalone prompt: character sheet + style + action + environment + light + camera"}]}"""

TRENDS_JSON = """{"summary": "общий вывод (3–4 предложения)",
 "visual_trends": [{"name": "...", "description": "...", "seen_in": ["номера роликов из списка, например 1, 3"]}],
 "formats": [{"name": "формат подачи", "description": "...", "seen_in": ["..."]}],
 "hooks": [{"pattern": "приём первых секунд", "seen_in": ["..."]}],
 "editing": [{"pattern": "приём монтажа", "seen_in": ["..."]}],
 "ideas": [{"title": "...", "concept": "...", "hook": "...", "format": "...", "why": "почему это может сработать (без цифр)"}]}"""

# ---------------- анализ одного ролика ----------------
def analyze_video(job, iid, asset_id=None, url=None, language="ru", focus=""):
    uid = job.uid
    def upd(**kw):
        with db() as c: c.execute("UPDATE intel_videos SET " + ",".join(f"{k}=?" for k in kw) + " WHERE id=?", (*[json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for v in kw.values()], iid))
    upd(status="running", job_id=job.id)
    try:
        try: video, name, public = tools.fetch_video(job, uid, asset_id, url)
        except UserError as e:
            if url: raise UserError(str(e) + " Альтернатива: скачайте ролик (в TikTok: «Поделиться» → «Сохранить видео») и загрузите файлом — анализ будет тем же.")
            raise
        a = None
        if not asset_id:
            with db() as c: r = c.execute("SELECT id FROM assets WHERE user_id=? AND path LIKE ? ORDER BY created DESC LIMIT 1", (uid, "%" + Path(video).name)).fetchone()
            a = r["id"] if r else None
        upd(title=Path(name).stem[:120], asset_id=asset_id or a, public_stats=public or {})
        job._p = 0.12; job.progress(0.12, "Измеряю: длительность, склейки, громкость…")
        m = tools.measure(video)
        job.progress(0.25, "Компьютерное зрение: ключевые кадры по склейкам, палитра, свет, движение…")
        kf = media.shot_keyframes(video, m["cuts"], m["duration"], 12)
        vision = {"palette": media.palette([p for _, p in kf]), "light": media.light_stats([p for _, p in kf]), "motion": media.motion_activity(video)}
        kf_assets = [job.asset(p, kind="image", name=f"{Path(name).stem[:40]} · {t} с.jpg", meta={"reference_frame": True, "intel": iid, "t": t})["id"] for t, p in kf]
        upd(measured={k: v for k, v in m.items()}, vision=vision, keyframes=kf_assets, thumb=kf_assets[0] if kf_assets else None)
        transcript = None
        if m["has_audio"] and P.chosen("stt"):
            job._p = 0.35; job.progress(0.35, "Распознаю речь…")
            try: transcript = ai.transcribe(media.extract_audio(video), job=job)
            except Exception: transcript = None
        if transcript and transcript.get("text"): m["words_per_min"] = round(len(transcript["text"].split()) / max(m["duration"], 1) * 60)
        facts = {k: v for k, v in m.items() if k not in ("loudness",)}
        facts.update({"palette_measured": vision["palette"], "light_measured": {k: v for k, v in vision["light"].items()}, "motion_measured": {k: v for k, v in vision["motion"].items() if k != "timeline"}})
        lang = tools.LANGS.get(language, "русском")
        prompt = (f"Ты — режиссёр-аналитик коротких видео. Разбери ролик для TikTok-студии. Пиши на {lang} языке (промпты сцен — на английском).\n"
                  f"РЕАЛЬНЫЕ ИЗМЕРЕНИЯ (программа посчитала сама, опирайся на них и не придумывай другие цифры): {json.dumps(facts, ensure_ascii=False)}\n"
                  + (f"Расшифровка речи: {transcript['text'][:4000]}\n" if transcript and transcript.get("text") else "")
                  + (f"Особое внимание: {focus}\n" if focus else "")
                  + "Не выдумывай просмотры, лайки и статистику. Внешность описывай обобщённо, без имён. Если чего-то не видно — так и напиши.\nВерни строго JSON:\n" + INTEL_JSON)
        job._p = 0.5
        if P.chosen("video_understanding"):
            job.progress(0.5, "Мультимодальная модель смотрит ролик целиком…"); mode = "video"
            res = ai.gemini_video_json(media.compress_for_ai(video), prompt, job=job)
        elif P.chosen("vision"):
            job.progress(0.5, f"Мультимодальная модель изучает {len(kf)} ключевых кадров…"); mode = "frames"
            parts = [{"type": "text", "text": prompt + f"\nНиже {len(kf)} ключевых кадров — середины планов между склейками."}]
            for t, p in kf: parts += [{"type": "text", "text": f"План на {t} с:"}, ai.image_part(p)]
            res = ai.parse_json(ai.chat([{"role": "user", "content": parts}], cap="vision", json_mode=True, job=job, temperature=0.35, max_tokens=6000))
        else:
            raise UserError("Для анализа картинки ролика подключите бесплатный ключ Gemini (Настройки → Провайдеры). Измерения сохранены, но без модели зрения ИИ не видит кадр.")
        if not isinstance(res, dict): raise UserError("Модель вернула пустой анализ. Повторите.")
        if m["duration"] > 90 and mode == "video": res["_note"] = "Модель смотрела первые 90 секунд ролика; измерения сделаны по всему ролику."
        upd(status="done", analysis=res, transcript=transcript or {}, mode=mode, measured=m, title=(res.get("title") or Path(name).stem)[:120], error=None)
        bp = res.get("blueprint")
        if isinstance(bp, dict) and bp.get("scenes"):
            save_blueprint(uid, job.project_id, bp.get("concept_name") or res.get("title") or "План ролика", bp, kind="reverse", source_id=iid)
        return {"intel_id": iid, "title": res.get("title"), "mode": mode}
    except core.Cancelled:
        upd(status="cancelled"); raise
    except Exception as e:
        upd(status="error", error=str(e) if isinstance(e, UserError) else core.friendly_error(e)); raise

def analyze_images(job, iid, image_ids, language="ru"):
    uid = job.uid
    def upd(**kw):
        with db() as c: c.execute("UPDATE intel_videos SET " + ",".join(f"{k}=?" for k in kw) + " WHERE id=?", (*[json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for v in kw.values()], iid))
    upd(status="running", job_id=job.id)
    try:
        paths = []
        for aid in image_ids[:12]:
            a = get_asset(uid, aid)
            if a and a["kind"] == "image": paths.append(asset_file(a))
        if not paths: raise UserError("Не найдено ни одной картинки.")
        job.progress(0.2, "Компьютерное зрение: палитра и свет…")
        vision = {"palette": media.palette(paths), "light": media.light_stats(paths)}
        upd(vision=vision, keyframes=image_ids[:12], thumb=image_ids[0])
        if not P.chosen("vision"): raise UserError("Для анализа скриншотов подключите модель зрения: бесплатный ключ Gemini (Настройки → Провайдеры).")
        job._p = 0.45; job.progress(0.45, f"Мультимодальная модель изучает {len(paths)} кадров…")
        prompt = (f"Ты — арт-директор. Это скриншоты/референсы из коротких видео. Опиши общий визуальный стиль на {tools.LANGS.get(language, 'русском')} языке.\n"
                  f"Реальные измерения палитры и света: {json.dumps(vision, ensure_ascii=False)}\nНе выдумывай то, чего не видно. Верни строго JSON:\n" + IMAGES_JSON)
        parts = [{"type": "text", "text": prompt}]
        for i, p in enumerate(paths): parts += [{"type": "text", "text": f"Кадр {i + 1}:"}, ai.image_part(p)]
        res = ai.parse_json(ai.chat([{"role": "user", "content": parts}], cap="vision", json_mode=True, job=job, temperature=0.35))
        upd(status="done", analysis=res, mode="images", title=(res.get("title") or "Набор скриншотов")[:120], error=None)
        return {"intel_id": iid, "title": res.get("title"), "mode": "images"}
    except core.Cancelled: upd(status="cancelled"); raise
    except Exception as e: upd(status="error", error=str(e) if isinstance(e, UserError) else core.friendly_error(e)); raise

def _intel_rows(uid, ids):
    with db() as c:
        rs = [dict(r) for r in c.execute(f"SELECT * FROM intel_videos WHERE user_id=? AND status='done' AND id IN ({','.join('?' * len(ids))})", (uid, *ids))]
    if not rs: raise UserError("Выберите хотя бы один успешно проанализированный ролик.")
    return rs

def _brief(r, i=None):
    a = jload(r["analysis"]); m = jload(r["measured"]); v = jload(r["vision"])
    keep = {k: a.get(k) for k in ("title", "concept", "visual_style", "aesthetic_tags", "characters", "environment", "camera", "lighting", "palette_words", "editing", "on_screen_text", "hook", "pace", "voice", "music")}
    keep["measured"] = {k: m.get(k) for k in ("duration", "cut_count", "cuts_per_10s", "avg_shot", "words_per_min", "vertical") if k in m}
    keep["vision_measured"] = {"palette": v.get("palette"), "light": v.get("light"), "motion": {k: x for k, x in (v.get("motion") or {}).items() if k != "timeline"}}
    if i is not None: keep["n"] = i
    return keep

# ---------------- Visual DNA ----------------
def build_style(job, ids, name="", language="ru"):
    rs = _intel_rows(job.uid, ids)
    job.progress(0.15, f"Свожу общую ДНК {len(rs)} референсов…")
    agg = aggregate([dict(r) for r in rs])
    prompt = (f"Ниже анализы {len(rs)} референсов (роликов и скриншотов). Сформируй их ОБЩУЮ Visual DNA — профиль стиля, который можно применять к будущим генерациям. "
              f"Пиши на {tools.LANGS.get(language, 'русском')} языке, prompt_style и negative_prompt — на английском. Выделяй именно повторяющееся, а не случайное. "
              f"Реальные усреднённые измерения: {json.dumps(agg, ensure_ascii=False)}\nАнализы: {json.dumps([_brief(r, i + 1) for i, r in enumerate(rs)], ensure_ascii=False)[:24000]}\n"
              "Верни строго JSON:\n" + DNA_JSON)
    dna = ai.chat_json("Ты — арт-директор и аналитик визуальных трендов.", prompt, job=job, temperature=0.5, max_tokens=4000)
    sid = new_id(); now = time.time()
    cover = next((r["thumb"] for r in rs if r["thumb"]), None)
    with db() as c:
        c.execute("INSERT INTO styles(id,user_id,name,dna,sources,measured,cover,created,updated) VALUES(?,?,?,?,?,?,?,?,?)",
                  (sid, job.uid, (name or dna.get("name") or "Мой стиль")[:80], json.dumps(dna, ensure_ascii=False), json.dumps([r["id"] for r in rs]), json.dumps(agg, ensure_ascii=False), cover, now, now))
    return {"style_id": sid, "name": name or dna.get("name")}

def aggregate(rs) -> dict:
    """Реальная статистика по набору референсов: средние измерения и общая палитра."""
    vids = [jload(r["measured"]) for r in rs if r["kind"] == "video" and r["measured"]]
    avg = lambda k: round(sum(x.get(k, 0) or 0 for x in vids) / len(vids), 2) if vids else None
    pal = {}
    for r in rs:
        for c in (jload(r["vision"]).get("palette") or []): pal[c["hex"]] = pal.get(c["hex"], 0) + c["share"]
    lights = [jload(r["vision"]).get("light") for r in rs if jload(r["vision"]).get("light")]
    motions = [jload(r["vision"]).get("motion", {}).get("motion") for r in rs if jload(r["vision"]).get("motion", {}).get("motion") is not None]
    la = lambda k: round(sum(l[k] for l in lights) / len(lights), 1) if lights else None
    return {"videos": len(vids), "images_sets": len(rs) - len(vids), "avg_duration": avg("duration"), "avg_cuts_per_10s": avg("cuts_per_10s"), "avg_shot": avg("avg_shot"),
            "palette": [{"hex": h, "share": round(s / max(1, len(rs)), 1)} for h, s in sorted(pal.items(), key=lambda x: -x[1])[:8]],
            "brightness": la("brightness"), "contrast": la("contrast"), "saturation": la("saturation"), "warmth": la("warmth"),
            "motion": round(sum(motions) / len(motions), 2) if motions else None}

# ---------------- тренды ----------------
def trends(job, ids, language="ru"):
    rs = _intel_rows(job.uid, ids)
    if len(rs) < 2: raise UserError("Для поиска трендов нужно минимум 2 проанализированных ролика.")
    job.progress(0.2, f"Ищу закономерности в {len(rs)} роликах…")
    stats = [{"n": i + 1, "title": r["title"], **{k: v for k, v in jload(r["public_stats"]).items() if k in ("view_count", "like_count", "comment_count", "upload_date", "uploader")}} for i, r in enumerate(rs)]
    prompt = (f"Ниже анализы {len(rs)} роликов, пронумерованных от 1. Найди повторяющиеся визуальные тренды, форматы подачи, приёмы хуков и монтажа, предложи оригинальные идеи. "
              f"Пиши на {tools.LANGS.get(language, 'русском')} языке. В seen_in указывай номера роликов, где тренд реально встречается. "
              "Не выдумывай просмотры и популярность — публичные цифры есть только там, где они переданы ниже; если их нет, не оценивай популярность.\n"
              f"Публичные данные со страниц роликов (только реально полученные): {json.dumps(stats, ensure_ascii=False)}\n"
              f"Анализы: {json.dumps([_brief(r, i + 1) for i, r in enumerate(rs)], ensure_ascii=False)[:24000]}\nВерни строго JSON:\n" + TRENDS_JSON)
    data = ai.chat_json("Ты — аналитик трендов TikTok.", prompt, job=job, temperature=0.6, max_tokens=4000)
    data["public_stats"] = stats; data["sources"] = [{"n": i + 1, "id": r["id"], "title": r["title"]} for i, r in enumerate(rs)]
    tid = new_id()
    with db() as c:
        c.execute("INSERT INTO trend_reports(id,user_id,title,sources,data,created) VALUES(?,?,?,?,?,?)",
                  (tid, job.uid, (data.get("summary") or "Тренды")[:80], json.dumps([r["id"] for r in rs]), json.dumps(data, ensure_ascii=False), time.time()))
    return {"report_id": tid}

# ---------------- blueprint: создание по референсу ----------------
KEEP = {"style": "общий визуальный стиль", "lighting": "освещение", "palette": "цветовую палитру", "camera": "движение камеры и крупность планов",
        "editing": "ритм и приёмы монтажа", "environment": "окружение", "character": "персонажа (внешность)", "clothing": "одежду", "hair": "причёску",
        "hook": "структуру хука", "text_style": "оформление субтитров", "voice": "стиль озвучки"}

def save_blueprint(uid, project_id, title, data, kind="new", style_id=None, source_id=None):
    bid = new_id(); now = time.time()
    with db() as c:
        c.execute("INSERT INTO blueprints(id,user_id,project_id,title,kind,style_id,source_id,data,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?)",
                  (bid, uid, project_id, str(title)[:120], kind, style_id, source_id, json.dumps(data, ensure_ascii=False), now, now))
    return bid

def make_blueprint(job, source_type, source_id, keep=None, instructions="", duration=15, language="ru", ratio="9:16", character_id=None):
    uid = job.uid; keep = keep or {}
    if source_type == "video":
        r = _intel_rows(uid, [source_id])[0]; ref = _brief(r); style_id = None
    elif source_type == "style":
        with db() as c: s = c.execute("SELECT * FROM styles WHERE id=? AND user_id=?", (source_id, uid)).fetchone()
        if not s: raise UserError("Стиль не найден.")
        ref = {"style_dna": jload(s["dna"]), "measured": jload(s["measured"])}; style_id = source_id
        with db() as c: c.execute("UPDATE styles SET uses=uses+1 WHERE id=?", (source_id,))
    else: raise UserError("Выберите ролик или стиль-референс.")
    char = None
    if character_id:
        with db() as c: ch = c.execute("SELECT * FROM characters WHERE id=? AND user_id=?", (character_id, uid)).fetchone()
        if ch: char = {"name": ch["name"], **jload(ch["sheet"])}
    kept = [v for k, v in KEEP.items() if keep.get(k)]
    changed = [v for k, v in KEEP.items() if k in keep and not keep.get(k)]
    job.progress(0.2, "Режиссёр ИИ пишет новый оригинальный ролик…")
    prompt = (f"Референс (результаты анализа): {json.dumps(ref, ensure_ascii=False)[:14000]}\n"
              f"СОХРАНИТЬ из референса: {', '.join(kept) if kept else 'общую эстетику'}.\nИЗМЕНИТЬ: {', '.join(changed) if changed else 'по пожеланиям'}.\n"
              f"Пожелания пользователя: {instructions or 'новый персонаж, новый сюжет, тот же визуальный стиль'}\n"
              + (f"Использовать сохранённого персонажа (не менять его внешность): {json.dumps(char, ensure_ascii=False)}\n" if char else "Придумай НОВОГО персонажа, не похожего на людей из референса.\n")
              + f"Длительность: {duration} с, формат {ratio}, язык текста и озвучки: {tools.LANGS.get(language, language)}.\n"
              "Создай ОРИГИНАЛЬНЫЙ ролик: нельзя копировать референс покадрово, нельзя использовать реальных людей, бренды и чужие тексты. "
              f"Сцен 3–6, сумма duration = {duration}. Каждый prompt — самодостаточный, на английском, с полным описанием персонажа и стиля.\nВерни строго JSON:\n" + BLUEPRINT_JSON)
    bp = ai.chat_json("Ты — режиссёр и сценарист коротких вертикальных видео.", prompt, job=job, temperature=0.85, max_tokens=5000)
    if not bp.get("scenes"): raise UserError("ИИ не составил сцены. Повторите.")
    bp["_ratio"] = ratio; bp["_language"] = language; bp["_keep"] = keep; bp["_instructions"] = instructions
    if style_id:
        bp["_style_prompt"] = ref["style_dna"].get("prompt_style", ""); bp["_negative"] = ref["style_dna"].get("negative_prompt", "")
    bid = save_blueprint(uid, job.project_id, bp.get("concept_name") or "Новый ролик", bp, "new", style_id, source_id)
    return {"blueprint_id": bid}

def blueprint_to_plan(bp: dict) -> dict:
    sp = bp.get("_style_prompt", "")
    scenes = []
    for s in bp.get("scenes", []):
        if not str(s.get("prompt", "")).strip(): continue
        try: d = max(1.0, min(15.0, float(s.get("duration") or 3)))
        except (TypeError, ValueError): d = 3.0
        scenes.append({"duration": d, "image_prompt": s["prompt"] + (", " + sp if sp else ""), "motion_prompt": s.get("camera", ""),
                       "voiceover": s.get("voiceover", ""), "on_screen_text": s.get("subtitle", "")})
    return {"title": bp.get("concept_name", "Новый ролик"), "scenes": scenes, "voiceover_full": bp.get("voiceover") or " ".join(s["voiceover"] for s in scenes if s["voiceover"])}

def produce(job, blueprint_id, voice="ru-RU-SvetlanaNeural", with_voice=True, with_subs=True, ratio=None):
    with db() as c: b = c.execute("SELECT * FROM blueprints WHERE id=? AND user_id=?", (blueprint_id, job.uid)).fetchone()
    if not b: raise UserError("План ролика не найден.")
    bp = jload(b["data"]); plan = blueprint_to_plan(bp)
    if not plan["scenes"]: raise UserError("В плане нет сцен с промптами.")
    with db() as c: c.execute("UPDATE blueprints SET status='producing', updated=? WHERE id=?", (time.time(), blueprint_id))
    try:
        out = tools.recreate_produce(job, plan, ratio or bp.get("_ratio", "9:16"), voice, with_voice, with_subs, uid=job.uid)
    except Exception:
        with db() as c: c.execute("UPDATE blueprints SET status='draft' WHERE id=?", (blueprint_id,))
        raise
    with db() as c: c.execute("UPDATE blueprints SET status='produced', result=?, updated=? WHERE id=?", (json.dumps({"video": out["video"], "info": out["info"]}, ensure_ascii=False), time.time(), blueprint_id))
    out["blueprint_id"] = blueprint_id
    return out

def style_suffix(uid, style_id) -> tuple:
    """Для генераторов: английский дескриптор стиля и негатив из сохранённого профиля."""
    if not style_id: return "", ""
    with db() as c: s = c.execute("SELECT dna FROM styles WHERE id=? AND user_id=?", (style_id, uid)).fetchone()
    if not s: return "", ""
    with db() as c: c.execute("UPDATE styles SET uses=uses+1 WHERE id=?", (style_id,))
    d = jload(s["dna"]); return d.get("prompt_style", ""), d.get("negative_prompt", "")

# ---------------- API ----------------
def install(app, A):
    U = A.U
    init()

    def own(table, iid, uid):
        with db() as c: r = c.execute(f"SELECT * FROM {table} WHERE id=? AND user_id=?", (iid, uid)).fetchone()
        if not r: raise HTTPException(404, "Не найдено")
        return dict(r)

    def pub_video(r):
        out = {k: r[k] for k in ("id", "kind", "asset_id", "source_url", "title", "status", "job_id", "mode", "error", "favorite", "created", "thumb", "project_id")}
        for k in ("analysis", "measured", "vision", "transcript", "public_stats"): out[k] = jload(r[k], None) if r[k] else None
        out["keyframes"] = jload(r["keyframes"], []); out["image_ids"] = jload(r["image_ids"], [])
        out["thumb_url"] = f"/files/{r['thumb']}" if r["thumb"] else None
        return out

    class Item(BaseModel): asset_id: Optional[str] = None; url: Optional[str] = None
    class AnalyzeIn(BaseModel):
        items: List[Item] = []; image_ids: List[str] = []; language: str = "ru"; focus: str = ""; project_id: Optional[int] = None

    @app.post("/api/intel/analyze")
    def analyze(b: AnalyzeIn, request: Request):
        u = U(request)
        if not b.items and not b.image_ids: raise HTTPException(400, "Добавьте видео, ссылки или скриншоты.")
        if len(b.items) > 10: raise HTTPException(400, "За один раз — до 10 роликов.")
        if b.project_id: A.own_project(u["id"], b.project_id)
        out = []
        for it in b.items:
            url = (it.url or "").strip()
            if not it.asset_id and not url: continue
            if it.asset_id:
                a = get_asset(u["id"], it.asset_id)
                if not a or a["kind"] != "video": raise HTTPException(400, "Один из файлов не является видео.")
            iid = new_id()
            with db() as c: c.execute("INSERT INTO intel_videos(id,user_id,project_id,kind,asset_id,source_url,title,created) VALUES(?,?,?,?,?,?,?,?)",
                                      (iid, u["id"], b.project_id, "video", it.asset_id, url or None, (a["name"] if it.asset_id else url)[:120], time.time()))
            jid = submit(u["id"], "intel", "Анализ: " + ((a["name"] if it.asset_id else url)[:70]), {"iid": iid, "asset_id": it.asset_id, "url": url or None, "language": b.language, "focus": b.focus},
                         lambda job, iid, asset_id, url, language, focus: analyze_video(job, iid, asset_id, url, language, focus), b.project_id)
            with db() as c: c.execute("UPDATE intel_videos SET job_id=? WHERE id=?", (jid, iid))
            out.append({"id": iid, "job": jid})
        if b.image_ids:
            for aid in b.image_ids:
                a = get_asset(u["id"], aid)
                if not a or a["kind"] != "image": raise HTTPException(400, "Один из файлов не является картинкой.")
            iid = new_id()
            with db() as c: c.execute("INSERT INTO intel_videos(id,user_id,project_id,kind,image_ids,title,created) VALUES(?,?,?,?,?,?,?)",
                                      (iid, u["id"], b.project_id, "image", json.dumps(b.image_ids[:12]), f"Скриншоты ({len(b.image_ids[:12])})", time.time()))
            jid = submit(u["id"], "intel", f"Анализ скриншотов ({len(b.image_ids[:12])})", {"iid": iid, "image_ids": b.image_ids[:12], "language": b.language},
                         lambda job, iid, image_ids, language: analyze_images(job, iid, image_ids, language), b.project_id)
            with db() as c: c.execute("UPDATE intel_videos SET job_id=? WHERE id=?", (jid, iid))
            out.append({"id": iid, "job": jid})
        return {"items": out}

    @app.get("/api/intel/videos")
    def videos(request: Request, status: str = ""):
        u = U(request); sql, args = "SELECT * FROM intel_videos WHERE user_id=?", [u["id"]]
        if status: sql += " AND status=?"; args.append(status)
        with db() as c: return [pub_video(dict(r)) for r in c.execute(sql + " ORDER BY created DESC LIMIT 300", args)]

    @app.get("/api/intel/videos/{iid}")
    def video(iid: str, request: Request): return pub_video(own("intel_videos", iid, U(request)["id"]))

    class Patch(BaseModel): title: Optional[str] = None; name: Optional[str] = None; favorite: Optional[bool] = None; data: Optional[dict] = None; dna: Optional[dict] = None; sheet: Optional[dict] = None; image: Optional[str] = None

    @app.patch("/api/intel/videos/{iid}")
    def video_patch(iid: str, b: Patch, request: Request):
        u = U(request); own("intel_videos", iid, u["id"])
        with db() as c:
            if b.title is not None: c.execute("UPDATE intel_videos SET title=? WHERE id=?", (b.title.strip()[:120], iid))
            if b.favorite is not None: c.execute("UPDATE intel_videos SET favorite=? WHERE id=?", (int(b.favorite), iid))
        return {"ok": True}

    @app.post("/api/intel/videos/{iid}/retry")
    def video_retry(iid: str, request: Request):
        u = U(request); r = own("intel_videos", iid, u["id"])
        if r["status"] in ("queued", "running"): raise HTTPException(400, "Анализ уже идёт.")
        with db() as c: c.execute("UPDATE intel_videos SET status='queued', error=NULL WHERE id=?", (iid,))
        if r["kind"] == "image":
            jid = submit(u["id"], "intel", "Повтор: " + (r["title"] or "скриншоты")[:70], {"iid": iid, "image_ids": jload(r["image_ids"], []), "language": "ru"},
                         lambda job, iid, image_ids, language: analyze_images(job, iid, image_ids, language), r["project_id"])
        else:   # ролик уже скачан — повторно не качаем
            jid = submit(u["id"], "intel", "Повтор: " + (r["title"] or "ролик")[:70], {"iid": iid, "asset_id": r["asset_id"], "url": None if r["asset_id"] else r["source_url"], "language": "ru", "focus": ""},
                         lambda job, iid, asset_id, url, language, focus: analyze_video(job, iid, asset_id, url, language, focus), r["project_id"])
        with db() as c: c.execute("UPDATE intel_videos SET job_id=? WHERE id=?", (jid, iid))
        return {"job": jid}

    @app.delete("/api/intel/videos/{iid}")
    def video_del(iid: str, request: Request):
        u = U(request); r = own("intel_videos", iid, u["id"])
        if r["status"] in ("queued", "running") and r["job_id"]: core.CANCEL.add(r["job_id"])
        with db() as c: c.execute("DELETE FROM intel_videos WHERE id=?", (iid,))
        return {"ok": True}

    # стили
    class StyleIn(BaseModel): ids: List[str]; name: str = ""; language: str = "ru"
    @app.post("/api/intel/styles")
    def style_new(b: StyleIn, request: Request):
        if not b.ids: raise HTTPException(400, "Выберите референсы для Visual DNA.")
        return A.start(request, "intel_style", "Visual DNA: " + (b.name or f"{len(b.ids)} референса"), {"ids": b.ids[:20], "name": b.name.strip()[:80], "language": b.language}, build_style)

    def pub_style(r):
        out = {k: r[k] for k in ("id", "name", "favorite", "uses", "created", "updated", "cover")}
        out["dna"] = jload(r["dna"]); out["measured"] = jload(r["measured"]); out["sources"] = jload(r["sources"], [])
        out["cover_url"] = f"/files/{r['cover']}" if r["cover"] else None
        return out

    @app.get("/api/intel/styles")
    def styles(request: Request):
        u = U(request)
        with db() as c: return [pub_style(dict(r)) for r in c.execute("SELECT * FROM styles WHERE user_id=? ORDER BY favorite DESC, updated DESC", (u["id"],))]

    @app.patch("/api/intel/styles/{sid}")
    def style_patch(sid: str, b: Patch, request: Request):
        u = U(request); s = own("styles", sid, u["id"])
        with db() as c:
            if b.name is not None: c.execute("UPDATE styles SET name=?, updated=? WHERE id=?", (b.name.strip()[:80] or s["name"], time.time(), sid))
            if b.favorite is not None: c.execute("UPDATE styles SET favorite=? WHERE id=?", (int(b.favorite), sid))
            if b.dna is not None: c.execute("UPDATE styles SET dna=?, updated=? WHERE id=?", (json.dumps({**jload(s["dna"]), **b.dna}, ensure_ascii=False), time.time(), sid))
        return pub_style(own("styles", sid, u["id"]))

    @app.delete("/api/intel/styles/{sid}")
    def style_del(sid: str, request: Request):
        u = U(request); own("styles", sid, u["id"])
        with db() as c: c.execute("DELETE FROM styles WHERE id=?", (sid,))
        return {"ok": True}

    # тренды
    class TrendIn(BaseModel): ids: List[str]; language: str = "ru"
    @app.post("/api/intel/trends")
    def trend_new(b: TrendIn, request: Request):
        if len(b.ids) < 2: raise HTTPException(400, "Выберите минимум 2 проанализированных ролика.")
        return A.start(request, "intel_trends", f"Тренды по {len(b.ids)} роликам", {"ids": b.ids[:30], "language": b.language}, trends)

    @app.get("/api/intel/trends")
    def trend_list(request: Request):
        u = U(request)
        with db() as c: rs = rows(c.execute("SELECT * FROM trend_reports WHERE user_id=? ORDER BY created DESC LIMIT 50", (u["id"],)))
        for r in rs: r["data"] = jload(r["data"]); r["sources"] = jload(r["sources"], [])
        return rs

    @app.delete("/api/intel/trends/{tid}")
    def trend_del(tid: str, request: Request):
        u = U(request); own("trend_reports", tid, u["id"])
        with db() as c: c.execute("DELETE FROM trend_reports WHERE id=?", (tid,))
        return {"ok": True}

    # blueprints
    class BpIn(BaseModel):
        source_type: str; source_id: str; keep: dict = {}; instructions: str = ""; duration: int = Field(15, ge=5, le=60)
        language: str = "ru"; ratio: str = "9:16"; character_id: Optional[str] = None; project_id: Optional[int] = None
    @app.post("/api/intel/blueprints")
    def bp_new(b: BpIn, request: Request):
        p = b.model_dump(); pid = p.pop("project_id")
        return A.start(request, "intel_blueprint", "План ролика по референсу", p, make_blueprint, pid)

    def pub_bp(r):
        out = {k: r[k] for k in ("id", "title", "kind", "style_id", "source_id", "status", "created", "updated", "project_id")}
        out["data"] = jload(r["data"]); out["result"] = jload(r["result"], None) if r["result"] else None
        return out

    @app.get("/api/intel/blueprints")
    def bp_list(request: Request, kind: str = ""):
        u = U(request); sql, args = "SELECT * FROM blueprints WHERE user_id=?", [u["id"]]
        if kind: sql += " AND kind=?"; args.append(kind)
        with db() as c: return [pub_bp(dict(r)) for r in c.execute(sql + " ORDER BY updated DESC LIMIT 200", args)]

    @app.get("/api/intel/blueprints/{bid}")
    def bp_get(bid: str, request: Request): return pub_bp(own("blueprints", bid, U(request)["id"]))

    @app.patch("/api/intel/blueprints/{bid}")
    def bp_patch(bid: str, b: Patch, request: Request):
        u = U(request); r = own("blueprints", bid, u["id"])
        with db() as c:
            if b.data is not None: c.execute("UPDATE blueprints SET data=?, title=?, updated=? WHERE id=?", (json.dumps(b.data, ensure_ascii=False)[:500000], (b.data.get("concept_name") or r["title"])[:120], time.time(), bid))
            if b.title is not None: c.execute("UPDATE blueprints SET title=? WHERE id=?", (b.title.strip()[:120], bid))
        return pub_bp(own("blueprints", bid, u["id"]))

    @app.delete("/api/intel/blueprints/{bid}")
    def bp_del(bid: str, request: Request):
        u = U(request); own("blueprints", bid, u["id"])
        with db() as c: c.execute("DELETE FROM blueprints WHERE id=?", (bid,))
        return {"ok": True}

    class ProduceIn(BaseModel): voice: str = "ru-RU-SvetlanaNeural"; with_voice: bool = True; with_subs: bool = True; ratio: Optional[str] = None; project_id: Optional[int] = None; quote: str = ""
    @app.post("/api/intel/blueprints/{bid}/produce")
    def bp_produce(bid: str, b: ProduceIn, request: Request):
        r = own("blueprints", bid, U(request)["id"])
        return A.start(request, "recreate", "Ролик: " + r["title"][:80], {"blueprint_id": bid, "voice": b.voice, "with_voice": b.with_voice, "with_subs": b.with_subs, "ratio": b.ratio}, produce, b.project_id,
                       paid=("intel_produce", {**b.model_dump(), "blueprint_id": bid}))

    # персонажи
    class CharIn(BaseModel): name: str; sheet: dict = {}; image: Optional[str] = None; source: str = ""
    @app.post("/api/intel/characters")
    def char_new(b: CharIn, request: Request):
        u = U(request)
        if b.image and not get_asset(u["id"], b.image): raise HTTPException(400, "Картинка не найдена")
        cid = new_id()
        with db() as c: c.execute("INSERT INTO characters(id,user_id,name,sheet,image,source,created) VALUES(?,?,?,?,?,?,?)",
                                  (cid, u["id"], b.name.strip()[:60] or "Персонаж", json.dumps(b.sheet, ensure_ascii=False)[:20000], b.image, b.source[:60], time.time()))
        return {"id": cid}

    @app.get("/api/intel/characters")
    def chars(request: Request):
        u = U(request)
        with db() as c: rs = rows(c.execute("SELECT * FROM characters WHERE user_id=? ORDER BY created DESC", (u["id"],)))
        for r in rs: r["sheet"] = jload(r["sheet"]); r["image_url"] = f"/files/{r['image']}" if r["image"] else None
        return rs

    @app.patch("/api/intel/characters/{cid}")
    def char_patch(cid: str, b: Patch, request: Request):
        u = U(request); r = own("characters", cid, u["id"])
        with db() as c:
            if b.name is not None: c.execute("UPDATE characters SET name=? WHERE id=?", (b.name.strip()[:60] or r["name"], cid))
            if b.sheet is not None: c.execute("UPDATE characters SET sheet=? WHERE id=?", (json.dumps(b.sheet, ensure_ascii=False), cid))
            img = getattr(b, "image", None)
            if img is not None:
                if img and not get_asset(u["id"], img): raise HTTPException(400, "Картинка не найдена")
                c.execute("UPDATE characters SET image=? WHERE id=?", (img or None, cid))
        return {"ok": True}

    @app.delete("/api/intel/characters/{cid}")
    def char_del(cid: str, request: Request):
        u = U(request); own("characters", cid, u["id"])
        with db() as c: c.execute("DELETE FROM characters WHERE id=?", (cid,))
        return {"ok": True}

    @app.get("/api/intel/memory")
    def memory(request: Request):
        u = U(request)
        with db() as c:
            q = lambda t, extra="": c.execute(f"SELECT COUNT(*) FROM {t} WHERE user_id=?{extra}", (u["id"],)).fetchone()[0]
            return {"videos": q("intel_videos", " AND status='done'"), "styles": q("styles"), "characters": q("characters"),
                    "blueprints": q("blueprints"), "trends": q("trend_reports"), "running": q("intel_videos", " AND status IN ('queued','running')")}
