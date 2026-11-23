import { state, api, h, icon, btn, fail, toast, go, field, select, segmented, RATIOS, LANGS, loadProviders, confirmBox, modal, runTool, download, copy, fmtDate } from "./lib.js";

const COST = { free: ["бесплатно", "free"], free_quota: ["бесплатный лимит", "free"], local: ["на вашем компьютере", "free"], paid_credits: ["платные кредиты", "paid"], paid: ["платно · цена до запуска", "paid"], unknown: ["зависит от сервера", ""] };
const MODEL_CAPS = { gemini: ["text"], groq: ["text"], openrouter: ["text", "vision"], cloudflare: ["text", "vision", "image"], ollama: ["text", "vision"], custom: ["text", "vision"], pollinations: ["text", "image", "video"] };
const CAP_MODEL_LBL = { text: "Модель для текста", vision: "Модель для картинок (зрение)", image: "Модель картинок", video: "Модель видео" };

export async function render(page, _k, tab) {
  tab = tab || "providers";
  const tabs = h("div.tabs", { role: "tablist" }, ...[["providers", "Провайдеры ИИ"], ["costs", "Расходы"], ["cloud", "Облако"], ["devices", "iPad и MacBook"], ["comfy", "ComfyUI"], ["profile", "Профиль"], ["account", "Аккаунт"]].map(([id, l]) =>
    h("button", { type: "button", class: id === tab ? "on" : "", role: "tab", onclick: () => go("#/settings/" + id) }, l)));
  const body = h("div");
  const ver = h("span.dim", { style: { fontSize: "12px", marginLeft: "12px" } });
  api("/api/info").then(r => ver.textContent = "версия " + r.version).catch(() => { });
  page.append(h("div.ph", {}, h("h1", {}, "Настройки", ver)), tabs, body);
  const f = { providers, costs, cloud, comfy, devices, profile, account }[tab] || providers;
  return f(body);
}

// ---------- провайдеры ----------
async function providers(body) {
  let s = await loadProviders(true);
  const local = s.local;
  const draw = () => {
    const capRows = Object.entries(s.cap_labels).filter(([c]) => c !== "video_understanding").map(([cap, lbl]) => {
      const opts = Object.entries(s.providers).filter(([, p]) => p.caps.includes(cap));
      const sel = select([["", cap === "stt" || cap === "vision" || cap === "image_edit" ? "Автоматически (из подключённых)" : "Не выбрано"], ...opts.map(([id, p]) => [id, `${p.label} — ${COST[p.cost][0]}${p.configured ? "" : " (не подключён)"}`])], s.use[cap] || "",
        { disabled: !local, onchange: async e => { try { s = await api("/api/settings/providers", { body: { use: { [cap]: e.target.value } } }); state.providers = { ...state.providers, ...s }; draw(); toast("Сохранено"); } catch (x) { fail(x); } } });
      const act = s.active[cap];
      return h("div.capsel", {}, h("span", {}, lbl), sel, act ? h("span.tag.ok", {}, "работает: " + s.providers[act].label) : h("span.tag.off", {}, "не работает"));
    });
    capRows.push(h("div.capsel", {}, h("span", {}, s.cap_labels.video_understanding), h("span.dim", { style: { fontSize: "12px" } }, "Только Google Gemini умеет смотреть видео целиком. Без него анализ идёт по кадрам (если подключено «зрение»)."),
      s.active.video_understanding ? h("span.tag.ok", {}, "работает") : h("span.tag.off", {}, "нужен ключ Gemini")));
    body.replaceChildren(
      !local ? h("div.note.warn", { style: { marginBottom: "16px" } }, "Ключи и провайдеров меняет владелец — первый аккаунт MaisonAI. Войдите под ним на любом устройстве.") : null,
      h("div.note", { style: { marginBottom: "16px" } }, "MaisonAI по умолчанию работает без ключей: текст и картинки — через бесплатный Pollinations (медленно, с паузами), голос — Microsoft Edge, видео — монтаж из кадров. Для скорости и качества подключите бесплатные ключи Gemini, Groq и Cloudflare. Платные сервисы без вашего выбора не используются."),
      h("div.panel", {}, h("div.row", { style: { marginBottom: "10px" } }, h("h3", { style: { margin: 0, flex: 1 } }, "Что чем делается"),
        s.auto_best !== false ? h("span.tag.ok", {}, "автонастройка включена") : null,
        btn("Выбрать лучшее автоматически", async () => { try { s = await api("/api/settings/auto", { body: {} }); state.providers = s; draw(); toast("Для каждой функции выбран лучший из подключённых сервисов"); } catch (e) { fail(e); } }, "sm pri", "sparkles", { disabled: !local })),
        h("p.dim", { style: { fontSize: "12px", marginBottom: "6px" } }, "После сохранения ключа MaisonAI сам выбирает лучший вариант: Gemini — текст и анализ видео, Cloudflare — картинки и их правка, Groq — распознавание речи, голоса Microsoft — озвучка. Платные сервисы сам не включает."),
        ...capRows),
      h("div.mono-up", { style: { margin: "24px 0 10px" } }, "Подключения"),
      ...Object.entries(s.providers).map(([id, p]) => provCard(id, p)));
  };
  const provCard = (id, p) => {
    const res = h("div");
    const key = h("input.in", { type: "password", placeholder: p.key_hint ? "Сохранён " + p.key_hint + " — введите новый, чтобы заменить" : "Вставьте ключ", autocomplete: "off", disabled: !local });
    const acc = h("input.in", { placeholder: "Account ID (32 символа, со страницы Workers AI)", value: p.account || "", disabled: !local });
    const base = h("input.in", { placeholder: "http://…", value: p.base || "", disabled: !local });
    const saveKey = btn("Сохранить", async () => {
      try {
        if (p.needs.includes("key") || p.needs.includes("account")) s = await api("/api/settings/keys", { body: { provider: id, key: key.value, account: id === "cloudflare" ? acc.value : "" } });
        if (["custom", "ollama", "comfyui"].includes(id)) s = await api("/api/settings/providers", { body: { base: { [id]: base.value } } });
        state.providers = s; toast("Сохранено"); draw();
      } catch (e) { fail(e); }
    }, "sm pri", "check", { disabled: !local });
    const test = btn("Проверить", async () => {
      test.disabled = true; res.replaceChildren(h("div.dim", {}, "Проверяю…"));
      try {
        const r = await api("/api/settings/test/" + id, { body: {} });
        res.replaceChildren(h("div", { class: r.ok ? "note" : "err" }, (r.ok ? "Работает. " : "") + r.detail + (r.ms ? ` · ${r.ms} мс` : "")));
        if (r.ok && r.models?.length && MODEL_CAPS[id]) res.append(modelPickers(id, r.models));
      } catch (e) { res.replaceChildren(h("div.err", {}, e.message)); }
      test.disabled = false;
    }, "sm", "refresh");
    const cost = COST[p.cost];
    const inputs = [];
    if (p.needs.includes("key")) inputs.push(field("Ключ API", key));
    if (id === "cloudflare") inputs.push(field("Account ID", acc));
    if (["custom", "ollama", "comfyui"].includes(id)) inputs.push(field("Адрес сервера", base));
    return h("div.prov", {},
      h("div.hd", {}, h("b", {}, p.label), h("span.tag." + (cost[1] || "x"), {}, cost[0]), p.configured ? h("span.tag.ok", {}, "подключён") : h("span.tag.off", {}, "не подключён"),
        h("div", { style: { flex: 1 } }), p.signup ? h("a.btn.sm.ghost", { href: p.signup, target: "_blank", rel: "noopener" }, icon("link"), p.needs.includes("key") ? "Получить ключ" : "Сайт") : null),
      h("p.lim", {}, p.limits),
      id === "cloudflare" ? h("p.lim", {}, "Как подключить: dash.cloudflare.com → Workers AI → «Use REST API» → создайте токен «Workers AI» и скопируйте Account ID.") : null,
      id === "hf_spaces" ? h("p.lim", {}, "Можно вставить несколько токенов через пробел — например ваш и сестры. Когда у одного кончится дневной лимит, программа сама возьмёт следующий. Только настоящие аккаунты разных людей: заводить несколько аккаунтов на одного человека Hugging Face запрещает и может заблокировать.") : null,
      id === "pollinations" ? h("div.row", { style: { marginBottom: "8px" } }, btn("Цены моделей", () => prices(), "sm ghost", "eye")) : null,
      inputs.length ? h("div.grid2", {}, ...inputs) : null,
      h("div.row", { style: { marginTop: "10px" } }, inputs.length ? saveKey : null, test,
        p.key_hint && local ? btn("Удалить ключ", async () => { if (!await confirmBox("Удалить сохранённый ключ " + p.label + "?")) return; s = await api("/api/settings/keys", { body: { provider: id, clear: true } }); state.providers = s; draw(); }, "sm ghost danger", "trash") : null),
      res);
  };
  const modelPickers = (id, models) => h("div.grid2", { style: { marginTop: "10px" } }, ...MODEL_CAPS[id].filter(c => c !== "image" && c !== "video").map(cap =>
    field(CAP_MODEL_LBL[cap], select([["", "Автоматически"], ...models.map(m => [m, m])], s.models[`${id}:${cap}`] || "", { disabled: !local, onchange: async e => { try { s = await api("/api/settings/providers", { body: { models: { [`${id}:${cap}`]: e.target.value } } }); toast("Модель сохранена"); } catch (x) { fail(x); } } }))));
  const prices = async () => {
    const box = h("div.col", {}, h("div.dim", {}, "Загружаю каталог Pollinations…"));
    modal("Цены Pollinations", box);
    for (const kind of ["video", "image"]) {
      try {
        const r = await api("/api/settings/pollinations_prices?kind=" + kind);
        if (r.error) { box.append(h("div.err", {}, r.error)); continue; }
        box.append(h("h3", {}, kind === "video" ? "Видео" : "Изображения"), ...r.models.map(m => h("div.capsel", {}, h("b", {}, m.id), h("span.dim", { style: { fontSize: "12px" } }, m.description || ""), h("span.tag" + (m.paid_only ? ".paid" : ""), {}, m.pricing ? JSON.stringify(m.pricing).slice(0, 80) : "цена не указана"))));
      } catch (e) { box.append(h("div.err", {}, e.message)); }
    }
    box.firstChild.remove();
  };
  draw();
}

// ---------- ComfyUI ----------
async function comfy(body) {
  const s = await loadProviders(true);
  const st = h("div"), ck = h("div");
  const check = async () => {
    st.replaceChildren(h("div.dim", {}, "Проверяю ComfyUI…"));
    const r = await api("/api/settings/test/comfyui", { body: {} });
    st.replaceChildren(h("div", { class: r.ok ? "note" : "err" }, r.detail));
    if (r.ok) {
      const m = await api("/api/settings/comfy_models");
      const cps = m.checkpoints || [], dm = m.diffusion_models || [];
      const wanOk = dm.includes(s.wan_models.unet);
      ck.replaceChildren(
        h("div", { class: wanOk ? "note" : "note warn" }, wanOk ? "Модель видео Wan 2.2 5B найдена." : "Модель видео Wan 2.2 5B не найдена в ComfyUI/models/diffusion_models."),
        cps.length ? field("Модель для картинок (чекпойнт)", select([["", "Первая доступная"], ...cps.map(c => [c, c])], s.models["comfyui:image"] || "", { disabled: !s.local, onchange: async e => { await api("/api/settings/providers", { body: { models: { "comfyui:image": e.target.value } } }); toast("Сохранено"); } }))
          : h("div.note.warn", {}, "Нет моделей для картинок (папка models/checkpoints пуста)."));
    }
  };
  const L = "https://huggingface.co/Comfy-Org/";
  body.replaceChildren(h("div.grid2", {},
    h("div.panel", {}, h("h3", {}, "Настоящее нейросетевое видео бесплатно"), h("p.muted", {}, "ComfyUI запускает модели на вашей видеокарте: без лимитов и без оплаты. Нужна видеокарта NVIDIA (для Wan 2.2 5B — от 8 ГБ видеопамяти, лучше 12+). 5 секунд видео генерируются от нескольких минут."),
      h("ol", { style: { margin: "12px 0 0 18px", display: "grid", gap: "8px", color: "var(--tx2)" } },
        h("li", {}, "Установите ComfyUI Desktop: ", h("a", { href: "https://www.comfy.org/download", target: "_blank", rel: "noopener", style: { textDecoration: "underline" } }, "comfy.org/download")),
        h("li", {}, "Скачайте 3 файла модели Wan 2.2 5B и положите в папки ComfyUI/models:"),
        h("li", { style: { listStyle: "none" } }, h("dl.kv", {},
          h("dt", {}, "diffusion_models"), h("dd", {}, h("a", { href: L + "Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/diffusion_models/" + s.wan_models.unet, target: "_blank", rel: "noopener", style: { textDecoration: "underline" } }, s.wan_models.unet), " · 9,3 ГБ"),
          h("dt", {}, "text_encoders"), h("dd", {}, h("a", { href: L + "Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/text_encoders/" + s.wan_models.clip, target: "_blank", rel: "noopener", style: { textDecoration: "underline" } }, s.wan_models.clip), " · 6,3 ГБ"),
          h("dt", {}, "vae"), h("dd", {}, h("a", { href: L + "Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/vae/" + s.wan_models.vae, target: "_blank", rel: "noopener", style: { textDecoration: "underline" } }, s.wan_models.vae), " · 1,3 ГБ"))),
        h("li", {}, "Для картинок положите любую SDXL-модель в models/checkpoints."),
        h("li", {}, "Запустите ComfyUI, нажмите «Проверить» и выберите ComfyUI в «Провайдеры ИИ» для видео и картинок."))),
    h("div.panel.col", {}, h("h3", { style: { margin: 0 } }, "Подключение"), btn("Проверить ComfyUI", () => check().catch(e => st.replaceChildren(h("div.err", {}, e.message))), "pri", "refresh"), st, ck)));
}

// ---------- устройства ----------
async function devices(body) {
  const draw = async () => {
    const n = await api("/api/net");
    if (n.cloud) {
      body.replaceChildren(h("div.grid2", {}, h("div.panel.col", {}, h("h3", { style: { margin: 0 } }, "Облачная версия"), h("p.muted", {}, "MaisonAI работает на сервере в интернете — откройте этот адрес на любом устройстве. Компьютер включать не нужно."),
        h("div.row", {}, h("img.qr", { src: "/api/net/qr?url=" + encodeURIComponent(n.urls[0]), alt: "QR-код" }), h("div.col", {}, h("b", { style: { fontSize: "16px", wordBreak: "break-all" } }, n.urls[0]), btn("Копировать адрес", () => copy(n.urls[0]), "sm", "copy")))),
        installHelp()));
      return;
    }
    let rm = null; try { rm = await api("/api/remote"); } catch { }
    const remotePanel = rm ? remoteBox(rm, draw) : null;
    const sw = btn(n.enabled ? "Выключить доступ" : "Включить доступ", async () => { try { await api("/api/net", { body: { enabled: !n.enabled } }); draw(); } catch (e) { fail(e); } }, n.enabled ? "" : "pri", "device", { disabled: !n.local });
    body.replaceChildren(remotePanel || "", h("div.grid2", {},
      h("div.panel.col", {}, h("h3", { style: { margin: 0 } }, "Доступ по Wi-Fi"), h("p.muted", {}, "MaisonAI работает на компьютере, а iPad и iPhone открывают его по домашней сети Wi-Fi. Все проекты общие — начните на компьютере, продолжите на iPad."),
        h("div.row", {}, h("span.tag" + (n.enabled ? ".ok" : ".off"), {}, n.enabled ? "включён" : "выключен"), sw),
        !n.local ? h("div.note", {}, "Вы уже подключены с другого устройства.") : null,
        n.enabled ? h("div.col", {}, ...n.urls.map(u => h("div.row", {}, h("img.qr", { src: "/api/net/qr?url=" + encodeURIComponent(u), alt: "QR-код " + u }), h("div.col", {}, h("b", { style: { fontSize: "18px" } }, u), h("span.dim", {}, "Наведите камеру iPhone/iPad на код"))))) : null),
      h("div.panel", {}, h("h3", {}, "Как установить на iPad и iPhone"), h("ol", { style: { marginLeft: "18px", display: "grid", gap: "8px", color: "var(--tx2)" } },
        h("li", {}, "Компьютер и iPad — в одной сети Wi-Fi. Включите доступ слева."),
        h("li", {}, "Один раз запустите ALLOW_DEVICES.bat в папке MaisonAI (разрешит соединение в брандмауэре Windows)."),
        h("li", {}, "Откройте адрес в Safari или наведите камеру на QR-код."),
        h("li", {}, "Нажмите «Поделиться» → «На экран Домой». MaisonAI откроется как приложение, без адресной строки."),
        h("li", {}, "Компьютер должен быть включён, а MaisonAI — запущен.")),
        h("p.dim", { style: { marginTop: "10px", fontSize: "12px" } }, "Ключи ИИ остаются на компьютере и не передаются на iPad."))));
  };
  await draw();
}

let remoteTimer = null;
function remoteBox(r, redraw) {
  clearTimeout(remoteTimer);
  if (r.enabled && r.status !== "on") remoteTimer = setTimeout(() => { if (document.querySelector(".remote-box")) redraw(); }, 2500);
  const link = r.stable_url || r.url;
  const tag = !r.enabled ? h("span.tag.off", {}, "выключен") : r.status === "on" ? h("span.tag.ok", {}, "работает") :
    r.status === "downloading" ? h("span.tag", {}, `скачиваю программу туннеля ${Math.round(r.download * 100)}%`) : r.status === "error" ? h("span.tag.off", {}, "переподключаюсь…") : h("span.tag", {}, "запускаю…");
  const sw = btn(r.enabled ? "Выключить" : "Включить доступ из любого места", async e => { e.currentTarget.disabled = true; try { await api("/api/remote", { body: { enabled: !r.enabled } }); } catch (x) { fail(x); } redraw(); },
    r.enabled ? "" : "pri", "globe", { disabled: !r.local });
  const tok = h("input.in", { type: "password", placeholder: "Токен Cloudflare (Edit Cloudflare Workers)", autocomplete: "off", spellcheck: false });
  const L = (href, text) => h("a", { href, target: "_blank", rel: "noopener", style: { textDecoration: "underline" } }, text);
  const save = btn("Сделать ссылку постоянной", async e => {
    const b = e.currentTarget; if (!tok.value.trim()) return toast("Вставьте токен Cloudflare", true);
    b.disabled = true; try { await api("/api/remote/link", { body: { token: tok.value.trim() } }); toast("Постоянная ссылка готова"); redraw(); } catch (x) { fail(x); } b.disabled = false; }, "sm", "link");
  return h("div.panel.col.remote-box", { style: { marginBottom: "16px" } },
    h("h3", { style: { margin: 0 } }, "Доступ из любого места"),
    h("p.muted", {}, "MaisonAI открывается по ссылке с iPad, MacBook и телефона где угодно — дома, в дороге, через мобильный интернет. Без карты и бесплатно. Работает, пока компьютер включён: программа сама запускается вместе с Windows и не даёт компьютеру уснуть."),
    h("div.row", {}, tag, sw),
    !r.local ? h("div.note", {}, "Включать и выключать доступ можно только на самом компьютере.") : null,
    r.enabled && r.error && r.status !== "on" ? h("div.note.warn", {}, r.error) : null,
    r.enabled && link && (r.status === "on" || r.stable_url) ? h("div.row", {}, h("img.qr", { src: "/api/net/qr?url=" + encodeURIComponent(link), alt: "QR-код" }),
      h("div.col", {}, h("b", { style: { fontSize: "16px", wordBreak: "break-all" } }, link), h("div.row", {}, btn("Копировать", () => copy(link), "sm", "copy"), h("a.btn.sm.ghost", { href: link, target: "_blank", rel: "noopener" }, icon("link"), "Открыть")),
        h("span.dim", {}, r.stable_url ? "Постоянная ссылка — сохраните её на iPad «На экран Домой»." : "Эта ссылка поменяется после перезагрузки компьютера. Ниже можно сделать постоянную."))) : null,
    r.enabled ? h("div.note", {}, "Войти из интернета можно только своим логином и паролем. Новые люди регистрируются только по коду приглашения (Настройки → Аккаунт).") : null,
    r.local ? h("details", { style: { marginTop: "4px" } }, h("summary", { style: { cursor: "pointer", fontWeight: 600 } }, r.stable_url ? "Постоянная ссылка включена" : "Постоянная ссылка (по желанию, 2 минуты)"),
      h("div.col", { style: { marginTop: "10px", gap: "8px" } },
        r.stable_error ? h("div.note.warn", {}, r.stable_error) : null,
        r.stable_url ? h("div.row", {}, h("span.dim", {}, r.stable_url), btn("Убрать", async () => { try { await api("/api/remote/link", { body: { token: "" } }); redraw(); } catch (x) { fail(x); } }, "sm ghost", "x")) :
        h("div.col", { style: { gap: "8px" } },
          h("ol", { style: { marginLeft: "18px", display: "grid", gap: "6px", color: "var(--tx2)" } },
            h("li", {}, "Откройте ", L("https://dash.cloudflare.com/profile/api-tokens", "dash.cloudflare.com/profile/api-tokens"), " (тот же аккаунт Cloudflare, что для картинок)."),
            h("li", {}, "«Create Token» → напротив «Edit Cloudflare Workers» нажмите «Use template»."),
            h("li", {}, "Внизу «Continue to summary» → «Create Token» → «Copy»."),
            h("li", {}, "Вставьте сюда и нажмите кнопку. Ссылка будет вида maisonai.….workers.dev и больше не поменяется.")),
          tok, save))) : null);
}

function installHelp() {
  return h("div.panel", {}, h("h3", {}, "Как установить как приложение"),
    h("div.mono-up", { style: { margin: "6px 0" } }, "iPad и iPhone"),
    h("ol", { style: { marginLeft: "18px", display: "grid", gap: "6px", color: "var(--tx2)" } },
      h("li", {}, "Откройте адрес в Safari (или наведите камеру на QR-код)."),
      h("li", {}, "Нажмите кнопку «Поделиться» (квадрат со стрелкой вверх)."),
      h("li", {}, "Выберите «На экран Домой» → «Добавить». Иконка MaisonAI появится рядом с приложениями.")),
    h("div.mono-up", { style: { margin: "14px 0 6px" } }, "MacBook"),
    h("ol", { style: { marginLeft: "18px", display: "grid", gap: "6px", color: "var(--tx2)" } },
      h("li", {}, "Safari: меню «Файл» → «Добавить в Dock». MaisonAI откроется отдельным окном, как программа."),
      h("li", {}, "Chrome: ⋮ → «Трансляция, сохранение и отправка» → «Установить страницу как приложение»."),
      h("li", {}, "Войдите тем же логином — проекты общие на всех устройствах.")));
}

// ---------- облако ----------
async function cloud(body) {
  const st = await api("/api/cloud/state");
  if (st.cloud) {
    await devices(body);
    const b = st.backup || {};
    if (b.repo || b.error) body.prepend(h("div", { class: b.error || !b.enabled ? "note warn" : "note", style: { marginBottom: "16px" } },
      b.error ? b.error : !b.enabled ? "Автосохранение выключено." : "Ваши данные автоматически сохраняются в закрытый архив на Hugging Face каждые полторы минуты" + (b.last ? ` (последний раз: ${b.last} UTC)` : "") + ". Когда сервер «просыпается», всё восстанавливается само."));
    return;
  }
  // ---------- Render: без карты ----------
  const L2 = (href, text) => h("a", { href, target: "_blank", rel: "noopener", style: { textDecoration: "underline" } }, text);
  const hfTok = h("input.in", { type: "password", placeholder: st.tokens_saved ? "сохранён — можно не вводить" : "hf_…", autocomplete: "off", spellcheck: false });
  const ghTok = h("input.in", { type: "password", placeholder: st.tokens_saved ? "сохранён — можно не вводить" : "ghp_…", autocomplete: "off", spellcheck: false });
  const rMigrate = h("input", { type: "checkbox", checked: true });
  const rOut = h("div");
  const renderUrl = h("input.in", { placeholder: "https://maisonai-xxxx.onrender.com", value: st.kind === "render" ? st.cloud_url || "" : "" });
  const stp = (n, title, ...kids) => h("div.plan-scene", {}, h("div.no", {}, String(n).padStart(2, "0")), h("div.col", { style: { gap: "6px" } }, h("b", {}, title), ...kids));
  const renderSteps = repo => h("div.panel.col", { style: { marginTop: "12px" } }, h("h3", { style: { margin: 0 } }, "Осталось 6 кликов в Render"),
    stp(1, "Зарегистрируйтесь в Render", h("span.muted", {}, L2("https://dashboard.render.com/register", "dashboard.render.com/register"), " → проще всего кнопкой «GitHub» (тот же аккаунт). Карта не нужна.")),
    stp(2, "Создайте сервер", h("span.muted", {}, "Вверху «+ New» → «Web Service» → вкладка «Public Git Repository» → вставьте ссылку и нажмите «Connect»:"),
      h("div.row", {}, h("b", { style: { wordBreak: "break-all" } }, repo), btn("Копировать", () => copy(repo), "sm", "copy"))),
    stp(3, "Заполните поля", h("ul.dash-list", {}, h("li", {}, "Name: maisonai"), h("li", {}, "Language: Docker"), h("li", {}, "Region: Frankfurt (EU Central)"), h("li", {}, "Instance Type: Free"))),
    stp(4, "Добавьте один секрет", h("span.muted", {}, "Ниже, в «Environment Variables»: NAME — ", h("b", {}, "HF_TOKEN"), ", VALUE — тот же токен Hugging Face (hf_…), что вы вставили выше.")),
    stp(5, "Нажмите «Deploy Web Service»", h("span.muted", {}, "Сборка 5–10 минут. Когда вверху появится зелёное «Live» — готово.")),
    stp(6, "Скопируйте адрес сервера сюда", h("span.muted", {}, "Он вверху страницы Render, под названием (…onrender.com)."),
      h("div.row", {}, renderUrl, btn("Сохранить и проверить", async e => {
        const bt = e.currentTarget; bt.disabled = true; toast("Проверяю — если сервер спит, это займёт до минуты…");
        try { const r = await api("/api/cloud/render/url", { body: { url: renderUrl.value } }); toast(r.ok ? "Облако работает!" : "Адрес сохранён, но сервер пока не отвечает — подождите, пока в Render будет «Live».", !r.ok); cloud(body); } catch (x) { fail(x); }
        bt.disabled = false; }, "sm pri", "check"))),
    h("p.dim", { style: { fontSize: "12px" } }, "Обновить программу в облаке: нажмите «Подготовить облако» ещё раз, затем в Render — «Manual Deploy» → «Deploy latest commit»."));
  const rGo = btn(st.kind === "render" ? "Подготовить облако ещё раз (обновить)" : "Подготовить облако", async () => {
    if (!st.tokens_saved && (!hfTok.value.trim() || !ghTok.value.trim())) return toast("Вставьте оба токена", true);
    rGo.disabled = true;
    try {
      const r = await runTool("/api/cloud/render/prepare", { hf_token: hfTok.value.trim(), gh_token: ghTok.value.trim(), migrate: rMigrate.checked }, rOut, "Подготовка облака");
      ghTok.value = "";
      rOut.replaceChildren(h("div.note", {}, r.migrated ? "Проекты, файлы и ключи ИИ перенесены в ваш закрытый архив." : r.kept ? "В архиве уже были ваши данные — я их оставил, ничего не перезаписал." : "Программа выложена."), renderSteps(r.repo));
    } catch (e) { rOut.replaceChildren(h("div.err", { style: { whiteSpace: "pre-wrap" } }, e.message)); }
    rGo.disabled = false;
  }, "pri wide", "upload");
  const renderPanel = h("div.grid2", { style: { marginBottom: "20px" } },
    h("div.col", {},
      stp(1, "Токен Hugging Face с правом записи", h("span.muted", {}, L2("https://huggingface.co/settings/tokens/new?tokenType=write", "huggingface.co/settings/tokens"), " → «Create new token» → вкладка ", h("b", {}, "Write"), " → имя MaisonAI → «Create token» → «Copy». Там будут храниться ваши проекты (закрыто).")),
      stp(2, "Аккаунт и токен GitHub", h("span.muted", {}, "Регистрация: ", L2("https://github.com/signup", "github.com/signup"), " (бесплатно, без карты). Потом откройте ", L2("https://github.com/settings/tokens/new?scopes=public_repo&description=MaisonAI", "эту ссылку"),
        " → «Expiration»: No expiration → внизу «Generate token» → скопируйте (ghp_…). Туда выкладывается только программа, без ваших данных и ключей.")),
      stp(3, "Вставьте оба токена и нажмите кнопку", h("span.muted", {}, "Потом я покажу 6 простых кликов в Render."))),
    h("div.panel.col", {}, h("h3", { style: { margin: 0 } }, "Render · бесплатно, без карты"),
      !state.local ? h("div.note.warn", {}, "Готовить облако можно только с самого компьютера.") : null,
      field("Токен Hugging Face (Write)", hfTok), field("Токен GitHub", ghTok), h("label.row", {}, rMigrate, "Перенести мои проекты, файлы и ключи ИИ"), rGo,
      h("p.dim", { style: { fontSize: "12px" } }, "Токены хранятся только на этом компьютере в зашифрованном виде (для обновлений облака) и не попадают в историю."),
      rOut, st.kind === "render" && st.repo ? renderSteps(st.repo) : null));
  const ip = h("input.in", { placeholder: "Например: 140.238.12.34", inputMode: "decimal", value: st.cloud_host || "" });
  const user = h("input.in", { value: "ubuntu" });
  let keyText = "";
  const keyName = h("span.dim", {}, "файл не выбран");
  const keyInp = h("input", { type: "file", accept: ".key,.pem,*", style: { display: "none" }, onchange: async e => { const f = e.target.files[0]; if (!f) return; keyText = await f.text(); keyName.textContent = f.name + (keyText.includes("PRIVATE KEY") ? "" : " — это не приватный ключ"); } });
  const migrate = h("input", { type: "checkbox", checked: true });
  const out = h("div");
  const go_ = btn(st.cloud_url ? "Обновить программу в облаке" : "Установить в облако", async () => {
    if (!ip.value.trim()) return toast("Вставьте Public IP сервера", true);
    if (!keyText) return toast("Выберите файл ключа .key", true);
    go_.disabled = true;
    try {
      const r = await runTool("/api/cloud/deploy", { host: ip.value.trim(), user: user.value.trim() || "ubuntu", key: keyText, migrate: migrate.checked }, out, "Установка в облако");
      out.replaceChildren(result(r.url, r.reachable, r.note, r.migrated));
    } catch (e) { out.replaceChildren(h("div.err", { style: { whiteSpace: "pre-wrap" } }, e.message)); }
    go_.disabled = false;
  }, "pri wide", "upload");
  const result = (url, ok, note, migrated) => h("div.panel.col", { style: { marginTop: "12px" } },
    h("div.row", {}, h("span.tag" + (ok ? ".ok" : ".off"), {}, ok ? "работает из интернета" : "ещё не открывается"), migrated ? h("span.tag", {}, "проекты перенесены") : null),
    h("div.row", {}, h("img.qr", { src: "/api/net/qr?url=" + encodeURIComponent(url), alt: "QR" }), h("div.col", {}, h("b", { style: { fontSize: "16px", wordBreak: "break-all" } }, url),
      h("a.btn.pri.sm", { href: url, target: "_blank", rel: "noopener" }, icon("link"), "Открыть"),
      btn("Проверить адрес", async e => { const b = e.currentTarget; b.disabled = true; try { const r = await api("/api/cloud/check", { body: { url } }); toast(r.ok ? "Облако отвечает — всё работает" : "Пока не отвечает: " + r.detail, !r.ok); } catch (x) { fail(x); } b.disabled = false; }, "sm", "refresh"))),
    note ? h("div.note.warn", {}, note) : null,
    h("p.dim", { style: { fontSize: "12px" } }, "Войдите в облаке тем же логином и паролем. Ключи ИИ уже перенесены и зашифрованы на сервере."));
  const step = (n, title, ...kids) => h("div.plan-scene", {}, h("div.no", {}, String(n).padStart(2, "0")), h("div.col", { style: { gap: "6px" } }, h("b", {}, title), ...kids));
  const L = (href, text) => h("a", { href, target: "_blank", rel: "noopener", style: { textDecoration: "underline" } }, text);
  const oracle = h("details.panel", { style: { marginTop: "8px" } }, h("summary", { style: { cursor: "pointer", fontWeight: 600 } }, "Oracle Cloud — мощный сервер (нужна карта для проверки)"), h("div", { style: { marginTop: "14px" } },
    h("div.grid2", {},
      h("div.col", {},
        step(1, "Зарегистрируйтесь в Oracle Cloud", h("span.muted", {}, "Откройте ", L("https://signup.cloud.oracle.com", "signup.cloud.oracle.com"), ", выберите регион поближе (например, Frankfurt). Понадобятся почта, телефон и карта для проверки.")),
        step(2, "Создайте сервер", h("span.muted", {}, "Меню ≡ → Compute → Instances → Create instance."),
          h("ul.dash-list", {}, h("li", {}, "Image: Canonical Ubuntu 24.04"), h("li", {}, "Shape: Ampere VM.Standard.A1.Flex — 2 OCPU, 12 GB (бесплатно). Если «Out of capacity» — повторите позже или выберите VM.Standard.E2.1.Micro (слабее)."),
            h("li", {}, "SSH keys: «Generate a key pair for me» → «Save private key». Сохраните файл .key."), h("li", {}, "Нажмите Create и подождите 1–2 минуты."))),
        step(3, "Откройте порты 80 и 443", h("span.muted", {}, "На странице сервера: Subnet → Security Lists → Default Security List → Add Ingress Rules."),
          h("ul.dash-list", {}, h("li", {}, "Source CIDR: 0.0.0.0/0"), h("li", {}, "IP Protocol: TCP"), h("li", {}, "Destination Port Range: 80,443"), h("li", {}, "Add Ingress Rules"))),
        step(4, "Скопируйте Public IP address", h("span.muted", {}, "Он на странице сервера, в блоке «Instance access»."))),
      h("div.panel.col", {}, h("h3", { style: { margin: 0 } }, "5 · Установка одной кнопкой"),
        !state.local ? h("div.note.warn", {}, "Устанавливать облако можно только с самого компьютера.") : null,
        field("Public IP сервера", ip), field("Пользователь", user, "для Ubuntu — ubuntu"),
        field("Файл ключа SSH", h("div.row", {}, btn("Выбрать файл .key", () => keyInp.click(), "sm", "upload"), keyName, keyInp)),
        h("label.row", {}, migrate, "Перенести мои проекты, файлы и ключи ИИ"),
        go_, h("p.dim", { style: { fontSize: "12px" } }, "Программа подключится к серверу, установит всё нужное (5–10 минут), включит HTTPS и перенесёт ваши данные. Ключ SSH используется только для установки и не сохраняется."),
        out))));
  body.replaceChildren(
    h("div.note", { style: { marginBottom: "16px" } }, "Чтобы MaisonAI открывалась при выключенном компьютере, её ставят на бесплатный сервер Render (без карты). Честно о минусах: он намного слабее компьютера (длинные ролики собираются медленно), засыпает через 15 минут без посетителей (первое открытие ≈ 1 минута) и даёт около 5 ГБ трафика в месяц. Ваши данные хранятся в закрытом архиве на Hugging Face и не пропадают."),
    st.cloud_url ? h("div", { style: { marginBottom: "16px" } }, result(st.cloud_url, null, "", false)) : null,
    renderPanel, oracle);
}

// ---------- профиль ----------
async function profile(body) {
  const u = state.user;
  const name = h("input.in", { value: u.display_name, maxLength: 40 });
  const lang = select(LANGS, u.prefs?.language || "uk");
  const ratio = segmented(RATIOS, u.prefs?.ratio || "9:16");
  const old = h("input.in", { type: "password", autocomplete: "current-password" }), nw = h("input.in", { type: "password", autocomplete: "new-password", minLength: 8 });
  body.replaceChildren(h("div.grid2", {},
    h("div.panel.col", {}, h("h3", { style: { margin: 0 } }, "Профиль"), h("dl.kv", {}, h("dt", {}, "Логин"), h("dd", {}, u.username), h("dt", {}, "Создан"), h("dd", {}, u.created)),
      field("Имя", name), field("Язык по умолчанию", lang), field("Формат по умолчанию", ratio),
      btn("Сохранить", async () => { try { await api("/api/account/profile", { body: { display_name: name.value, prefs: { language: lang.value, ratio: ratio.value } } }); state.user.display_name = name.value || u.username; state.user.prefs = { ...u.prefs, language: lang.value, ratio: ratio.value }; toast("Сохранено"); } catch (e) { fail(e); } }, "pri", "check")),
    h("div.panel.col", {}, h("h3", { style: { margin: 0 } }, "Пароль"), field("Текущий пароль", old), field("Новый пароль", nw, "не короче 8 символов"),
      btn("Сменить пароль", async () => { try { await api("/api/account/password", { body: { old: old.value, new: nw.value } }); old.value = nw.value = ""; toast("Пароль изменён"); } catch (e) { fail(e); } }, "", "lock"))));
}

async function account(body) {
  const pw = h("input.in", { type: "password", placeholder: "Пароль для подтверждения" });
  const impInp = h("input", { type: "file", accept: ".zip", style: { display: "none" }, onchange: async e => {
    const f = e.target.files[0]; if (!f) return; const fd = new FormData(); fd.append("file", f);
    try { const r = await api("/api/account/import", { body: fd }); toast(`Импортировано: проектов ${r.projects}, файлов ${r.assets}, генераций ${r.jobs}`); } catch (x) { fail(x); }
    impInp.value = ""; } });
  const data = h("div.panel.col", {}, h("h3", { style: { margin: 0 } }, "Перенос данных"), h("p.muted", {}, "Скачайте все свои проекты и файлы одним архивом или загрузите архив с другого компьютера или из облака."),
    h("div.row", {}, btn("Скачать все данные", () => download("/api/account/export", "MaisonAI.zip"), "", "download"), btn("Загрузить архив", () => impInp.click(), "", "upload"), impInp));
  let invBox = null;
  try {
    const inv = await api("/api/account/invite");
    if (inv.cloud || inv.remote) {
      const code = h("b", { style: { fontSize: "22px", fontFamily: "var(--fm)", letterSpacing: ".12em" } }, inv.code);
      invBox = h("div.panel.col", {}, h("h3", { style: { margin: 0 } }, "Приглашения"), h("p.muted", {}, "Регистрация в облаке закрыта для посторонних. Дайте этот код человеку, которого хотите пустить."),
        h("div.row", {}, code, btn("", () => copy(code.textContent), "sm icon ghost", "copy"), btn("Новый код", async () => { const r = await api("/api/account/invite", { body: { regenerate: true } }); code.textContent = r.code; toast("Старый код больше не работает"); }, "sm", "refresh")));
    }
  } catch { }
  body.replaceChildren(h("div.grid2", { style: { marginBottom: "16px" } }, data, invBox), h("div.grid2", {},
    h("div.panel.col", {}, h("h3", { style: { margin: 0 } }, "Сеанс"), btn("Выйти", async () => { await api("/api/auth/logout", { body: {} }).catch(() => { }); localStorage.removeItem("mai_project"); location.hash = "#/"; location.reload(); }, "", "logout"),
      h("p.dim", { style: { fontSize: "12px" } }, "Файлы хранятся в папке data рядом с программой. Чтобы перенести MaisonAI на другой компьютер, скопируйте эту папку.")),
    h("div.panel.col", {}, h("h3", { style: { margin: 0 } }, "Удалить аккаунт"), h("p.muted", {}, "Удалит все ваши проекты, файлы и историю. Отменить нельзя."), pw,
      btn("Удалить навсегда", async () => {
        if (!await confirmBox("Точно удалить аккаунт и все данные?")) return;
        try { await api("/api/account?password=" + encodeURIComponent(pw.value), { method: "DELETE" }); location.hash = "#/"; location.reload(); } catch (e) { fail(e); }
      }, "danger", "trash"))));
}

// ---------- Расходы: бюджет, модели fal.ai, журнал, счётчик запросов ----------
const USD = v => "$" + (Math.abs(v) < 0.1 && v !== 0 ? Number(v).toFixed(3) : Number(v || 0).toFixed(2));
async function costs(body) {
  const [r, pr, st] = await Promise.all([api("/api/costs"), api("/api/costs/prices"), api("/api/settings/providers")]);
  const b = r.budget, sp = r.spent, edit = r.can_edit;
  const inp = (v) => h("input.in", { type: "number", min: 0, max: 1000, step: 0.5, value: v, disabled: !edit });
  const daily = inp(b.daily), monthly = inp(b.monthly), maxJob = inp(b.max_job);
  const meter = (label, used, lim) => h("div.meter", {}, h("div.row", { style: { justifyContent: "space-between" } }, h("span", {}, label), h("b", {}, `${USD(used)} / ${USD(lim)}`)),
    h("div.bar", {}, h("i", { style: { width: Math.min(100, lim > 0 ? used / lim * 100 : 100) + "%" } })));
  const falOn = st.providers.fal?.configured;
  const kinds = [["video", "Видео (картинка → видео)"], ["image", "Картинки"], ["image_edit", "Правка картинок"]];
  const unitRu = u => ({ second: "за секунду", megapixel: "за мегапиксель", image: "за картинку", video: "за ролик" })[u] || u;
  const modelSel = kind => field(kinds.find(k => k[0] === kind)[1], select(pr.models.filter(m => m.kind === kind).map(m => [m.id, `${m.label} — ${USD(m.live ? m.live[0] : m.price)} ${unitRu(m.live ? m.live[1] : m.unit)}`]), pr.selected[kind],
    { disabled: !edit, onchange: async e => { try { await api("/api/settings/providers", { body: { models: { ["fal:" + kind]: e.target.value } } }); toast("Модель сохранена"); } catch (x) { fail(x); } } }));
  const useSel = cap => {
    const opts = Object.entries(st.providers).filter(([, p]) => p.caps.includes(cap) && p.configured).map(([id, p]) => [id, p.label]);
    return select(opts, st.use[cap] || "", { disabled: !edit, onchange: async e => { try { await api("/api/settings/providers", { body: { use: { [cap]: e.target.value } } }); toast(e.target.value === "fal" ? "Включено. Перед каждым запуском будет цена и подтверждение." : "Сохранено"); } catch (x) { fail(x); } } });
  };
  const st_ = { charged: ["ok", "оплачено"], running: ["", "идёт"], failed: ["off", "не выполнено · не оплачено"], unknown: ["warn", "неизвестно"] };
  body.replaceChildren(
    h("div.note", { style: { marginBottom: "16px" } }, "Платные модели запускаются только после того, как вы увидели цену и нажали «Подтвердить». Сама программа на платное не переключается — только на бесплатное, если платный сервис недоступен. Бюджет проверяется до запуска: выйти за лимит нельзя."),
    h("div.grid2", {},
      h("div.panel.col", {}, h("h3", { style: { margin: 0 } }, "Бюджет"),
        meter("Сегодня", sp.day, b.daily), meter("Этот месяц", sp.month, b.monthly),
        h("div.grid3", {}, field("В день, $", daily), field("В месяц, $", monthly), field("На одну задачу, $", maxJob)),
        edit ? btn("Сохранить бюджет", async () => { try { await api("/api/costs/budget", { body: { daily: +daily.value, monthly: +monthly.value, max_job: +maxJob.value } }); toast("Бюджет сохранён"); costs(body); } catch (x) { fail(x); } }, "pri", "check") : h("div.dim", {}, "Бюджет меняет владелец.")),
      h("div.panel.col", {}, h("h3", { style: { margin: 0 } }, "Генерация видео — все варианты"), h("p.dim", { style: { fontSize: "13px", margin: 0 } }, "Бесплатные (Hugging Face, свой компьютер, монтаж) и платные (fal.ai — сотни моделей, Google Veo, Runway) в одном списке с ценами."),
        btn("Все модели видео", () => import("./videomodels.js").then(m => m.openVideoModels()), "pri", "sparkles")),
      h("div.panel.col", {}, h("h3", { style: { margin: 0 } }, "fal.ai — платные модели"),
        falOn ? h("div.note", {}, "Ключ fal.ai подключён.") : h("div.note.warn", {}, "Ключ fal.ai не подключён: Провайдеры ИИ → fal.ai → вставьте ключ с fal.ai/dashboard/keys. Без ключа платные модели не используются."),
        ...kinds.map(([k]) => modelSel(k)),
        falOn ? h("div.col", { style: { gap: "8px" } }, h("b", {}, "Где использовать"), field("Видео", useSel("video")), field("Картинки", useSel("image")), field("Правка картинок", useSel("image_edit"))) : null,
        h("p.dim", { style: { fontSize: "12px" } }, `Цены: ${pr.models.some(m => m.live) ? "живые, с fal.ai" : "каталог MaisonAI, проверено " + pr.checked}. fal.ai берёт деньги только за успешно созданные файлы.`))),
    h("div.panel.col", { style: { marginTop: "16px" } }, h("h3", { style: { margin: 0 } }, "Журнал платных запросов"),
      r.rows.length ? h("div.tbl-wrap", {}, h("table.cost-table", {}, h("thead", {}, h("tr", {}, ...["Когда", "Задача", "Модель", "Объём", "Сумма", "Статус"].map(t => h("th", {}, t)))),
        h("tbody", {}, ...r.rows.map(x => h("tr", {}, h("td", {}, fmtDate(x.created)), h("td", {}, x.job_title || x.what), h("td.dim", {}, x.model.split("/").slice(1, 3).join("/")),
          h("td.num", {}, `${x.units} ${x.unit}`), h("td.num", {}, USD(x.usd)), h("td", {}, h("span.tag." + (st_[x.status]?.[0] || ""), { title: x.note || "" }, st_[x.status]?.[1] || x.status))))))) : h("div.dim", {}, "Платных запросов ещё не было.")),
    h("div.panel.col", { style: { marginTop: "16px" } }, h("h3", { style: { margin: 0 } }, "Счётчик запросов к ИИ"),
      r.calls.length ? h("div.tbl-wrap", {}, h("table.cost-table", {}, h("thead", {}, h("tr", {}, ...["День", "Сервис", "Успешно", "Ошибки"].map(t => h("th", {}, t)))),
        h("tbody", {}, ...r.calls.slice(0, 60).map(x => h("tr", {}, h("td", {}, x.day), h("td", {}, st.providers[x.provider]?.label || x.provider), h("td.num", {}, x.ok), h("td.num", {}, x.err)))))) : h("div.dim", {}, "Запросов пока не было.")));
}
