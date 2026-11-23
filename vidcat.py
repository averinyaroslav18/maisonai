"""«Все модели видео»: один список всех способов генерации — бесплатных и платных — с ценой за 5-секундный ролик.

Бесплатные: Hugging Face (Wan 2.2), ComfyUI на своём компьютере, монтаж из картинок.
Платные: fal.ai (живой каталог всех видеомоделей с живыми ценами), Google Veo 3.1, Runway.
Пользователь сам выбирает; платное всегда запускается только после показа цены и подтверждения.
"""
import providers as P

FREE = [
    {"pid": "agnes", "model": "", "label": "Agnes Video 2.5 Flash (Agnes AI)", "price5": 0, "kind": "картинка → видео, текст → видео",
     "note": "Настоящее ИИ-видео 720P, 4–12 с — персонажи двигаются. Сейчас бесплатно по акции, лимит ≈ 1–2 ролика в минуту. Ключ бесплатный: platform.agnes-ai.com."},
    {"pid": "hf_spaces", "model": "", "label": "Wan 2.2 через Hugging Face", "price5": 0, "kind": "картинка → видео, текст → видео",
     "note": "Настоящее нейросетевое видео до 5 с. Бесплатно ≈ 5–8 клипов в день на аккаунт Hugging Face (лимит видеокарты)."},
    {"pid": "comfyui", "model": "", "label": "Wan 2.2 5B на вашем компьютере (ComfyUI)", "price5": 0, "kind": "картинка → видео, текст → видео",
     "note": "Без лимитов, но нужна видеокарта NVIDIA от 8 ГБ. На MacBook и слабых ПК не подойдёт."},
    {"pid": "slideshow", "model": "", "label": "Монтаж из ИИ-картинок", "price5": 0, "kind": "текст → видео",
     "note": "Всегда бесплатно и без лимитов: ИИ рисует кадры, программа анимирует камеру. Персонажи не двигаются."},
]

def catalog(force=False) -> dict:
    import fal, paidvideo as PV
    use = P.load_cfg()["use"].get("video", "")
    cur = {"pid": use, "model": P.model_for(use, "video", "") if use in ("fal", "veo", "runway") else ""}
    if use == "fal": cur["model"] = fal.model("video")
    paid = []
    for mid, m in PV.VEO.items():
        paid.append({"pid": "veo", "model": mid, "label": "Google " + m["label"], "price5": round(m["price"] * 6, 3), "per_sec": m["price"],
                     "kind": "картинка → видео, текст → видео", "note": "Со звуком. Ролик 4, 6 или 8 с (5 с округляется до 6).", "src": "Google"})
    for mid, m in PV.RUNWAY.items():
        paid.append({"pid": "runway", "model": mid, "label": m["label"], "price5": round(m["credits"] / 100 * 5, 3), "per_sec": m["credits"] / 100,
                     "kind": "картинка → видео" + (", текст → видео" if m["t2v"] else ""), "note": "Ролик 5 или 10 с.", "src": "Runway"})
    for m in fal.catalog(force):
        p5 = fal.per5(m)
        paid.append({"pid": "fal", "model": m["id"], "label": m.get("label") or m["id"], "price5": p5, "price": m.get("price"), "unit": m.get("unit"),
                     "kind": "текст → видео" if "text-to-video" in (m.get("category") or "") else "картинка → видео", "note": m.get("desc", ""), "src": "fal.ai"})
    paid.sort(key=lambda x: (x["price5"] is None, x["price5"] or 0))
    conf = {pid: P.configured(pid) for pid in ("agnes", "hf_spaces", "comfyui", "slideshow", "fal", "veo", "runway")}
    signup = {pid: P.PROVIDERS[pid].get("signup", "") for pid in conf}
    return {"free": FREE, "paid": paid, "current": cur, "configured": conf, "signup": signup, "fal_models": sum(1 for x in paid if x["pid"] == "fal")}

def choose(pid: str, model: str = "") -> dict:
    if pid not in ("agnes", "hf_spaces", "comfyui", "slideshow", "fal", "veo", "runway"): raise ValueError("Неизвестный способ")
    c = P.load_cfg(); c["use"]["video"] = pid
    if pid in ("fal", "veo", "runway") and model: c["models"][f"{pid}:video"] = model
    P.save_cfg(c)
    return {"ok": True, "configured": P.configured(pid)}

def install(app, A):
    from fastapi import HTTPException, Request
    from pydantic import BaseModel

    @app.get("/api/video/catalog")
    def video_catalog(request: Request, refresh: bool = False):
        A.U(request); r = catalog(refresh); r["can_edit"] = A.can_admin(request); return r

    class ChooseIn(BaseModel): pid: str; model: str = ""
    @app.post("/api/video/choose")
    def video_choose(b: ChooseIn, request: Request):
        A.U(request)
        if not A.can_admin(request): raise HTTPException(403, "Модель видео выбирает только владелец.")
        try: return choose(b.pid, b.model.strip()[:200])
        except ValueError as e: raise HTTPException(400, str(e))
