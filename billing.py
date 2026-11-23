"""Контроль расходов: ни одного платного запроса без подтверждения.

Как это работает:
1. Перед запуском задачи сервер считает цену (estimators). Если хоть что-то платное — задача НЕ запускается,
   а браузер получает 409 {need_confirm, quote}: список позиций, итог, остаток бюджета.
2. Пользователь подтверждает → браузер повторяет запрос с quote. Квота одноразовая, живёт 15 минут,
   привязана к пользователю и к точным параметрам (fingerprint) — изменить параметры после подтверждения нельзя.
3. Задача получает «кошелёк» (allow) ровно на подтверждённую сумму. Каждый платный вызов (spend) проверяет
   остаток ДО отправки запроса и пишет строку в журнал. Превысить подтверждённую сумму невозможно.
4. Дневной и месячный бюджет проверяются при выдаче квоты. Повторный клик с теми же параметрами, пока задача
   идёт, не создаёт вторую оплату — возвращается уже запущенная задача.
5. Автоматический переход бывает только на бесплатный вариант, никогда на платный.
"""
import hashlib, json, secrets, threading, time
from datetime import datetime, timezone
import core, providers as P
from core import db, UserError

SCHEMA = """
CREATE TABLE IF NOT EXISTS usage(id INTEGER PRIMARY KEY, user_id INTEGER, job_id TEXT, provider TEXT, model TEXT, what TEXT,
  units REAL, unit TEXT, usd REAL, status TEXT, request_id TEXT, note TEXT, created REAL);
CREATE TABLE IF NOT EXISTS api_calls(day TEXT, provider TEXT, ok INTEGER DEFAULT 0, err INTEGER DEFAULT 0, PRIMARY KEY(day, provider));
CREATE INDEX IF NOT EXISTS ix_usage_user ON usage(user_id, created);
"""
DEFAULT_BUDGET = {"daily": 1.0, "monthly": 5.0, "max_job": 2.0}
QUOTES = {}
_lock = threading.Lock()
ESTIMATORS = {}

def install_db():
    with db() as c: c.executescript(SCHEMA)
    with db() as c:   # задачи, прерванные закрытием программы: честно помечаем
        c.execute("UPDATE usage SET status='unknown', note='Программа закрылась во время запроса — проверьте журнал fal.ai' WHERE status='running'")

def budget() -> dict:
    b = dict(DEFAULT_BUDGET); b.update(P.load_cfg().get("budget") or {}); return b

def _day(): return datetime.now(timezone.utc).strftime("%Y-%m-%d")

def spent(uid=None) -> dict:
    now = datetime.now(timezone.utc)
    d0 = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp(); m0 = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()
    q = "SELECT COALESCE(SUM(usd),0) FROM usage WHERE status IN ('charged','running','unknown') AND created>=?"
    with db() as c:   # бюджет общий на программу (платит владелец ключа)
        day = c.execute(q, (d0,)).fetchone()[0]; month = c.execute(q, (m0,)).fetchone()[0]
    return {"day": round(day, 4), "month": round(month, 4)}

def count(pid: str, ok: bool = True):
    """Счётчик запросов к провайдерам (и бесплатным, и платным)."""
    try:
        with db() as c:
            c.execute("INSERT INTO api_calls(day, provider, ok, err) VALUES(?,?,?,?) ON CONFLICT(day, provider) DO UPDATE SET ok=ok+?, err=err+?",
                      (_day(), pid, int(ok), int(not ok), int(ok), int(not ok)))
    except Exception: pass

# ---------------- оценка цены ----------------
def estimator(tool):
    def deco(fn): ESTIMATORS[tool] = fn; return fn
    return deco

def paid(cap: str) -> bool:
    pid = P.chosen(cap)
    return bool(pid) and P.PROVIDERS.get(pid, {}).get("cost") == "paid"

def video_cost(seconds) -> tuple:
    """(провайдер, модель, цена) для выбранного платного видео."""
    pid = P.chosen("video")
    if pid in ("veo", "runway"):
        import paidvideo as PV
        if pid == "veo": m = P.model_for("veo", "video", "veo-3.1-lite-generate-preview"); return "Google Veo", m, PV.veo_cost(m, seconds)
        m = P.model_for("runway", "video", "gen4_turbo"); return "Runway", m, PV.rw_cost(m, seconds)
    import fal
    ep = fal.model("video"); return "fal.ai", ep, fal.cost(ep, seconds=seconds)

def item_video(seconds, what="видео") -> dict:
    prov, ep, c = video_cost(seconds)
    return {"provider": prov, "model": ep, "label": c["label"], "what": what, "units": c["units"], "unit": c["unit"], "usd": c["usd"], "source": c["source"]}

def item_image(width=1024, height=1024, edit=False, what="картинка") -> dict:
    import fal
    ep = fal.model("image_edit" if edit else "image"); c = fal.cost(ep, width=width, height=height)
    return {"provider": "fal.ai", "model": ep, "label": c["label"], "what": what, "units": c["units"], "unit": c["unit"], "usd": c["usd"], "source": c["source"]}

def estimate(tool: str, body: dict, uid=None) -> list:
    fn = ESTIMATORS.get(tool)
    return fn(body, uid) if fn else []

def fingerprint(uid, tool, body) -> str:
    b = {k: v for k, v in (body or {}).items() if k not in ("quote", "project_id")}
    return hashlib.sha256(json.dumps([uid, tool, b], sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:32]

def make_quote(uid, tool, body, items) -> dict:
    total = round(sum(i["usd"] for i in items), 4)
    b, s = budget(), spent()
    left_day, left_month = round(b["daily"] - s["day"], 4), round(b["monthly"] - s["month"], 4)
    blocked = ""
    if total > b["max_job"] + 1e-9: blocked = f"Цена ${total:.2f} больше лимита на одну задачу (${b['max_job']:.2f}). Уменьшите задачу или поднимите лимит в Настройках → Расходы."
    elif total > left_day + 1e-9: blocked = f"Не хватает дневного бюджета: осталось ${max(0, left_day):.2f}, нужно ${total:.2f}. Лимит меняется в Настройках → Расходы."
    elif total > left_month + 1e-9: blocked = f"Не хватает месячного бюджета: осталось ${max(0, left_month):.2f}, нужно ${total:.2f}."
    qid = ""
    if not blocked:
        qid = secrets.token_urlsafe(16)
        with _lock:
            for k in [k for k, v in QUOTES.items() if v["exp"] < time.time()]: QUOTES.pop(k, None)
            QUOTES[qid] = {"uid": uid, "tool": tool, "fp": fingerprint(uid, tool, body), "usd": total, "exp": time.time() + 900}
    return {"need_confirm": True, "quote": qid, "items": items, "total": total, "currency": "USD", "blocked": blocked,
            "budget": {"daily": b["daily"], "monthly": b["monthly"], "spent_day": s["day"], "spent_month": s["month"]},
            "note": "Это примерная цена по тарифу провайдера. Деньги списывает сам сервис (fal.ai, Google или Runway) с вашего баланса там; MaisonAI ничего не берёт."}

class NeedConfirm(Exception):
    def __init__(self, detail): self.detail = detail

def authorize(uid, tool, body) -> dict | None:
    """None — платного нет. dict — подтверждённый кошелёк задачи. Иначе NeedConfirm с ценой."""
    items = estimate(tool, body, uid)
    if not items: return None
    qid = (body or {}).get("quote") or ""
    with _lock: q = QUOTES.get(qid)
    if not q or q["uid"] != uid or q["tool"] != tool or q["exp"] < time.time() or q["fp"] != fingerprint(uid, tool, body):
        raise NeedConfirm(make_quote(uid, tool, body, items))
    total = round(sum(i["usd"] for i in items), 4)
    if total > q["usd"] + 1e-6: raise NeedConfirm(make_quote(uid, tool, body, items))   # цена выросла — спросим снова
    with _lock: QUOTES.pop(qid, None)   # одноразовая
    return {"usd": q["usd"], "spent": 0.0, "fp": q["fp"]}

def spend(job, provider, model, what, units, unit, usd) -> int:
    """Вызывается ДО отправки платного запроса. Без подтверждённого кошелька — отказ."""
    allow = getattr(job, "allow", None) if job else None
    if not allow:
        raise UserError("Это платная модель. Запускайте её из раздела, где показывается цена и кнопка «Подтвердить» — без подтверждения MaisonAI ничего платного не делает.")
    if allow["spent"] + usd > allow["usd"] + 1e-6:
        raise UserError(f"Задача упёрлась в подтверждённую сумму ${allow['usd']:.2f}. Остальное не запущено и не оплачено.")
    allow["spent"] = round(allow["spent"] + usd, 4)
    with db() as c:
        cur = c.execute("INSERT INTO usage(user_id, job_id, provider, model, what, units, unit, usd, status, created) VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (job.uid, job.id, provider, model, what, units, unit, usd, "running", time.time()))
        return cur.lastrowid

def finish(uid_row: int, ok: bool, request_id: str = "", note: str = "", job=None, usd=0.0):
    with db() as c:
        c.execute("UPDATE usage SET status=?, request_id=?, note=? WHERE id=?", ("charged" if ok else "failed", request_id, note[:300], uid_row))
    if not ok and job is not None and getattr(job, "allow", None):   # неудача не тратит подтверждённую сумму
        job.allow["spent"] = round(max(0.0, job.allow["spent"] - usd), 4)

def paid_call(job, provider, model, what, units, unit, usd, fn):
    """Обёртка платного вызова: журнал + проверка кошелька + честный статус."""
    row = spend(job, provider, model, what, units, unit, usd)
    try:
        r = fn()
    except BaseException as e:
        finish(row, False, note=str(e)[:300], job=job, usd=usd); raise
    finish(row, True, (r or {}).get("request_id", "") if isinstance(r, dict) else "")
    return r

def report(limit=200) -> dict:
    with db() as c:
        rows = [dict(r) for r in c.execute("SELECT u.*, j.title AS job_title FROM usage u LEFT JOIN jobs j ON j.id=u.job_id ORDER BY u.id DESC LIMIT ?", (limit,))]
        calls = [dict(r) for r in c.execute("SELECT * FROM api_calls ORDER BY day DESC, provider LIMIT 300")]
        by_model = [dict(r) for r in c.execute("SELECT model, COUNT(*) n, ROUND(SUM(usd),4) usd FROM usage WHERE status='charged' GROUP BY model ORDER BY usd DESC")]
    return {"rows": rows, "calls": calls, "by_model": by_model, "spent": spent(), "budget": budget()}

def instrument():
    """Счётчик запросов: оборачиваем главные точки вызова ИИ (успех/ошибка по сервису)."""
    import ai, gen
    def wrap(mod, name, who):
        fn = getattr(mod, name)
        if getattr(fn, "_counted", False): return
        def w(*a, **k):
            try: pid = who(a, k) or name
            except Exception: pid = name
            try: r = fn(*a, **k)
            except Exception: count(pid, False); raise
            count(pid, True); return r
        w._counted = True; w.__wrapped__ = fn; setattr(mod, name, w)
    wrap(ai, "chat", lambda a, k: k.get("pid") or P.chosen(k.get("cap", a[1] if len(a) > 1 else "text")))
    wrap(gen, "image", lambda a, k: P.chosen("image_edit" if (k.get("refs") or (len(a) > 3 and a[3])) else "image"))
    wrap(gen, "video", lambda a, k: P.chosen("video"))
    wrap(gen, "tts", lambda a, k: "gemini" if str(k.get("voice") or (a[1] if len(a) > 1 else "")).startswith("gemini:") else P.chosen("tts"))
    wrap(ai, "transcribe", lambda a, k: P.chosen("stt"))

def install(app, A):
    from fastapi import HTTPException, Request
    from pydantic import BaseModel
    install_db(); instrument()

    @app.get("/api/costs")
    def costs(request: Request):
        A.U(request); r = report()
        if not A.can_admin(request): r["rows"] = [x for x in r["rows"] if x["user_id"] == request.state.user["id"]]
        r["can_edit"] = A.can_admin(request); return r

    class BudgetIn(BaseModel): daily: float; monthly: float; max_job: float
    @app.post("/api/costs/budget")
    def set_budget(b: BudgetIn, request: Request):
        A.U(request)
        if not A.can_admin(request): raise HTTPException(403, "Бюджет меняет только владелец.")
        if min(b.daily, b.monthly, b.max_job) < 0 or max(b.daily, b.monthly, b.max_job) > 1000: raise HTTPException(400, "Укажите суммы от 0 до 1000 $.")
        c = P.load_cfg(); c["budget"] = {"daily": round(b.daily, 2), "monthly": round(b.monthly, 2), "max_job": round(b.max_job, 2)}; P.save_cfg(c)
        return budget()

    class EstIn(BaseModel): tool: str; body: dict = {}
    @app.post("/api/costs/estimate")
    def est(b: EstIn, request: Request):
        u = A.U(request); items = estimate(b.tool, b.body, u["id"])
        return {"items": items, "total": round(sum(i["usd"] for i in items), 4), "paid": bool(items)}

    @app.get("/api/costs/prices")
    def prices(request: Request):
        A.U(request); import fal
        live = fal.live_prices()
        return {"models": [{"id": k, **v, "live": live.get(k)} for k, v in fal.MODELS.items()], "checked": fal.CHECKED,
                "selected": {k: fal.model(k) for k in ("video", "image", "image_edit")}}
