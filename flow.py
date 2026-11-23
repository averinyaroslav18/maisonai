"""Maison Flow — единый конвейер: идея → концепция → сценарий → раскадровка (AI Director) → сцены
(кадр + клип, каждую можно перегенерировать) → озвучка → субтитры → предпросмотр → экспорт MP4 → обложка.

Всё хранится в проекте (projects.data["flow"]), долгие шаги — фоновые задачи с реальным статусом.
Платные шаги (если для картинок/видео выбран fal.ai) проходят через billing: цена → подтверждение.
Если нейросетевое видео недоступно — сцена собирается бесплатно из кадра с движением камеры (FFmpeg).
"""
import json, random, threading, time, uuid
from pathlib import Path
import ai, billing, gen, media, providers as P, tools
from core import db, jload, get_asset, asset_file, UserError

_locks = {}
def _lock(pid):
    return _locks.setdefault(pid, threading.Lock())

CAMERA_TO_MOTION = {"push": "zoom_in", "dolly in": "zoom_in", "zoom in": "zoom_in", "pull": "zoom_out", "dolly out": "zoom_out", "zoom out": "zoom_out",
                    "pan left": "pan_left", "pan right": "pan_right", "truck left": "pan_left", "truck right": "pan_right", "tilt up": "tilt_up",
                    "crane up": "tilt_up", "tilt down": "tilt_down", "crane down": "tilt_down", "orbit": "drift", "handheld": "drift", "static": "punch"}

PLAN_JSON = """{
 "title": "название ролика",
 "concept": {"logline": "суть в 1 предложении", "hook": "что цепляет в первые 2 секунды", "audience": "для кого", "tone": "тон",
             "visual_style": "единый визуальный стиль ролика (по-английски, для генерации)", "palette": "палитра", "music_mood": "настроение музыки"},
 "character": "описание главного персонажа на английском (внешность, одежда, причёска) — одинаковое во всех сценах, либо пусто",
 "voiceover_full": "полный текст озвучки",
 "scenes": [{"duration": 4, "voiceover": "фраза этой сцены (часть voiceover_full)", "on_screen_text": "короткий текст на экране или пусто",
   "visual": "что в кадре — по-английски, самодостаточный промпт для генерации кадра",
   "action": "что движется в кадре — по-английски (для оживления)",
   "camera_angle": "ракурс", "camera_move": "движение камеры (push in / pull out / pan left / pan right / tilt up / tilt down / orbit / handheld / static)",
   "lens": "объектив/крупность", "lighting": "свет", "composition": "композиция", "transition": "переход к следующей сцене"}],
 "cover": {"title": "текст для обложки, 2–5 слов", "prompt": "промпт картинки обложки по-английски"},
 "caption": "подпись к публикации", "hashtags": ["..."]
}"""

def _project(uid, pid):
    with db() as c: r = c.execute("SELECT * FROM projects WHERE id=? AND user_id=?", (pid, uid)).fetchone()
    if not r: raise UserError("Проект не найден.")
    d = jload(r["data"]); return dict(r), d

def load(uid, pid) -> dict:
    _, d = _project(uid, pid)
    if "flow" not in d: raise UserError("Это не проект Maison Flow.")
    return d["flow"]

def save(uid, pid, flow: dict):
    with _lock(pid):
        _, d = _project(uid, pid); d["flow"] = flow
        with db() as c: c.execute("UPDATE projects SET data=?, title=?, updated=datetime('now') WHERE id=?", (json.dumps(d, ensure_ascii=False), (flow.get("title") or "Maison Flow")[:120], pid))

def update_scene(uid, pid, sid, **fields):
    with _lock(pid):
        _, d = _project(uid, pid); f = d["flow"]
        for s in f["scenes"]:
            if s["id"] == sid: s.update(fields)
        with db() as c: c.execute("UPDATE projects SET data=?, updated=datetime('now') WHERE id=?", (json.dumps(d, ensure_ascii=False), pid))
    return f

def patch(uid, pid, **fields):
    with _lock(pid):
        _, d = _project(uid, pid); d["flow"].update(fields)
        with db() as c: c.execute("UPDATE projects SET data=?, updated=datetime('now') WHERE id=?", (json.dumps(d, ensure_ascii=False), pid))
    return d["flow"]

def scene(flow, sid):
    for s in flow["scenes"]:
        if s["id"] == sid: return s
    raise UserError("Сцена не найдена — возможно, её удалили.")

def _norm_scenes(scenes, total):
    out = []
    for s in scenes:
        if not isinstance(s, dict): continue
        out.append({"id": uuid.uuid4().hex[:8], "duration": max(1.5, min(15.0, float(s.get("duration") or 3))),
                    **{k: str(s.get(k) or "")[:1500] for k in ("voiceover", "on_screen_text", "visual", "action", "camera_angle", "camera_move", "lens", "lighting", "composition", "transition")},
                    "frame": None, "clip": None, "clip_kind": "", "status": "draft", "provider": ""})
    if out and total:
        k = total / sum(s["duration"] for s in out)
        for s in out: s["duration"] = round(max(1.5, s["duration"] * k), 2)
    return out

# ---------------- 1. идея → концепция, сценарий, раскадровка ----------------
def plan(job, idea, own_script="", ratio="9:16", duration=30, style="", language="ru", voice="ru-RU-SvetlanaNeural", scenes=0,
         audience="", character_id=None, style_id=None, project_id=None):
    uid = job.uid
    char = None
    if character_id:
        with db() as c: ch = c.execute("SELECT * FROM characters WHERE id=? AND user_id=?", (character_id, uid)).fetchone()
        if ch: char = {"id": ch["id"], "name": ch["name"], "image": ch["image"], **jload(ch["sheet"])}
    dna = ""
    if style_id:
        import intel
        sp, _ = intel.style_suffix(uid, style_id); dna = sp
    n = int(scenes) if scenes else max(3, min(10, round(duration / 4)))
    job.progress(0.1, "Режиссёр ИИ придумывает концепцию и раскадровку…")
    prompt = (f"Идея ролика: {idea}\n" + (f"Готовый сценарий пользователя (используй ДОСЛОВНО как озвучку, разбей на сцены): {own_script}\n" if own_script.strip() else "")
              + f"Формат: {ratio}, длительность {duration} с, сцен: {n}, язык озвучки и текстов: {tools.LANGS.get(language, language)}.\n"
              + (f"Желаемый визуальный стиль: {style}\n" if style else "") + (f"Сохранённый стиль Visual DNA: {dna}\n" if dna else "")
              + (f"Аудитория: {audience}\n" if audience else "")
              + (f"Главный персонаж (не менять внешность): {json.dumps(char, ensure_ascii=False)}\n" if char else "")
              + "Ты — AI Director: для каждой сцены продумай ракурс, движение камеры, объектив, свет и композицию так, чтобы ролик удерживал внимание: "
                "сильный хук в первой сцене, смена крупности между сценами, нарастание к финалу, финальный призыв. "
                f"Сумма duration всех сцен = {duration}. Озвучка каждой сцены должна успевать прозвучать за её duration (≈2.5 слова в секунду). "
                "Промпты visual/action — на английском, самодостаточные, с единым стилем и одинаковым персонажем. Никаких реальных людей и брендов.\n"
                "Верни строго JSON:\n" + PLAN_JSON)
    d = ai.chat_json("Ты — креативный директор и режиссёр коротких видео для TikTok, Reels и Shorts.", prompt, job=job, temperature=0.85, max_tokens=6000)
    sc = _norm_scenes(d.get("scenes") or [], duration)
    if not sc: raise UserError("ИИ не составил сцены. Нажмите «Повторить».")
    flow = {"version": 1, "idea": idea, "title": (d.get("title") or idea)[:120], "concept": d.get("concept") or {}, "character": d.get("character") or "",
            "character_ref": (char or {}).get("image"), "character_id": character_id,
            "voiceover_full": d.get("voiceover_full") or " ".join(s["voiceover"] for s in sc), "scenes": sc,
            "cover": d.get("cover") or {}, "caption": d.get("caption") or "", "hashtags": d.get("hashtags") or [],
            "settings": {"ratio": ratio, "duration": duration, "style": style or (d.get("concept") or {}).get("visual_style", ""), "language": language, "voice": voice,
                         "emotion": "", "subtitles": True, "transitions": True, "music_id": None, "music_volume": 0.3, "style_id": style_id},
            "voice": None, "preview": None, "final": None, "thumbnail": None, "spec": None, "created": time.time()}
    with db() as c:
        if project_id:
            r = c.execute("SELECT data FROM projects WHERE id=? AND user_id=?", (project_id, uid)).fetchone()
            if not r: raise UserError("Проект не найден.")
            dd = jload(r["data"]); dd["flow"] = flow
            c.execute("UPDATE projects SET data=?, kind='flow', title=?, updated=datetime('now') WHERE id=?", (json.dumps(dd, ensure_ascii=False), flow["title"], project_id))
            pid = project_id
        else:
            pid = c.execute("INSERT INTO projects(user_id,title,kind,data) VALUES(?,?,?,?)", (uid, flow["title"], "flow", json.dumps({"flow": flow}, ensure_ascii=False))).lastrowid
    job.project_id = pid
    return {"project_id": pid, "title": flow["title"], "scenes": len(sc)}

# ---------------- 2. AI Director: доработать сцены ----------------
def director(job, project_id, scene_ids=None, note=""):
    f = load(job.uid, project_id)
    targets = [s for s in f["scenes"] if not scene_ids or s["id"] in scene_ids]
    job.progress(0.15, "AI Director продумывает ракурсы, свет и движение камеры…")
    brief = [{"id": s["id"], "voiceover": s["voiceover"], "visual": s["visual"], "duration": s["duration"]} for s in targets]
    d = ai.chat_json("Ты — оператор-постановщик и режиссёр коротких вертикальных видео.",
                     f"Концепция: {json.dumps(f.get('concept'), ensure_ascii=False)}\nСтиль: {f['settings'].get('style')}\nПерсонаж: {f.get('character')}\n"
                     f"Пожелание пользователя: {note or 'сделай динамичнее и кинематографичнее'}\nСцены: {json.dumps(brief, ensure_ascii=False)}\n"
                     "Для КАЖДОЙ сцены предложи: visual (улучшенный промпт кадра на английском с учётом ракурса и света), action, camera_angle, "
                     "camera_move (push in / pull out / pan left / pan right / tilt up / tilt down / orbit / handheld / static), lens, lighting, composition, transition. "
                     "Меняй крупность и ракурс между соседними сценами. Верни JSON {\"scenes\": [{\"id\": \"...\", ...}]}",
                     job=job, temperature=0.7, max_tokens=5000)
    by = {s.get("id"): s for s in d.get("scenes") or [] if isinstance(s, dict)}
    with _lock(project_id):
        _, dd = _project(job.uid, project_id); fl = dd["flow"]; n = 0
        for s in fl["scenes"]:
            u = by.get(s["id"])
            if not u: continue
            for k in ("visual", "action", "camera_angle", "camera_move", "lens", "lighting", "composition", "transition"):
                if u.get(k): s[k] = str(u[k])[:1500]
            s["frame"] = s["frame"]; n += 1
        with db() as c: c.execute("UPDATE projects SET data=?, updated=datetime('now') WHERE id=?", (json.dumps(dd, ensure_ascii=False), project_id))
    if not n: raise UserError("AI Director не вернул сцены. Повторите.")
    return {"updated": n}

# ---------------- 3. сцены: кадр и клип ----------------
def frame_prompt(f, s) -> str:
    parts = [s.get("visual"), f.get("character") and f"main character: {f['character']}", s.get("camera_angle") and f"camera angle: {s['camera_angle']}",
             s.get("lens") and f"lens: {s['lens']}", s.get("lighting") and f"lighting: {s['lighting']}", s.get("composition") and f"composition: {s['composition']}",
             f["settings"].get("style") and f"style: {f['settings']['style']}"]
    return ". ".join(x for x in parts if x)[:1800]

def make_frame(job, uid, project_id, sid):
    f = load(uid, project_id); s = scene(f, sid); st = f["settings"]
    update_scene(uid, project_id, sid, status="frame")
    refs = []
    if f.get("character_ref"):
        a = get_asset(uid, f["character_ref"])
        if a and a["kind"] == "image" and P.chosen("image_edit"): refs = [str(asset_file(a))]
    r = gen.image(frame_prompt(f, s), st["ratio"], s.get("seed") or random.randint(1, 2_000_000_000), refs=refs or None, job=job)
    a = job.asset(r["path"], kind="image", name=f"Сцена {f['scenes'].index(s) + 1} — кадр.jpg", meta={"prompt": frame_prompt(f, s), "provider": r["provider"], "flow_scene": sid})
    update_scene(uid, project_id, sid, frame=a["id"], clip=None, clip_kind="", status="frame_ready", provider=r["provider"])
    return a

def make_clip(job, uid, project_id, sid, mode="auto"):
    f = load(uid, project_id); s = scene(f, sid); st = f["settings"]
    if not s.get("frame") or not get_asset(uid, s["frame"]):
        job.progress(getattr(job, "_p", 0.1), "Сначала рисую кадр сцены…"); make_frame(job, uid, project_id, sid); f = load(uid, project_id); s = scene(f, sid)
    img = asset_file(get_asset(uid, s["frame"]))
    vp = P.chosen("video")
    want_ai = mode == "ai" or (mode == "auto" and vp in gen.AI_VIDEO)
    W, H = media.FORMATS.get(st["ratio"], media.FORMATS["9:16"])
    note, kind = "", "motion"
    clip = None
    if want_ai and vp in gen.AI_VIDEO:
        update_scene(uid, project_id, sid, status="clip")
        try:
            prompt = f"{s.get('action') or s.get('visual')}. Camera: {s.get('camera_move') or 'slow push in'}. {st.get('style', '')}"[:1500]
            r = gen.video(prompt, st["ratio"], min(10, s["duration"]), image_path=str(img), job=job, ai_only=True)
            clip = media.video_clip(r["path"], 0, s["duration"], W, H, volume=0.0)
            kind = "ai"; prov = r["provider"]; note = r.get("note", "")
        except UserError as e:
            note = f"Нейросетевое видео не получилось ({e}). Сцена собрана движением камеры — бесплатно."
    elif want_ai:
        note = "Для нейросетевого видео подключите Hugging Face, ComfyUI или fal.ai. Сцена собрана движением камеры — бесплатно."
    if clip is None:
        cm = (s.get("camera_move") or "").lower()
        motion = next((m for k, m in CAMERA_TO_MOTION.items() if k in cm), media.MOTIONS[f["scenes"].index(s) % len(media.MOTIONS)])
        clip = media.image_clip(img, s["duration"], W, H, motion); prov = "FFmpeg (движение камеры)"
    a = job.asset(clip, kind="video", name=f"Сцена {f['scenes'].index(s) + 1}.mp4", meta={"flow_scene": sid, "provider": prov, "ai_video": kind == "ai"})
    update_scene(uid, project_id, sid, clip=a["id"], clip_kind=kind, status="ready", provider=prov, note=note)
    return {"asset": a, "kind": kind, "note": note}

def build(job, project_id, what="all", mode="auto", only_missing=True):
    uid = job.uid; f = load(uid, project_id); sc = f["scenes"]; n = len(sc); notes = []
    for i, s in enumerate(sc):
        job.check(); job._p = 0.05 + 0.9 * i / n
        if what in ("frames", "all") and (not only_missing or not s.get("frame")):
            job.progress(job._p, f"Сцена {i + 1} из {n}: кадр…"); make_frame(job, uid, project_id, s["id"])
        if what in ("clips", "all") and (not only_missing or not s.get("clip")):
            job.progress(job._p + 0.4 / n, f"Сцена {i + 1} из {n}: клип…")
            r = make_clip(job, uid, project_id, s["id"], mode)
            if r["note"]: notes.append(f"Сцена {i + 1}: {r['note']}")
    return {"notes": notes}

# ---------------- 4. озвучка ----------------
def voice(job, project_id, voice=None, emotion=None, rate=0):
    uid = job.uid; f = load(uid, project_id); st = f["settings"]
    text = (f.get("voiceover_full") or "").strip() or " ".join(s["voiceover"] for s in f["scenes"]).strip()
    if not text: raise UserError("Нет текста озвучки. Впишите его в поле «Озвучка».")
    v = voice or st.get("voice") or "ru-RU-SvetlanaNeural"
    job.progress(0.2, "Озвучиваю…")
    t = gen.tts(text, v, rate, job=job, emotion=emotion if emotion is not None else st.get("emotion", ""))
    dur = media.probe(t["path"])["duration"]
    a = job.asset(t["path"], kind="audio", name="Озвучка.mp3", meta={"text": text, "voice": v, "segments": t["segments"], "duration": dur, "provider": t["provider"]})
    # длительности сцен подстраиваем под озвучку: пропорционально длине текста каждой сцены
    with _lock(project_id):
        _, dd = _project(uid, project_id); fl = dd["flow"]
        lens = [max(4, len(s["voiceover"])) for s in fl["scenes"]]; tot = sum(lens); target = dur + 0.6
        changed = []
        for s, L in zip(fl["scenes"], lens):
            nd = round(max(1.5, target * L / tot), 2)
            if abs(nd - s["duration"]) > 0.25 and s.get("clip_kind") == "motion": s["clip"] = None; changed.append(s["id"])   # движение камеры пересоберём бесплатно под новую длину
            s["duration"] = nd
        fl["voice"] = {"asset": a["id"], "segments": t["segments"], "duration": dur, "voice": v}; fl["settings"]["voice"] = v
        with db() as c: c.execute("UPDATE projects SET data=?, updated=datetime('now') WHERE id=?", (json.dumps(dd, ensure_ascii=False), project_id))
    return {"asset": a, "duration": dur, "rebuilt": len(changed)}

# ---------------- 5. сборка: предпросмотр и экспорт ----------------
def render(job, project_id, final=False, hd=False):
    uid = job.uid; f = load(uid, project_id); st = f["settings"]; sc = f["scenes"]
    W, H = media.FORMATS.get(st["ratio"], media.FORMATS["9:16"])
    parts, durs = [], []
    for i, s in enumerate(sc):
        job.check(); job.progress(0.05 + 0.4 * i / len(sc), f"Готовлю сцену {i + 1} из {len(sc)}…")
        ca = get_asset(uid, s["clip"]) if s.get("clip") else None
        if ca:
            p = media.video_clip(asset_file(ca), 0, s["duration"], W, H, volume=0.0)
        else:
            if not s.get("frame") or not get_asset(uid, s["frame"]):
                job._p = 0.05 + 0.4 * i / len(sc); make_frame(job, uid, project_id, s["id"]); f = load(uid, project_id); s = f["scenes"][i]
            cm = (s.get("camera_move") or "").lower()
            motion = next((m for k, m in CAMERA_TO_MOTION.items() if k in cm), media.MOTIONS[i % len(media.MOTIONS)])
            p = media.image_clip(asset_file(get_asset(uid, s["frame"])), s["duration"], W, H, motion)
        parts.append(p); durs.append(media.probe(p)["duration"] or s["duration"])
    job.progress(0.5, "Склеиваю сцены с переходами…")
    merged = media.concat_xfade(parts, durs) if st.get("transitions", True) and len(parts) > 1 else media.concat(parts)
    ma = job.asset(merged, kind="video", name="Сцены (склейка).mp4", meta={"intermediate": True, "flow": project_id})
    spec = {"format": st["ratio"], "clips": [{"asset": ma["id"], "start": 0, "end": None, "volume": 1.0}], "audio": [], "subtitles": [], "texts": [], "clip_volume": 1.0, "fade": True}
    if f.get("voice") and get_asset(uid, f["voice"]["asset"]):
        spec["audio"].append({"asset": f["voice"]["asset"], "at": 0.3, "volume": 1.0})
        if st.get("subtitles", True):
            spec["subtitles"] = [{**x, "start": x["start"] + 0.3, "end": x["end"] + 0.3} for x in f["voice"]["segments"]]
    t0, step = 0.0, 0.45 if st.get("transitions", True) and len(parts) > 1 else 0.0
    for s, d in zip(sc, durs):
        if s.get("on_screen_text"): spec["texts"].append({"start": round(t0 + 0.2, 2), "end": round(t0 + d - step, 2), "text": s["on_screen_text"], "position": "top", "style": "box"})
        t0 += d - step
    if st.get("music_id") and get_asset(uid, st["music_id"]):
        spec["audio"].append({"asset": st["music_id"], "at": 0, "volume": float(st.get("music_volume", 0.3))})
    out = tools.assemble(job, spec, uid, name=(f.get("title") or "Maison Flow")[:80] + ("" if final else " — предпросмотр"), hd=hd and final)
    key = "final" if final else "preview"
    patch(uid, project_id, **{key: out["video"]["id"], "spec": spec})
    return {**out, "spec": spec}

# ---------------- 6. обложка ----------------
def cover(job, project_id, title=None, use_frame=True):
    import studio
    uid = job.uid; f = load(uid, project_id); st = f["settings"]
    bg = None
    if use_frame and f["scenes"] and f["scenes"][0].get("frame"): bg = f["scenes"][0]["frame"]
    r = studio.thumbnail(job, title=title or (f.get("cover") or {}).get("title") or f.get("title"), ratio=st["ratio"], bg_asset=bg,
                         prompt=None if bg else ((f.get("cover") or {}).get("prompt") or frame_prompt(f, f["scenes"][0])), uid=uid)
    patch(uid, project_id, thumbnail=r["asset"]["id"])
    return r

# ---------------- оценка цены ----------------
def _w(uid, b):
    try: return load(uid, b["project_id"])
    except Exception: return None

@billing.estimator("flow_frame")
def _e_frame(b, uid):
    f = _w(uid, b)
    if not f or not billing.paid("image_edit" if f.get("character_ref") and P.chosen("image_edit") else "image"): return []
    W, H = gen.RATIOS.get(f["settings"]["ratio"], gen.RATIOS["9:16"]); return [billing.item_image(W, H, bool(f.get("character_ref")), "кадр сцены")]

@billing.estimator("flow_clip")
def _e_clip(b, uid):
    f = _w(uid, b)
    if not f: return []
    s = next((x for x in f["scenes"] if x["id"] == b.get("scene_id")), None)
    if not s: return []
    out = []
    if not s.get("frame"): out += _e_frame(b, uid)
    if b.get("mode", "auto") != "motion" and billing.paid("video"): out.append(billing.item_video(min(10, s["duration"]), "клип сцены"))
    return out

@billing.estimator("flow_build")
def _e_build(b, uid):
    f = _w(uid, b)
    if not f: return []
    out = []; W, H = gen.RATIOS.get(f["settings"]["ratio"], gen.RATIOS["9:16"])
    img_paid = billing.paid("image_edit" if f.get("character_ref") and P.chosen("image_edit") else "image")
    for i, s in enumerate(f["scenes"]):
        need_frame = b.get("what", "all") in ("frames", "all") and (not b.get("only_missing", True) or not s.get("frame"))
        need_clip = b.get("what", "all") in ("clips", "all") and (not b.get("only_missing", True) or not s.get("clip"))
        if (need_frame or (need_clip and not s.get("frame"))) and img_paid: out.append(billing.item_image(W, H, bool(f.get("character_ref")), f"сцена {i + 1}: кадр"))
        if need_clip and b.get("mode", "auto") != "motion" and billing.paid("video"): out.append(billing.item_video(min(10, s["duration"]), f"сцена {i + 1}: клип"))
    return out

@billing.estimator("flow_render")
def _e_render(b, uid):   # в сборке рисуются только недостающие кадры
    f = _w(uid, b)
    if not f: return []
    img_paid = billing.paid("image"); W, H = gen.RATIOS.get(f["settings"]["ratio"], gen.RATIOS["9:16"])
    return [billing.item_image(W, H, False, f"сцена {i + 1}: кадр") for i, s in enumerate(f["scenes"]) if not s.get("clip") and not s.get("frame") and img_paid]

# ---------------- API ----------------
def install(app, A):
    from fastapi import HTTPException, Request
    from pydantic import BaseModel, Field
    from typing import List, Optional
    U = A.U

    def view(uid, pid):
        f = load(uid, pid)
        def url(aid):
            a = get_asset(uid, aid) if aid else None
            return {"id": a["id"], "url": f"/files/{a['id']}", "kind": a["kind"], "name": a["name"]} if a else None
        out = json.loads(json.dumps(f))
        for s in out["scenes"]: s["frame_a"] = url(s.get("frame")); s["clip_a"] = url(s.get("clip"))
        for k in ("preview", "final", "thumbnail"): out[k + "_a"] = url(out.get(k))
        out["voice_a"] = url((out.get("voice") or {}).get("asset")); out["music_a"] = url(out["settings"].get("music_id"))
        out["project_id"] = pid; out["video_provider"] = P.chosen("video"); out["image_provider"] = P.chosen("image")
        out["video_paid"] = billing.paid("video"); out["image_paid"] = billing.paid("image")
        return out

    class StartIn(BaseModel):
        idea: str; own_script: str = ""; ratio: str = "9:16"; duration: int = Field(30, ge=6, le=180); style: str = ""; language: str = "ru"
        voice: str = "ru-RU-SvetlanaNeural"; scenes: int = Field(0, ge=0, le=12); audience: str = ""; character_id: Optional[str] = None; style_id: Optional[str] = None
        project_id: Optional[int] = None
    @app.post("/api/flow/start")
    def f_start(b: StartIn, request: Request):
        if not b.idea.strip() and not b.own_script.strip(): raise HTTPException(400, "Опишите идею ролика или вставьте свой сценарий.")
        if b.ratio not in media.FORMATS: raise HTTPException(400, "Неизвестный формат.")
        p = b.model_dump(); p["idea"] = p["idea"].strip() or p["own_script"][:120]
        return A.start(request, "flow_plan", "Maison Flow: " + p["idea"][:70], p, plan, None)

    @app.get("/api/flow")
    def f_list(request: Request):
        u = U(request)
        with db() as c: rs = c.execute("SELECT id, title, updated, data FROM projects WHERE user_id=? AND kind='flow' ORDER BY updated DESC", (u["id"],)).fetchall()
        out = []
        for r in rs:
            f = jload(r["data"]).get("flow") or {}
            first = next((s.get("frame") for s in f.get("scenes", []) if s.get("frame")), None)
            out.append({"id": r["id"], "title": r["title"], "updated": r["updated"], "scenes": len(f.get("scenes", [])), "ready": sum(1 for s in f.get("scenes", []) if s.get("clip")),
                        "final": bool(f.get("final")), "cover_url": f"/files/{f.get('thumbnail') or first}" if (f.get("thumbnail") or first) else None})
        return out

    @app.get("/api/flow/{pid}")
    def f_get(pid: int, request: Request): return view(U(request)["id"], pid)

    class SaveIn(BaseModel): flow: dict
    EDIT_SCENE = ("voiceover", "on_screen_text", "visual", "action", "camera_angle", "camera_move", "lens", "lighting", "composition", "transition", "duration")
    @app.put("/api/flow/{pid}")
    def f_save(pid: int, b: SaveIn, request: Request):
        u = U(request); f = load(u["id"], pid); nf = b.flow
        with _lock(pid):
            _, dd = _project(u["id"], pid); f = dd["flow"]
            for k in ("title", "voiceover_full", "character", "caption"):
                if k in nf: f[k] = str(nf[k])[:8000]
            if isinstance(nf.get("hashtags"), list): f["hashtags"] = [str(x)[:60] for x in nf["hashtags"][:30]]
            if isinstance(nf.get("cover"), dict): f["cover"] = {k: str(nf["cover"].get(k, ""))[:500] for k in ("title", "prompt")}
            if isinstance(nf.get("settings"), dict):
                for k, v in nf["settings"].items():
                    if k in ("ratio", "style", "language", "voice", "emotion", "music_id", "style_id") : f["settings"][k] = (str(v)[:500] if v is not None else None)
                    elif k in ("subtitles", "transitions"): f["settings"][k] = bool(v)
                    elif k == "music_volume": f["settings"][k] = max(0.0, min(1.5, float(v)))
                if f["settings"]["ratio"] not in media.FORMATS: f["settings"]["ratio"] = "9:16"
                if f["settings"].get("music_id") and not get_asset(u["id"], f["settings"]["music_id"]): f["settings"]["music_id"] = None
            if isinstance(nf.get("scenes"), list):   # порядок, правки, удаление и новые сцены
                old = {s["id"]: s for s in f["scenes"]}; new = []
                for s in nf["scenes"][:20]:
                    base = old.get(s.get("id")) or {**_norm_scenes([s], 0)[0]}
                    changed_visual = any(str(s.get(k, base.get(k))) != str(base.get(k)) for k in ("visual", "camera_angle", "lens", "lighting", "composition"))
                    for k in EDIT_SCENE:
                        if k in s: base[k] = max(1.5, min(15.0, float(s[k]))) if k == "duration" else str(s[k])[:1500]
                    if changed_visual: base["status"] = "changed"
                    new.append(base)
                if not new: raise HTTPException(400, "Нужна хотя бы одна сцена.")
                f["scenes"] = new
            with db() as c: c.execute("UPDATE projects SET data=?, title=?, updated=datetime('now') WHERE id=?", (json.dumps(dd, ensure_ascii=False), f["title"][:120], pid))
        return view(u["id"], pid)

    class DirIn(BaseModel): scene_ids: List[str] = []; note: str = ""
    @app.post("/api/flow/{pid}/director")
    def f_dir(pid: int, b: DirIn, request: Request):
        load(U(request)["id"], pid)
        return A.start(request, "flow_director", "AI Director", {"project_id": pid, "scene_ids": b.scene_ids, "note": b.note}, director, pid)

    class QIn(BaseModel): quote: str = ""; mode: str = "auto"
    @app.post("/api/flow/{pid}/scenes/{sid}/frame")
    def f_frame(pid: int, sid: str, b: QIn, request: Request):
        u = U(request); scene(load(u["id"], pid), sid)
        def run(job, sid): return {"asset": make_frame(job, job.uid, pid, sid)}
        return A.start(request, "flow_frame", "Кадр сцены", {"sid": sid}, run, pid, paid=("flow_frame", {"project_id": pid, "scene_id": sid, "quote": b.quote}))

    @app.post("/api/flow/{pid}/scenes/{sid}/clip")
    def f_clip(pid: int, sid: str, b: QIn, request: Request):
        u = U(request); scene(load(u["id"], pid), sid)
        if b.mode not in ("auto", "ai", "motion"): raise HTTPException(400, "Неизвестный режим.")
        def run(job, sid, mode): return make_clip(job, job.uid, pid, sid, mode)
        return A.start(request, "flow_clip", "Клип сцены", {"sid": sid, "mode": b.mode}, run, pid,
                       paid=("flow_clip", {"project_id": pid, "scene_id": sid, "mode": b.mode, "quote": b.quote}))

    class BuildIn(BaseModel): what: str = "all"; mode: str = "auto"; only_missing: bool = True; quote: str = ""
    @app.post("/api/flow/{pid}/build")
    def f_build(pid: int, b: BuildIn, request: Request):
        load(U(request)["id"], pid)
        if b.what not in ("frames", "clips", "all") or b.mode not in ("auto", "ai", "motion"): raise HTTPException(400, "Неверные параметры.")
        return A.start(request, "flow_build", "Генерация сцен", {"project_id": pid, "what": b.what, "mode": b.mode, "only_missing": b.only_missing}, build, pid,
                       paid=("flow_build", {"project_id": pid, **b.model_dump()}))

    class VoiceIn(BaseModel): voice: Optional[str] = None; emotion: Optional[str] = None; rate: int = Field(0, ge=-50, le=100)
    @app.post("/api/flow/{pid}/voice")
    def f_voice(pid: int, b: VoiceIn, request: Request):
        load(U(request)["id"], pid)
        return A.start(request, "flow_voice", "Озвучка ролика", {"project_id": pid, **b.model_dump()}, voice, pid)

    class RenderIn(BaseModel): final: bool = False; hd: bool = False; quote: str = ""
    @app.post("/api/flow/{pid}/render")
    def f_render(pid: int, b: RenderIn, request: Request):
        load(U(request)["id"], pid)
        return A.start(request, "flow_render", "Экспорт MP4" if b.final else "Предпросмотр", {"project_id": pid, "final": b.final, "hd": b.hd}, render, pid,
                       paid=("flow_render", {"project_id": pid, **b.model_dump()}))

    class CoverIn(BaseModel): title: Optional[str] = None; use_frame: bool = True
    @app.post("/api/flow/{pid}/cover")
    def f_cover(pid: int, b: CoverIn, request: Request):
        load(U(request)["id"], pid)
        return A.start(request, "thumbnail", "Обложка", {"project_id": pid, "title": b.title, "use_frame": b.use_frame}, cover, pid,
                       paid=("flow_cover", {"project_id": pid, **b.model_dump()}))

@billing.estimator("flow_cover")
def _e_cover(b, uid):
    f = _w(uid, b)
    if not f or (b.get("use_frame", True) and f["scenes"] and f["scenes"][0].get("frame")) or not billing.paid("image"): return []
    W, H = gen.RATIOS.get(f["settings"]["ratio"], gen.RATIOS["9:16"]); return [billing.item_image(W, H, False, "фон обложки")]
