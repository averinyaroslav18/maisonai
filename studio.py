"""Thumbnail Studio (обложки), Content Planner (календарь), Project Library (единая библиотека с поиском, папками, избранным)."""
import json, random, time
from datetime import date, timedelta
from pathlib import Path
import ai, billing, gen, media, providers as P, tools
from core import db, rows, jload, get_asset, asset_file, asset_public, UserError, tmp_path, ASSETS

SIZES = {"9:16": (1080, 1920), "16:9": (1280, 720), "1:1": (1080, 1080), "4:5": (1080, 1350)}
STYLES = {"bold": "Крупно, белый с обводкой", "box": "Белый текст на чёрной плашке", "glow": "Неоновое свечение", "minimal": "Минимализм внизу", "split": "Две строки: акцент + подпись"}

def _font(px, bold=True):
    from PIL import ImageFont
    return ImageFont.truetype(str(ASSETS / "fonts" / ("Montserrat-ExtraBold.ttf" if bold else "Inter-Bold.ttf")), int(px))

def _wrap(d, text, f, maxw):
    words, lines, cur = str(text).split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if d.textlength(t, font=f) <= maxw or not cur: cur = t
        else: lines.append(cur); cur = w
    if cur: lines.append(cur)
    return lines

def compose(bg: Path, title: str, subtitle: str = "", ratio="9:16", style="bold", accent=(255, 255, 255)) -> Path:
    """Обложка: фон (обрезка по формату) + затемнение + типографика. Чистый Pillow — бесплатно, без сети."""
    from PIL import Image, ImageDraw, ImageFilter, ImageEnhance
    W, H = SIZES.get(ratio, SIZES["9:16"])
    im = Image.open(bg).convert("RGB")
    k = max(W / im.width, H / im.height); im = im.resize((int(im.width * k + 1), int(im.height * k + 1)), Image.LANCZOS)
    l, t = (im.width - W) // 2, (im.height - H) // 3; im = im.crop((l, t, l + W, t + H))
    im = ImageEnhance.Contrast(im).enhance(1.08)
    shade = Image.new("L", (1, 256))
    for y in range(256): shade.putpixel((0, y), int(max(0, (y - 90) / 166) ** 1.6 * 215))
    shade = shade.resize((W, H)); dark = Image.new("RGB", (W, H), (0, 0, 0)); im = Image.composite(dark, im, shade)
    d = ImageDraw.Draw(im, "RGBA"); title = (title or "").strip(); vertical = H > W
    base = min(W, H) * (0.13 if vertical else 0.11)
    if style == "minimal": base *= 0.55
    f = _font(base); lines = _wrap(d, title.upper() if style in ("bold", "glow", "box") else title, f, W * 0.86)
    while len(lines) > 4 and base > 30:
        base *= 0.88; f = _font(base); lines = _wrap(d, title.upper() if style in ("bold", "glow", "box") else title, f, W * 0.86)
    lh = int(base * 1.08); total = lh * len(lines)
    y0 = int(H * (0.62 if vertical else 0.55)) - total // 2 if style != "minimal" else int(H * 0.86) - total
    for i, line in enumerate(lines):
        tw = d.textlength(line, font=f); x = (W - tw) / 2 if style != "minimal" else W * 0.07; y = y0 + i * lh
        if style == "box":
            pad = base * 0.22; d.rounded_rectangle([x - pad, y - pad * 0.35, x + tw + pad, y + lh - pad * 0.1], radius=int(base * 0.14), fill=(0, 0, 0, 225))
            d.text((x, y), line, font=f, fill=(255, 255, 255))
        elif style == "glow":
            glow = Image.new("RGBA", (W, H), (0, 0, 0, 0)); gd = ImageDraw.Draw(glow); gd.text((x, y), line, font=f, fill=accent + (255,))
            glow = glow.filter(ImageFilter.GaussianBlur(base * 0.18)); im.paste(glow, (0, 0), glow); d = ImageDraw.Draw(im, "RGBA")
            d.text((x, y), line, font=f, fill=(255, 255, 255), stroke_width=max(1, int(base * 0.02)), stroke_fill=accent)
        elif style == "split" and i == 0:
            d.text((x, y), line, font=f, fill=accent, stroke_width=max(2, int(base * 0.07)), stroke_fill=(0, 0, 0))
        else:
            d.text((x, y), line, font=f, fill=(255, 255, 255), stroke_width=0 if style == "minimal" else max(2, int(base * 0.07)), stroke_fill=(0, 0, 0))
    if subtitle.strip():
        fs = _font(base * 0.36, bold=False); sl = _wrap(d, subtitle.strip(), fs, W * 0.8)[:2]
        yy = y0 + total + base * 0.25
        for j, line in enumerate(sl):
            tw = d.textlength(line, font=fs); x = (W - tw) / 2 if style != "minimal" else W * 0.07
            d.text((x, yy + j * base * 0.46), line, font=fs, fill=(235, 235, 235), stroke_width=max(1, int(base * 0.02)), stroke_fill=(0, 0, 0))
    out = tmp_path(".jpg"); im.save(out, "JPEG", quality=93); return out

def thumbnail(job, title, subtitle="", ratio="9:16", bg_asset=None, prompt=None, style="bold", uid=None, accent="#ffffff"):
    uid = uid or job.uid
    if bg_asset:
        a = get_asset(uid, bg_asset)
        if not a: raise UserError("Фон не найден.")
        if a["kind"] == "video": bg = media.frame_at(asset_file(a), 0.5)
        elif a["kind"] == "image": bg = asset_file(a)
        else: raise UserError("Фоном может быть картинка или видео.")
        prov = "ваш кадр"
    else:
        if not (prompt or "").strip(): raise UserError("Выберите фон или опишите картинку для фона.")
        job.progress(0.2, "Рисую фон обложки…")
        r = gen.image(f"{prompt}. Eye-catching social media cover, strong central subject, cinematic light, clean area for big title text, no text, no letters", ratio if ratio in gen.RATIOS else "9:16", job=job)
        bg = r["path"]; prov = r["provider"]
    job.progress(0.85, "Набираю заголовок…")
    try: rgb = tuple(int(accent.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    except Exception: rgb = (255, 255, 255)
    out = compose(bg, title or "", subtitle or "", ratio, style if style in STYLES else "bold", rgb)
    a = job.asset(out, kind="image", name=f"Обложка — {(title or 'MaisonAI')[:40]}.jpg", meta={"thumbnail": True, "title": title, "ratio": ratio, "style": style, "background": prov})
    return {"asset": a}

@billing.estimator("thumbnail")
def _e_thumb(b, uid):
    if b.get("bg_asset") or not billing.paid("image"): return []
    W, H = gen.RATIOS.get(b.get("ratio") if b.get("ratio") in gen.RATIOS else "9:16")
    return [billing.item_image(W, H, False, "фон обложки")]

# ---------------- Content Planner ----------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS planner(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, day TEXT NOT NULL, time TEXT DEFAULT '', title TEXT NOT NULL,
  platform TEXT DEFAULT 'tiktok', status TEXT DEFAULT 'idea', notes TEXT DEFAULT '', project_id INTEGER, created REAL);
CREATE INDEX IF NOT EXISTS ix_planner ON planner(user_id, day);
"""
STATUSES = ["idea", "script", "production", "ready", "published"]
PLATFORMS = ["tiktok", "reels", "shorts", "youtube", "other"]

def ideas(job, niche, count=7, start=None, every=1, platform="tiktok", language="ru", audience=""):
    job.progress(0.15, "ИИ придумывает идеи для контента…")
    d = ai.chat_json("Ты — контент-стратег коротких видео.",
                     f"Ниша/тема: {niche}\nАудитория: {audience or 'широкая'}\nПлатформа: {platform}\nКоличество идей: {count}\nЯзык: {tools.LANGS.get(language, language)}\n"
                     "Придумай разнообразные идеи коротких роликов (разные форматы: обучение, история, миф/правда, до/после, топ-3, ответ на вопрос). "
                     "Не выдумывай статистику и цифры просмотров. Верни JSON {\"ideas\": [{\"title\": \"...\", \"hook\": \"первая фраза\", \"format\": \"...\", \"notes\": \"кратко, что показать\"}]}",
                     job=job, temperature=0.95, max_tokens=3000)
    items = [x for x in d.get("ideas") or [] if isinstance(x, dict) and x.get("title")][:count]
    if not items: raise UserError("ИИ не придумал идеи. Повторите.")
    d0 = date.fromisoformat(start) if start else date.today()
    with db() as c:
        for i, x in enumerate(items):
            c.execute("INSERT INTO planner(user_id,day,title,platform,status,notes,created) VALUES(?,?,?,?,?,?,?)",
                      (job.uid, (d0 + timedelta(days=i * max(1, int(every)))).isoformat(), str(x["title"])[:200], platform, "idea",
                       (f"Хук: {x.get('hook', '')}\nФормат: {x.get('format', '')}\n{x.get('notes', '')}").strip()[:2000], time.time()))
    return {"added": len(items)}

# ---------------- Library ----------------
def install(app, A):
    from fastapi import HTTPException, Request
    from pydantic import BaseModel, Field
    from typing import Optional
    U = A.U
    with db() as c:
        c.executescript(SCHEMA)
        for t in ("assets", "projects"):
            cols = [r[1] for r in c.execute(f"PRAGMA table_info({t})")]
            if "folder" not in cols: c.execute(f"ALTER TABLE {t} ADD COLUMN folder TEXT DEFAULT ''")

    class ThumbIn(BaseModel):
        title: str = ""; subtitle: str = ""; ratio: str = "9:16"; bg_asset: Optional[str] = None; prompt: str = ""; style: str = "bold"; accent: str = "#ffffff"
        project_id: Optional[int] = None; quote: str = ""
    @app.post("/api/studio/thumbnail")
    def t_thumb(b: ThumbIn, request: Request):
        U(request)
        if b.ratio not in SIZES: raise HTTPException(400, "Неизвестный формат.")
        if not b.title.strip(): raise HTTPException(400, "Впишите заголовок обложки.")
        p = b.model_dump(); pid = p.pop("project_id"); p.pop("quote")
        def run(job, **kw): return thumbnail(job, **kw)
        return A.start(request, "thumbnail", "Обложка: " + b.title[:60], p, run, pid, paid=("thumbnail", b.model_dump()))

    @app.get("/api/studio/thumbnail/styles")
    def t_styles(request: Request): U(request); return {"styles": STYLES, "sizes": {k: list(v) for k, v in SIZES.items()}}

    # ----- planner -----
    @app.get("/api/planner")
    def pl_list(request: Request, month: str = ""):
        u = U(request); sql, args = "SELECT * FROM planner WHERE user_id=?", [u["id"]]
        if month: sql += " AND day LIKE ?"; args.append(month[:7] + "%")
        with db() as c: return rows(c.execute(sql + " ORDER BY day, time, id", args))

    class PlanIn(BaseModel):
        day: str; time: str = ""; title: str; platform: str = "tiktok"; status: str = "idea"; notes: str = ""; project_id: Optional[int] = None
    def _valid(b):
        try: date.fromisoformat(b.day)
        except ValueError: raise HTTPException(400, "Неверная дата.")
        if b.status not in STATUSES or b.platform not in PLATFORMS: raise HTTPException(400, "Неверный статус или платформа.")
        if not b.title.strip(): raise HTTPException(400, "Впишите название.")
    @app.post("/api/planner")
    def pl_new(b: PlanIn, request: Request):
        u = U(request); _valid(b)
        if b.project_id: A.own_project(u["id"], b.project_id)
        with db() as c:
            i = c.execute("INSERT INTO planner(user_id,day,time,title,platform,status,notes,project_id,created) VALUES(?,?,?,?,?,?,?,?,?)",
                          (u["id"], b.day, b.time[:5], b.title.strip()[:200], b.platform, b.status, b.notes[:4000], b.project_id, time.time())).lastrowid
        return {"id": i}
    @app.put("/api/planner/{iid}")
    def pl_edit(iid: int, b: PlanIn, request: Request):
        u = U(request); _valid(b)
        with db() as c:
            n = c.execute("UPDATE planner SET day=?, time=?, title=?, platform=?, status=?, notes=?, project_id=? WHERE id=? AND user_id=?",
                          (b.day, b.time[:5], b.title.strip()[:200], b.platform, b.status, b.notes[:4000], b.project_id, iid, u["id"])).rowcount
        if not n: raise HTTPException(404, "Не найдено")
        return {"ok": True}
    @app.delete("/api/planner/{iid}")
    def pl_del(iid: int, request: Request):
        u = U(request)
        with db() as c: c.execute("DELETE FROM planner WHERE id=? AND user_id=?", (iid, u["id"]))
        return {"ok": True}
    class IdeasIn(BaseModel):
        niche: str; count: int = Field(7, ge=1, le=30); start: Optional[str] = None; every: int = Field(1, ge=1, le=14); platform: str = "tiktok"; language: str = "ru"; audience: str = ""
    @app.post("/api/planner/ideas")
    def pl_ideas(b: IdeasIn, request: Request):
        if not b.niche.strip(): raise HTTPException(400, "Опишите тему или нишу.")
        if b.platform not in PLATFORMS: raise HTTPException(400, "Неверная платформа.")
        return A.start(request, "planner", f"Идеи: {b.niche[:60]}", b.model_dump(), ideas)

    # ----- library -----
    @app.get("/api/library")
    def lib(request: Request, kind: str = "", q: str = "", favorite: bool = False, folder: str = "", limit: int = 200):
        u = U(request); out = []; ql = q.strip().lower()
        if kind in ("", "image", "video", "audio"):
            sql, args = "SELECT * FROM assets WHERE user_id=?", [u["id"]]
            if kind: sql += " AND kind=?"; args.append(kind)
            else: sql += " AND kind IN ('image','video','audio')"
            if favorite: sql += " AND favorite=1"
            if folder: sql += " AND folder=?"; args.append(folder)
            with db() as c: rs = rows(c.execute(sql + " ORDER BY created DESC LIMIT ?", args + [2000 if ql else limit]))
            for r in rs:   # поиск в Python: SQLite LOWER не понимает кириллицу
                if ql and ql not in ((r["name"] or "") + " " + (r.get("meta") or "")).lower(): continue
                m = jload(r.get("meta"))
                if m.get("intermediate"): continue
                a = asset_public(r); a["folder"] = r.get("folder") or ""; a["type"] = "asset"; out.append(a)
        if kind in ("", "script") and not favorite:
            with db() as c: js = rows(c.execute("SELECT id, title, result, created FROM jobs WHERE user_id=? AND tool='script' AND status='done' ORDER BY created DESC LIMIT 100", (u["id"],)))
            for j in js:
                if ql and ql not in (j["title"] or "").lower(): continue
                if folder: continue
                res = jload(j["result"])
                out.append({"type": "script", "id": j["id"], "name": j["title"].replace("Сценарий: ", ""), "kind": "script", "created": j["created"], "data": res})
        if kind in ("", "character") and not favorite and not folder:
            with db() as c: cs = rows(c.execute("SELECT * FROM characters WHERE user_id=? ORDER BY created DESC", (u["id"],)))
            for ch in cs:
                if ql and ql not in (ch["name"] or "").lower(): continue
                img = get_asset(u["id"], ch["image"]) if ch.get("image") else None
                out.append({"type": "character", "id": ch["id"], "name": ch["name"], "kind": "character", "created": ch["created"], "url": f"/files/{img['id']}" if img else None, "sheet": jload(ch["sheet"])})
        if kind in ("", "project"):
            sql, args = "SELECT id, title, kind, favorite, folder, updated FROM projects WHERE user_id=?", [u["id"]]
            if favorite: sql += " AND favorite=1"
            if folder: sql += " AND folder=?"; args.append(folder)
            with db() as c: ps = rows(c.execute(sql + " ORDER BY updated DESC LIMIT 500", args))
            for p in ps:
                if ql and ql not in (p["title"] or "").lower(): continue
                out.append({"type": "project", "id": p["id"], "name": p["title"], "kind": "project", "project_kind": p["kind"], "favorite": p["favorite"], "folder": p["folder"] or "", "created": p["updated"]})
        return {"items": out[:limit]}

    @app.get("/api/library/folders")
    def folders(request: Request):
        u = U(request)
        with db() as c:
            f = [r[0] for r in c.execute("SELECT DISTINCT folder FROM assets WHERE user_id=? AND folder!='' UNION SELECT DISTINCT folder FROM projects WHERE user_id=? AND folder!=''", (u["id"], u["id"]))]
        return sorted(f)

    class MoveIn(BaseModel): type: str; id: str; folder: str = ""
    @app.post("/api/library/move")
    def move(b: MoveIn, request: Request):
        u = U(request); fol = b.folder.strip()[:60]
        with db() as c:
            if b.type == "asset": n = c.execute("UPDATE assets SET folder=? WHERE id=? AND user_id=?", (fol, b.id, u["id"])).rowcount
            elif b.type == "project": n = c.execute("UPDATE projects SET folder=? WHERE id=? AND user_id=?", (fol, int(b.id), u["id"])).rowcount
            else: raise HTTPException(400, "Папки есть у файлов и проектов.")
        if not n: raise HTTPException(404, "Не найдено")
        return {"ok": True}

    class FavIn(BaseModel): type: str; id: str; favorite: bool
    @app.post("/api/library/favorite")
    def fav(b: FavIn, request: Request):
        u = U(request)
        with db() as c:
            if b.type == "asset": n = c.execute("UPDATE assets SET favorite=? WHERE id=? AND user_id=?", (int(b.favorite), b.id, u["id"])).rowcount
            elif b.type == "project": n = c.execute("UPDATE projects SET favorite=? WHERE id=? AND user_id=?", (int(b.favorite), int(b.id), u["id"])).rowcount
            else: raise HTTPException(400, "В избранное можно добавить файл или проект.")
        if not n: raise HTTPException(404, "Не найдено")
        return {"ok": True}
