// MaisonAI — общие функции интерфейса: запросы, элементы, иконки, задачи, окна.
// replaceChildren/append пропускают пустые значения (null, false) — удобно для условных элементов
for (const m of ["replaceChildren", "append", "prepend"]) {
  const orig = Element.prototype[m];
  Element.prototype[m] = function (...k) { return orig.apply(this, k.flat().filter(x => x !== null && x !== undefined && x !== false)); };
}
export const state = { user: null, local: true, project: null, providers: null, jobs: new Map(), voices: null };

// ---------- запросы к серверу ----------
export async function api(path, opt = {}) {
  const o = { method: opt.method || (opt.body !== undefined ? "POST" : "GET"), headers: {}, credentials: "same-origin" };
  if (opt.body instanceof FormData) o.body = opt.body;
  else if (opt.body !== undefined) { o.headers["Content-Type"] = "application/json"; o.body = JSON.stringify(opt.body); }
  let r;
  try { r = await fetch(path, o); }
  catch { throw new Error("Нет связи с программой MaisonAI. Убедитесь, что она запущена на компьютере."); }
  if (r.status === 401 && !path.startsWith("/api/auth")) { location.hash = "#/"; window.dispatchEvent(new Event("mai:logout")); throw new Error("Требуется вход"); }
  const ct = r.headers.get("content-type") || "";
  const data = ct.includes("json") ? await r.json() : await r.text();
  if (!r.ok) {
    let msg = typeof data === "string" ? data : data.detail;
    if (Array.isArray(msg)) msg = "Проверьте заполнение полей: " + msg.map(e => (e.loc || []).slice(-1)[0]).join(", ");
    throw new Error(msg || `Ошибка ${r.status}`);
  }
  return data;
}

// ---------- создание элементов ----------
export function h(tag, attrs = {}, ...kids) {
  const [t, ...cls] = tag.split(".");
  const e = document.createElement(t || "div");
  if (cls.length) e.className = cls.join(" ");
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k.startsWith("on")) e.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === "class") e.className += (e.className ? " " : "") + v;
    else if (k === "style" && typeof v === "object") Object.assign(e.style, v);
    else if (k === "html") e.innerHTML = v;
    else if (k === "value") e.value = v;
    else if (k in e && typeof v !== "string") e[k] = v;
    else e.setAttribute(k, v === true ? "" : v);
  }
  for (const k of kids.flat(Infinity)) if (k !== null && k !== undefined && k !== false) e.append(k instanceof Node ? k : document.createTextNode(String(k)));
  return e;
}
export const $ = (s, r = document) => r.querySelector(s);
export const $$ = (s, r = document) => [...r.querySelectorAll(s)];
export const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// ---------- иконки: единая библиотека Lucide (одинаковая толщина линий, анимации при наведении) ----------
import { ICONS } from "./icons.js";
export function icon(name, cls = "") {
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  s.setAttribute("viewBox", "0 0 24 24"); s.setAttribute("class", "i " + cls); s.setAttribute("aria-hidden", "true"); s.dataset.i = name;
  s.innerHTML = ICONS[name] || ICONS.more;
  for (const el of s.children) el.setAttribute("pathLength", "1");
  return s;
}
export const btn = (label, onClick, cls = "", ic = null, attrs = {}) => h("button.btn" + (cls ? "." + cls.split(" ").join(".") : ""), { type: "button", onclick: onClick, ...attrs }, ic ? icon(ic) : null, label || null);

// ---------- уведомления ----------
export function toast(msg, err = false) {
  let box = $(".toasts"); if (!box) { box = h("div.toasts"); document.body.append(box); }
  const t = h("div.toast" + (err ? ".err" : ""), {}, msg); box.append(t);
  setTimeout(() => t.remove(), err ? 7000 : 3500);
}
export const fail = e => toast(e?.message || String(e), true);

// ---------- модальные окна ----------
export function modal(title, body, { foot = null, size = "", onClose = null } = {}) {
  const close = () => { bg.remove(); document.removeEventListener("keydown", key); onClose && onClose(); };
  const key = e => { if (e.key === "Escape") close(); };
  const bg = h("div.modal-bg", { onclick: e => { if (e.target === bg) close(); } },
    h("div.modal" + (size ? "." + size : ""), { role: "dialog", "aria-modal": "true", "aria-label": title },
      h("div.mh", {}, h("b", {}, title), btn("", close, "ghost icon sm", "x", { "aria-label": "Закрыть" })),
      h("div.mb", {}, body), foot ? h("div.mf", {}, foot) : null));
  document.addEventListener("keydown", key); document.body.append(bg);
  return { close, el: bg };
}
export function confirmBox(text, okLabel = "Удалить") {
  return new Promise(res => {
    let m;
    const ok = btn(okLabel, () => { m.close(); res(true); }, "pri");
    m = modal("Подтверждение", h("p", {}, text), { size: "sm", foot: [btn("Отмена", () => { m.close(); res(false); }), ok], onClose: () => res(false) });
  });
}

// ---------- формат ----------
export const tc = sec => { sec = Math.max(0, sec || 0); const h_ = Math.floor(sec / 3600), m = Math.floor(sec % 3600 / 60), s = Math.floor(sec % 60), f = Math.floor((sec % 1) * 25); return [h_, m, s, f].map(x => String(x).padStart(2, "0")).join(":"); };
export const mmss = sec => { sec = Math.max(0, sec || 0); return Math.floor(sec / 60) + ":" + String(Math.floor(sec % 60)).padStart(2, "0"); };
export const fmtDate = s => { if (!s) return ""; const d = typeof s === "number" ? new Date(s * 1000) : new Date(s.replace(" ", "T") + "Z"); return d.toLocaleString("ru-RU", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }); };
export const fmtSize = b => b > 1e6 ? (b / 1e6).toFixed(1) + " МБ" : Math.max(1, Math.round(b / 1e3)) + " КБ";
export function copy(text) { navigator.clipboard?.writeText(text).then(() => toast("Скопировано"), () => toast("Не удалось скопировать", true)); }
export function download(url, name) { const a = h("a", { href: url + (url.includes("?") ? "&" : "?") + "download=1", download: name || "" }); document.body.append(a); a.click(); a.remove(); }

// ---------- фоновые задачи ----------
const listeners = new Set();
export const onJobs = fn => { listeners.add(fn); return () => listeners.delete(fn); };
let pollTimer = null;
export function trackJob(id, title) {
  state.jobs.set(id, { id, title, status: "queued", progress: 0, message: "В очереди…", elapsed: 0, t0: Date.now() });
  emit(); schedule();
}
function emit() { for (const f of listeners) try { f(state.jobs); } catch (e) { console.error(e); } }
function schedule() { if (!pollTimer) pollTimer = setTimeout(poll, 700); }
async function poll() {
  pollTimer = null;
  const live = [...state.jobs.values()].filter(j => j.status === "queued" || j.status === "running");
  await Promise.all(live.map(async j => {
    try { const d = await api("/api/jobs/" + j.id); d.t0 = j.t0; state.jobs.set(j.id, d); } catch { }
  }));
  emit();
  if ([...state.jobs.values()].some(j => j.status === "queued" || j.status === "running")) schedule();
}
export function waitJob(id) {
  return new Promise((res, rej) => {
    const off = onJobs(m => {
      const j = m.get(id); if (!j) return;
      if (j.status === "done") { off(); res(j.result); }
      else if (j.status === "error") { off(); rej(new Error(j.error || "Ошибка")); }
      else if (j.status === "cancelled") { off(); rej(new Error("Отменено")); }
    });
  });
}
// Запуск инструмента + карточка прогресса в указанном месте страницы
export async function runTool(path, body, box, title) {
  if (state.project && body.project_id === undefined) body.project_id = state.project.id;
  const { job } = await api(path, { body });
  trackJob(job, title);
  if (box) jobCard(box, job, title);
  return waitJob(job);
}
export function jobCard(box, id, title) {
  const tcEl = h("span.tc", {}, "00:00:00:00"), msg = h("div.msg", {}, "В очереди…"), bi = h("i", { style: { width: "0%" } }), bar = h("div.bar.ind", {}, bi);
  const cancel = btn("Отменить", () => api(`/api/jobs/${id}/cancel`, { body: {} }).catch(fail), "sm ghost");
  const viz = h("div.ai-viz", { "aria-hidden": "true" }, ...Array.from({ length: 28 }, (_, k) => h("i", { style: { "--k": k, "--h": (35 + Math.round(Math.abs(Math.sin(k * 1.7)) * 60)) + "%" } })));
  const card = h("div.jobcard.live", {}, h("div.hd", {}, h("span.dot"), h("b", {}, title || "Генерация"), tcEl), msg, viz, bar, h("div.row.end", { style: { marginTop: "8px" } }, cancel));
  box.replaceChildren(card);
  const t0 = Date.now();
  const tick = setInterval(() => { tcEl.textContent = tc((Date.now() - t0) / 1000); }, 40);
  const off = onJobs(m => {
    const j = m.get(id); if (!j) return;
    msg.textContent = j.message || "";
    if (j.progress > 0) { bar.classList.remove("ind"); bi.style.width = Math.round(j.progress * 100) + "%"; }
    if (["done", "error", "cancelled"].includes(j.status)) {
      clearInterval(tick); off();
      if (j.status === "done") card.remove();
      else box.replaceChildren(h("div.err", {}, j.status === "cancelled" ? "Отменено." : j.error));
    }
  });
}

// ---------- медиа ----------
export function mediaEl(a, { controls = true, autoplay = false } = {}) {
  if (a.kind === "image") return h("img", { src: a.url, alt: a.name, loading: "lazy" });
  if (a.kind === "video") return h("video", { src: a.url, controls, playsInline: true, preload: "metadata", autoplay, muted: autoplay, loop: autoplay });
  if (a.kind === "audio") return h("audio", { src: a.url, controls, preload: "metadata" });
  return h("div.dim", {}, a.name);
}
export function thumbUrl(a) { return a.kind === "video" ? a.url + "?thumb=1" : a.url; }

// Загрузка файлов
export async function uploadFiles(files, onEach) {
  const out = [];
  for (const f of files) {
    const fd = new FormData(); fd.append("file", f); if (state.project) fd.append("project_id", state.project.id);
    try { const a = await api("/api/assets/upload", { body: fd }); out.push(a); onEach && onEach(a); }
    catch (e) { fail(e); }
  }
  return out;
}
export function dropZone(label, accept, onFiles, multiple = false) {
  const inp = h("input", { type: "file", accept, multiple });
  const z = h("label.drop", {}, icon("upload"), h("div", { style: { marginTop: "6px" } }, label), h("div.dim", { style: { fontSize: "12px" } }, "Нажмите или перетащите файл сюда"), inp);
  inp.onchange = () => { if (inp.files.length) onFiles([...inp.files]); inp.value = ""; };
  z.ondragover = e => { e.preventDefault(); z.classList.add("over"); };
  z.ondragleave = () => z.classList.remove("over");
  z.ondrop = e => { e.preventDefault(); z.classList.remove("over"); if (e.dataTransfer.files.length) onFiles([...e.dataTransfer.files]); };
  return z;
}

// Выбор файла из библиотеки
export function pickAsset(kinds, title = "Выберите файл") {
  return new Promise(async res => {
    let chosen = null;
    const grid = h("div.gallery");
    const load = async (onlyProject) => {
      grid.replaceChildren(h("div.dim", {}, "Загрузка…"));
      try {
        const q = new URLSearchParams({ kind: kinds.join(","), limit: 200 }); if (onlyProject && state.project) q.set("project_id", state.project.id);
        const items = await api("/api/assets?" + q);
        grid.replaceChildren(...(items.length ? items.map(a => assetCard(a, { onClick: () => { chosen = a; m.close(); } })) : [h("div.empty", {}, "Здесь пока пусто. Загрузите файл выше.")]));
      } catch (e) { grid.replaceChildren(h("div.err", {}, e.message)); }
    };
    const accept = kinds.map(k => ({ image: "image/*", video: "video/*", audio: "audio/*" }[k])).filter(Boolean).join(",");
    const seg = h("div.seg", {}, ...[["Все файлы", false], ["Текущий проект", true]].map(([l, v], i) => h("button", { class: i === 0 ? "on" : "", disabled: v && !state.project, onclick: e => { $$("button", seg).forEach(b => b.classList.remove("on")); e.currentTarget.classList.add("on"); load(v); } }, l)));
    const body = h("div.col", {}, dropZone("Загрузить с устройства", accept, async fs => { const a = await uploadFiles(fs); if (a[0]) { chosen = a[0]; m.close(); } }), seg, grid);
    const m = modal(title, body, { onClose: () => res(chosen) });
    load(false);
  });
}

export function assetCard(a, { onClick, actions = [], square = false } = {}) {
  const bgUrl = a.kind === "image" || a.kind === "video" ? `url("${thumbUrl(a)}")` : "";
  const md = a.kind === "audio" ? h("div.media", { style: { display: "grid", placeItems: "center", aspectRatio: "1" } }, icon("volume"))
    : h("div.media", { style: { backgroundImage: bgUrl } });
  return h("div.card" + (square ? ".sq" : ""), { onclick: onClick, title: a.name },
    md, h("span.badge", {}, { image: "фото", video: "видео", audio: "аудио", script: "сценарий" }[a.kind] || a.kind),
    actions.length ? h("div.acts", { onclick: e => e.stopPropagation() }, ...actions) : null,
    h("div.cap", {}, a.favorite ? "★ " : "", a.name));
}

export function asView(a) {
  const v = h("div.viewer", {}, mediaEl(a));
  return v;
}

export function previewModal(a, extra = []) {
  modal(a.name, h("div.col", {}, h("div.viewer", {}, mediaEl(a, { controls: true })), a.meta?.prompt ? h("div.copy-block", {}, a.meta.prompt, btn("", () => copy(a.meta.prompt), "sm icon ghost", "copy")) : null,
    a.meta?.provider ? h("div.dim", {}, "Сделано: " + a.meta.provider + (a.meta.ai_video === false ? " · монтаж, не нейросетевое видео" : "")) : null),
    { foot: [...extra, btn("Скачать", () => download(a.url, a.name), "", "download")] });
}

export async function toggleFav(a, onDone) {
  try { const r = await api("/api/assets/" + a.id, { method: "PATCH", body: { favorite: !a.favorite } }); a.favorite = r.favorite; toast(r.favorite ? "Добавлено в избранное" : "Убрано из избранного"); onDone && onDone(r); }
  catch (e) { fail(e); }
}
export async function deleteAsset(a, onDone) {
  if (!await confirmBox(`Удалить «${a.name}»? Файл будет удалён навсегда.`)) return;
  try { await api("/api/assets/" + a.id, { method: "DELETE" }); toast("Удалено"); onDone && onDone(); } catch (e) { fail(e); }
}

// Поле формы
export function field(label, input, hint) { return h("label.f", {}, h("span", {}, h("span", {}, label), hint ? h("span.dim", {}, hint) : null), input); }
export function select(options, value, attrs = {}) {
  return h("select.in", attrs, ...options.map(o => { const [v, l] = Array.isArray(o) ? o : [o, o]; return h("option", { value: v, selected: v === value }, l); }));
}
export function segmented(options, value, onChange, disabled = {}) {
  const s = h("div.seg", { role: "radiogroup" });
  s.value = value;
  for (const o of options) {
    const [v, l] = Array.isArray(o) ? o : [o, o];
    s.append(h("button", { type: "button", class: v === value ? "on" : "", disabled: !!disabled[v], title: disabled[v] || "", role: "radio", "aria-checked": v === value ? "true" : "false",
      onclick: e => { $$("button", s).forEach(b => { b.classList.remove("on"); b.setAttribute("aria-checked", "false"); }); e.currentTarget.classList.add("on"); e.currentTarget.setAttribute("aria-checked", "true"); s.value = v; onChange && onChange(v); } }, l));
  }
  return s;
}
export const RATIOS = [["9:16", "9:16"], ["1:1", "1:1"], ["4:5", "4:5"], ["16:9", "16:9"]];
export const LANGS = [["uk", "Українська"], ["ru", "Русский"], ["en", "English"], ["de", "Deutsch"], ["pl", "Polski"], ["es", "Español"], ["fr", "Français"]];

// Передача данных между страницами (например, сценарий → озвучка)
export const handoff = { set(k, v) { sessionStorage.setItem("mai_" + k, JSON.stringify(v)); }, take(k) { try { const v = JSON.parse(sessionStorage.getItem("mai_" + k)); sessionStorage.removeItem("mai_" + k); return v; } catch { return null; } } };
export const go = hash => { location.hash = hash; };

export async function loadProviders(force = false) {
  if (!state.providers || force) state.providers = await api("/api/settings/providers");
  return state.providers;
}
export function providerBadge(cap) {
  const s = state.providers; if (!s) return null;
  const pid = s.active[cap];
  if (!pid) return h("span.tag.paid", {}, "не настроено");
  const p = s.providers[pid];
  const lbl = { free: "бесплатно", free_quota: "бесплатный лимит", local: "локально", paid_credits: "платные кредиты", unknown: "" }[p.cost];
  return h("span.tag" + (p.cost === "paid_credits" ? ".paid" : ".free"), { title: p.limits }, p.label + (lbl ? " · " + lbl : ""));
}

// Выбор сохранённого стиля Visual DNA (TikTok Intelligence) для генераторов
export function styleSelect(pre = "") {
  const s = h("select.in", {}, h("option", { value: "" }, "Без стиля"));
  api("/api/intel/styles").then(ss => {
    for (const x of ss) s.append(h("option", { value: x.id, selected: x.id === pre }, "Visual DNA: " + x.name));
    if (pre) s.value = pre;
    if (!ss.length) s.append(h("option", { value: "", disabled: true }, "Стили появятся после анализа в TikTok Intelligence"));
  }).catch(() => { });
  return s;
}
