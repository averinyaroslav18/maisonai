"""Провайдеры ИИ и их настройки. Ключи хранятся только на сервере (Windows DPAPI), в браузер не отдаются."""
import ctypes, json, os, sys, threading
from pathlib import Path
from core import DATA

# Каждый провайдер честно помечен: бесплатно ли, нужен ли ключ, какие реальные ограничения.
PROVIDERS = {
    # ---------- текст и анализ ----------
    "pollinations_free": {"label": "Pollinations без ключа", "caps": ["text", "image"], "needs": [],
        "cost": "free", "limits": "Бесплатно, без регистрации. Текст — не чаще 1 запроса в 30 сек, картинки — 1 в 45 сек, до 768×768. Работает «как получится», без гарантий.",
        "signup": "https://pollinations.ai"},
    "gemini": {"label": "Google Gemini", "caps": ["text", "vision", "video_understanding", "stt", "tts"], "needs": ["key"],
        "cost": "free_quota", "limits": "Бесплатный ключ в Google AI Studio. Лимиты запросов в минуту/день зависят от модели и аккаунта — точные цифры показаны в AI Studio. Понимает видео и картинки.",
        "signup": "https://aistudio.google.com/apikey", "base": "https://generativelanguage.googleapis.com/v1beta/openai"},
    "groq": {"label": "Groq", "caps": ["text", "stt"], "needs": ["key"],
        "cost": "free_quota", "limits": "Бесплатный ключ. Лимиты на модель (например, ~30 запросов/мин, ~1000/день для больших моделей; Whisper — до 2 часов аудио в час). Точные цифры: console.groq.com/settings/limits.",
        "signup": "https://console.groq.com/keys", "base": "https://api.groq.com/openai/v1"},
    "openrouter": {"label": "OpenRouter (только бесплатные модели)", "caps": ["text", "vision"], "needs": ["key"],
        "cost": "free_quota", "limits": "Бесплатный ключ. Используются только модели с пометкой «:free»; у них дневной лимит запросов, который задаёт OpenRouter.",
        "signup": "https://openrouter.ai/keys", "base": "https://openrouter.ai/api/v1"},
    "cloudflare": {"label": "Cloudflare Workers AI", "caps": ["text", "vision", "image", "image_edit", "tts", "stt"], "needs": ["key", "account"],
        "cost": "free_quota", "limits": "Бесплатно 10 000 «нейронов» в день: примерно 170 картинок FLUX schnell 1024×1024 или ~80 правок картинок. После лимита — ошибка до следующего дня (платить не нужно, на бесплатном плане списаний нет).",
        "signup": "https://dash.cloudflare.com/profile/api-tokens"},
    "ollama": {"label": "Ollama (на этом компьютере)", "caps": ["text", "vision"], "needs": [],
        "cost": "local", "limits": "Полностью бесплатно и без лимитов, но работает на вашем компьютере: нужна установленная Ollama и скачанная модель.",
        "signup": "https://ollama.com/download", "base": "http://localhost:11434/v1"},
    "custom": {"label": "Свой OpenAI-совместимый сервер", "caps": ["text", "vision"], "needs": ["base"],
        "cost": "unknown", "limits": "Любой совместимый сервер (LM Studio, vLLM и т.д.). Стоимость зависит от сервера.", "signup": ""},
    # ---------- медиа ----------
    "edge_tts": {"label": "Microsoft Edge голоса", "caps": ["tts"], "needs": [],
        "cost": "free", "limits": "Бесплатно, без ключа, более 300 голосов (в т.ч. украинские и русские). Неофициальный способ доступа: Microsoft может изменить его в любой момент.",
        "signup": ""},
    "pollinations": {"label": "Pollinations с ключом", "caps": ["text"], "needs": ["key"],
        "cost": "paid_credits", "limits": "Списывает «Pollen» (1 Pollen ≈ 1 $). Бесплатно дают только разовые Pollen за задания в кабинете. Цена каждой модели показывается перед запуском. Включайте, только если согласны тратить кредиты.",
        "signup": "https://enter.pollinations.ai"},
    "hf_spaces": {"label": "Hugging Face · Wan 2.2 (оживление фото)", "caps": ["video"], "needs": ["key"],
        "cost": "free_quota", "limits": "Настоящее нейросетевое видео: персонажи и предметы двигаются. Бесплатный аккаунт Hugging Face даёт 5 минут видеокарты в день — это примерно 5–8 клипов по 5 секунд. Лимит обновляется через 24 часа. Если очередь занята, придётся подождать.",
        "signup": "https://huggingface.co/settings/tokens"},
    "agnes": {"label": "Agnes AI · видео (сейчас бесплатно)", "caps": ["video"], "needs": ["key"],
        "cost": "free_quota", "limits": "Настоящее ИИ-видео: персонажи и предметы двигаются. Agnes Video 2.5 Flash — 720P, 4–12 секунд, вертикальное 9:16. По официальной странице Agnes модель сейчас бесплатна по акции (обычная цена $0.025/сек — акция может закончиться, тогда программа скажет об этом и ничего не спишет). Лимит бесплатного плана ≈ 1–2 ролика в минуту. Ключ бесплатно: platform.agnes-ai.com.",
        "signup": "https://platform.agnes-ai.com/"},
    "fal": {"label": "fal.ai (платно, с подтверждением цены)", "caps": ["image", "image_edit", "video"], "needs": ["key"],
        "cost": "paid", "limits": "Платный сервис с предоплатой: одна учётная запись — сотни видеомоделей (Kling, Veo, Seedance, MiniMax/Hailuo, Wan, LTX, Luma, Pika и др.) с живыми ценами, от ≈ $0.015/сек. Выбор модели: Видео → «Все модели видео»; картинки FLUX schnell ≈ $0.003/Мпикс, правка Nano Banana ≈ $0.04. Перед каждым запуском MaisonAI показывает цену и ждёт подтверждения; действуют дневной и месячный бюджет (Настройки → Расходы).",
        "signup": "https://fal.ai/dashboard/keys"},
    "veo": {"label": "Google Veo 3.1 (платно, с подтверждением цены)", "caps": ["video"], "needs": ["key"],
        "cost": "paid", "limits": "Видео от Google со звуком: Veo 3.1 Lite ≈ $0.05/сек (720p), Fast ≈ $0.10/сек, Standard ≈ $0.40/сек; ролик 4, 6 или 8 секунд. Нужен ключ Google AI Studio с включённой оплатой (подойдёт и ключ Gemini). Перед каждым запуском — цена и подтверждение.",
        "signup": "https://aistudio.google.com/apikey"},
    "runway": {"label": "Runway (платно, с подтверждением цены)", "caps": ["video"], "needs": ["key"],
        "cost": "paid", "limits": "Runway API, оплата кредитами ($0.01 за кредит, минимум $10): Gen-4 Turbo ≈ $0.05/сек, Kling 3.0 Standard ≈ $0.09/сек, Gen-4.5 ≈ $0.12/сек; ролик 5 или 10 секунд. Перед каждым запуском — цена и подтверждение.",
        "signup": "https://dev.runwayml.com/"},
    "comfyui": {"label": "ComfyUI (на этом компьютере)", "caps": ["image", "image_edit", "video"], "needs": [],
        "cost": "local", "limits": "Бесплатно и без лимитов, но нужна видеокарта NVIDIA. Видео Wan 2.2 5B: ~8 ГБ видеопамяти и более (с выгрузкой в ОЗУ), 5-секундный ролик — от нескольких минут.",
        "signup": "https://www.comfy.org/download", "base": "http://127.0.0.1:8188"},
    "slideshow": {"label": "Монтаж из картинок (ffmpeg)", "caps": ["video"], "needs": [],
        "cost": "free", "limits": "Всегда бесплатно: ИИ рисует кадры, программа сама анимирует их (плавный наезд камеры), добавляет голос и субтитры. Это не нейросетевое видео — движений персонажей не будет.",
        "signup": ""},
}

CAP_LABELS = {"text": "Текст и сценарии", "vision": "Анализ картинок", "video_understanding": "Анализ видео",
              "image": "Генерация картинок", "image_edit": "Редактирование картинок", "tts": "Озвучка",
              "stt": "Распознавание речи (субтитры)", "video": "Генерация видео"}

DEFAULTS = {"text": "pollinations_free", "vision": "", "image": "pollinations_free", "image_edit": "",
            "tts": "edge_tts", "stt": "", "video": "slideshow"}

_lock = threading.Lock()

# ---------- безопасное хранение ключей: Windows DPAPI (привязано к учётной записи Windows) ----------
class _Blob(ctypes.Structure): _fields_ = [("cbData", ctypes.c_ulong), ("pbData", ctypes.POINTER(ctypes.c_char))]

def _dpapi(data: bytes, protect: bool) -> bytes:
    crypt32, k32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    k32.LocalFree.argtypes = [ctypes.c_void_p]
    buf = ctypes.create_string_buffer(data, len(data))
    inb = _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))); out = _Blob()
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    if not fn(ctypes.byref(inb), None, None, None, None, 0, ctypes.byref(out)): raise OSError("DPAPI")
    try: return ctypes.string_at(out.pbData, out.cbData)
    finally: k32.LocalFree(out.pbData)

def _keys_path(): return DATA / "keys.dat"

ENV_KEYS = {"gemini": {"key": "GEMINI_API_KEY"}, "groq": {"key": "GROQ_API_KEY"}, "openrouter": {"key": "OPENROUTER_API_KEY"},
            "cloudflare": {"key": "CLOUDFLARE_API_TOKEN", "account": "CLOUDFLARE_ACCOUNT_ID"}, "pollinations": {"key": "POLLINATIONS_API_KEY"},
            "hf_spaces": {"key": "HF_TOKEN"}, "fal": {"key": "FAL_KEY"}, "veo": {"key": "VEO_API_KEY"}, "runway": {"key": "RUNWAYML_API_SECRET"}, "agnes": {"key": "AGNES_API_KEY"}}

def _fernet():
    """На сервере (не Windows) ключи шифруются; ключ шифрования лежит отдельно от папки данных."""
    from cryptography.fernet import Fernet
    if os.environ.get("MAISONAI_SECRET"): return Fernet(os.environ["MAISONAI_SECRET"].strip().encode())   # Hugging Face: ключ в секретах Space
    kp = Path(os.environ.get("MAISONAI_KEYFILE") or (DATA.parent / "maisonai_secret.key"))
    if not kp.exists():
        kp.write_bytes(Fernet.generate_key())
        try: os.chmod(kp, 0o600)
        except Exception: pass
    return Fernet(kp.read_bytes().strip())

def load_secrets() -> dict:
    p = _keys_path(); d = {}
    if p.exists():
        raw = p.read_bytes()
        try:
            if raw[:1] == b"D": d = json.loads(_dpapi(raw[1:], False).decode())
            elif raw[:1] == b"F": d = json.loads(_fernet().decrypt(raw[1:]).decode())
            else: d = json.loads(raw[1:].decode())
        except Exception: d = {}
    for pid, fields in ENV_KEYS.items():   # ключи из переменных окружения (удобно для облака)
        for f, env in fields.items():
            if os.environ.get(env) and not (d.get(pid) or {}).get(f): d.setdefault(pid, {})[f] = os.environ[env]
    return d

def save_secrets(d: dict):
    blob, raw = json.dumps(d).encode(), None
    if sys.platform == "win32":
        try: raw = b"D" + _dpapi(blob, True)
        except Exception: raw = None
    if raw is None:
        try: raw = b"F" + _fernet().encrypt(blob)
        except Exception: raw = None
    raw = raw or b"P" + blob
    with _lock:
        _keys_path().write_bytes(raw)
        try: os.chmod(_keys_path(), 0o600)
        except Exception: pass

def load_cfg() -> dict:
    try: c = json.loads((DATA / "config.json").read_text(encoding="utf-8"))
    except Exception: c = {}
    c.setdefault("use", {}); c.setdefault("models", {}); c.setdefault("base", {})
    for k, v in DEFAULTS.items(): c["use"].setdefault(k, v)
    return c

def save_cfg(c: dict):
    with _lock: (DATA / "config.json").write_text(json.dumps(c, ensure_ascii=False, indent=1), encoding="utf-8")

def secret(pid: str, field: str = "key") -> str:
    return (load_secrets().get(pid) or {}).get(field, "")

def configured(pid: str) -> bool:
    p = PROVIDERS[pid]; s = load_secrets().get(pid) or {}; c = load_cfg()
    if pid == "veo" and not s.get("key") and (load_secrets().get("gemini") or {}).get("key"): return True   # подходит ключ Gemini
    for need in p["needs"]:
        if need == "base":
            if not (c["base"].get(pid) or "").strip(): return False
        elif not s.get(need): return False
    return True

def base_url(pid: str) -> str:
    c = load_cfg()
    if c["base"].get(pid): return c["base"][pid].rstrip("/")
    if pid == "cloudflare": return f"https://api.cloudflare.com/client/v4/accounts/{secret('cloudflare', 'account')}/ai/v1"
    return PROVIDERS[pid].get("base", "").rstrip("/")

def model_for(pid: str, cap: str, default: str = "") -> str:
    return (load_cfg()["models"].get(f"{pid}:{cap}") or default)

def chosen(cap: str) -> str:
    """Какой провайдер использовать для возможности. Пусто = не настроено."""
    c = load_cfg(); pid = c["use"].get(cap) or ""
    if pid and pid in PROVIDERS and cap in PROVIDERS[pid]["caps"] and configured(pid): return pid
    # запасные варианты, только бесплатные и настроенные
    if cap == "vision":
        for alt in ("gemini", "openrouter", "cloudflare", "ollama"):
            if configured(alt) and _picked(alt): return alt
        return ""
    if cap == "video_understanding": return "gemini" if configured("gemini") else ""
    if cap == "image_edit":
        for alt in ("cloudflare", "comfyui"):
            if configured(alt) and (alt != "comfyui" or c["use"].get("image") == "comfyui"): return alt
        return ""
    if cap == "stt":
        for alt in ("groq", "cloudflare", "gemini"):
            if configured(alt): return alt
        return ""
    return DEFAULTS.get(cap, "") if DEFAULTS.get(cap) and configured(DEFAULTS[cap]) else ""

def _picked(pid):  # провайдер выбран пользователем хотя бы для одной функции
    c = load_cfg(); return pid in c["use"].values() or pid == "gemini"

def public_state() -> dict:
    """Состояние для браузера — без ключей (только отметка «ключ сохранён» и последние 4 символа)."""
    sec, c = load_secrets(), load_cfg()
    provs = {}
    for pid, p in PROVIDERS.items():
        s = sec.get(pid) or {}
        provs[pid] = {**{k: p[k] for k in ("label", "caps", "needs", "cost", "limits", "signup")},
                      "configured": configured(pid), "key_hint": ("…" + s["key"][-4:]) if s.get("key") else "",
                      "account": s.get("account", ""), "base": c["base"].get(pid, p.get("base", ""))}
    active = {cap: chosen(cap) for cap in CAP_LABELS}
    return {"providers": provs, "use": c["use"], "active": active, "models": c["models"], "cap_labels": CAP_LABELS, "auto_best": c.get("auto_best", True)}

# ---------- автонастройка: лучший из подключённых сервисов для каждой функции ----------
BEST = {"text": ["gemini", "groq", "openrouter", "cloudflare", "pollinations_free"],
        "vision": ["gemini", "openrouter", "cloudflare"],
        "image": ["cloudflare", "pollinations_free"],
        "image_edit": ["cloudflare"],
        "tts": ["edge_tts"],
        "stt": ["groq", "gemini", "cloudflare"],
        "video": ["agnes", "hf_spaces", "slideshow"]}

def auto_best(force=False) -> dict:
    """Выбирает лучший бесплатный подключённый вариант. Платные (Pollinations с ключом) сам не включает."""
    c = load_cfg()
    if not force and (c.get("auto_best") is False or os.environ.get("MAISONAI_NO_AUTO")): return c["use"]
    for cap, order in BEST.items():
        if c["use"].get(cap) in ("comfyui", "fal", "veo", "runway") and configured(c["use"][cap]): continue   # выбранное вручную (локальное или платное) не трогаем
        for pid in order:
            if configured(pid): c["use"][cap] = pid; break
    c["auto_best"] = True
    save_cfg(c); return c["use"]
