import { state, api, h, $, $$, icon, btn, toast, fail, modal, tc, fmtDate, onJobs, loadProviders, providerBadge, go, handoff, field } from "./lib.js";
import * as fx from "./fx.js";
let orb = null;

const ROUTES = {
  "": ["home", "Главная", "home"], assistant: ["assistant", "Ассистент", "chat"], script: ["script", "Сценарии", "script"],
  voice: ["voice", "Голос", "mic"], image: ["image", "Изображения", "image"], video: ["video", "Видео", "film"],
  recreate: ["recreate", "Воссоздание стиля", "layers"], analyze: ["analyze", "Анализ TikTok", "scan"], editor: ["editor", "Редактор", "cut"],
  projects: ["projects", "Проекты", "folder"], project: ["projects", "Проект", "folder"], history: ["projects", "История", "clock"],
  favorites: ["projects", "Избранное", "star"], settings: ["settings", "Настройки", "gear"],
  intel: ["intel", "TikTok Intelligence", "radar"], menu: ["", "Ещё", "menu"],
};
const NAV = [["Студия", ["", "intel", "assistant"]], ["Создание", ["script", "voice", "image", "video", "editor"]], ["Библиотека", ["projects", "history", "favorites"]], ["", ["settings"]]];
const TABBAR = ["", "intel", "assistant", "video", "menu"];
const modules = {};
let cleanup = null;

// ---------- старт ----------
// «Пульс»: пока окно открыто, программа на компьютере не выключается
setInterval(() => { if (!document.hidden) fetch("/api/info", { cache: "no-store" }).catch(() => { }); }, 20000);
document.addEventListener("visibilitychange", () => { if (!document.hidden) fetch("/api/info", { cache: "no-store" }).catch(() => { }); });

async function boot() {
  if ("serviceWorker" in navigator && location.protocol === "http:" && !["127.0.0.1", "localhost"].includes(location.hostname)) { }  // iOS: офлайн-кэш не нужен
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => { });
  fx.init();
  try { orb = await import("./orb.js"); if (!orb.init()) orb = null; } catch (e) { console.warn("3D недоступно", e); orb = null; }
  intro();
  let st;
  try { st = await api("/api/auth/status"); } catch (e) { setBody(h("div.page", {}, h("div.err", {}, e.message))); return; }
  state.local = st.local;
  if (!st.logged_in) return authScreen(st.has_users, st);
  state.user = st.user;
  await shell();
}
window.addEventListener("mai:logout", () => { state.user = null; authScreen(true); });

function intro() {
  if (sessionStorage.getItem("mai_intro") || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  sessionStorage.setItem("mai_intro", "1");
  const word = h("span.word"), ai = h("span.ai"), cur = h("span.cur");
  const el = h("div.intro", {}, h("div.orb-slot", { "data-orb": "intro" }), h("div.logo", {}, h("span.mk"), h("span", {}, word, ai, cur)));
  document.body.append(el);
  const W = "MAISON", A = "AI"; let i = 0;
  const step = () => {
    if (i < W.length) word.textContent = W.slice(0, ++i);
    else if (i < W.length + A.length) { ai.textContent = A.slice(0, ++i - W.length); }
    else { setTimeout(() => { el.querySelector(".orb-slot").removeAttribute("data-orb"); el.style.opacity = "0"; setTimeout(() => el.remove(), 600); }, 900); return; }
    setTimeout(step, 70 + Math.random() * 50);
  };
  setTimeout(step, 700);
}

function setBody(...nodes) {   // 3D-холст и свет за курсором живут постоянно
  const keep = ["#orb", "#spot", ".intro"].map(s => document.querySelector(s)).filter(Boolean);
  document.body.replaceChildren(...keep, ...nodes);
}
const logo = () => h("div.logo", {}, h("span.mk", { "data-orb": "logo" }), h("span.word", {}, "MAISON", h("span.ai", {}, "AI")));

// ---------- вход и регистрация ----------
function authScreen(hasUsers, st = {}) {
  let mode = hasUsers ? "login" : "register";
  const root = h("div.auth");
  const draw = () => {
    const u = h("input.in", { autocomplete: "username", required: true, minLength: 3, maxLength: 32, autocapitalize: "none", spellcheck: false });
    const p = h("input.in", { type: "password", autocomplete: mode === "login" ? "current-password" : "new-password", required: true, minLength: mode === "login" ? 1 : 8 });
    const n = h("input.in", { autocomplete: "nickname", maxLength: 40 });
    const inv = h("input.in", { autocomplete: "off", maxLength: 20, autocapitalize: "characters", placeholder: "Например: 7F3A9C21" });
    const rem = h("input", { type: "checkbox", checked: true });
    const err = h("div");
    const submit = h("button.btn.pri.wide", { type: "submit" }, mode === "login" ? "Войти" : "Создать аккаунт");
    const form = h("form", {
      onsubmit: async e => {
        e.preventDefault(); err.replaceChildren(); submit.disabled = true;
        try {
          if (mode === "login") await api("/api/auth/login", { body: { username: u.value.trim(), password: p.value, remember: rem.checked } });
          else await api("/api/auth/register", { body: { username: u.value.trim(), password: p.value, display_name: n.value.trim(), invite: inv.value.trim() } });
          location.reload();
        } catch (x) { err.replaceChildren(h("div.err", {}, x.message)); submit.disabled = false; }
      }
    },
      h("h2", {}, mode === "login" ? "Вход" : "Регистрация"),
      mode === "register" ? field("Как к вам обращаться", n) : null,
      mode === "register" && st.invite_needed ? field("Код приглашения", inv, "выдаёт владелец") : null,
      field("Логин", u, mode === "register" ? "3–32 символа" : ""),
      field("Пароль", p, mode === "register" ? "не короче 8 символов" : ""),
      mode === "login" ? h("label.row", { style: { fontSize: "13px", color: "var(--tx2)" } }, rem, "Запомнить меня") : null,
      err, submit,
      h("button.btn.ghost", { type: "button", onclick: () => { mode = mode === "login" ? "register" : "login"; draw(); } }, mode === "login" ? "Нет аккаунта? Зарегистрироваться" : "Уже есть аккаунт? Войти"));
    root.replaceChildren(
      h("div.art", {}, h("div.lines"), logo(), h("div.orb-slot", { "data-orb": "auth" }), h("div", { style: { position: "relative" } }, h("div.big", {}, "От идеи", h("br"), h("span", {}, "до готового"), h("br"), "видео."),
        h("p.muted", { style: { marginTop: "18px", maxWidth: "460px" } }, "Сценарии, озвучка, изображения, видео, анализ роликов и монтаж — в одной студии. Работает на бесплатных и локальных моделях ИИ."))),
      h("div.frm", {}, form));
    setTimeout(() => (mode === "register" ? n : u).focus(), 50);
  };
  draw();
  setBody(root);
}

// ---------- оболочка ----------
async function shell() {
  const pid = localStorage.getItem("mai_project");
  if (pid) { try { state.project = await api("/api/projects/" + pid); } catch { localStorage.removeItem("mai_project"); } }
  loadProviders().catch(() => { });
  const nav = h("nav.nav", { "aria-label": "Разделы" });
  for (const [grp, keys] of NAV) {
    if (grp) nav.append(h("div.grp.mono-up", {}, grp));
    for (const k of keys) nav.append(h("a", { href: "#/" + k, "data-r": k, class: k === "intel" ? "key" : "", style: { "--i": nav.children.length } }, icon(ROUTES[k][2]), h("span", {}, ROUTES[k][1]), k === "intel" ? h("span.pill", {}, "AI") : null));
  }
  const initials = (state.user.display_name || state.user.username).trim()[0]?.toUpperCase() || "M";
  const side = h("aside.side", {}, logo(), nav, h("div.me", {}, h("div.av", {}, initials), h("div.nm", {}, state.user.display_name), btn("", logout, "ghost sm icon", "logout", { title: "Выйти", "aria-label": "Выйти" })));
  const crumb = h("div.crumb");
  const projPick = h("button.proj-pick", { type: "button", onclick: pickProject, title: "Текущий проект" }, icon("folder"), h("span", {}, ""));
  const monitor = h("button.monitor", { type: "button", onclick: () => go("#/history"), title: "Задачи" }, h("span.dot"), h("span.tc", {}, "00:00:00:00"), h("span.lbl", {}, "Нет активных задач"));
  // выдвижное меню для iPad и iPhone
  const drawerNav = nav.cloneNode(true);
  const drawer = h("div.drawer", { "aria-hidden": "true", onclick: e => { if (e.target === drawer || e.target.closest("a")) closeDrawer(); } },
    h("div.drawer-panel", {}, h("div.row", { style: { padding: "14px 16px", borderBottom: "1px solid var(--line)" } }, h("div.logo", {}, h("span.word", {}, "MAISON", h("span.ai", {}, "AI"))), h("div", { style: { flex: 1 } }), btn("", () => closeDrawer(), "ghost sm icon", "x", { "aria-label": "Закрыть меню" })),
      drawerNav, h("div.me", {}, h("div.av", {}, initials), h("div.nm", {}, state.user.display_name), btn("", logout, "ghost sm icon", "logout", { title: "Выйти" }))));
  const openDrawer = () => { drawer.classList.add("open"); drawer.setAttribute("aria-hidden", "false"); };
  const closeDrawer = () => { drawer.classList.remove("open"); drawer.setAttribute("aria-hidden", "true"); };
  const menuBtn = btn("", openDrawer, "ghost icon menu-btn", "menu", { "aria-label": "Меню" });
  const top = h("header.top", {}, menuBtn, h("div.logo.hidden", {}, h("span.mk", { "data-orb": "logo" })), crumb, h("div.sp"), projPick, monitor);
  const main = h("main", { id: "main" });
  const tabbar = h("nav.tabbar", { "aria-label": "Быстрые разделы" }, ...TABBAR.map(k => k === "menu"
    ? h("a", { href: "#", onclick: e => { e.preventDefault(); openDrawer(); } }, icon("menu"), "Ещё")
    : h("a", { href: "#/" + k, "data-r": k }, icon(ROUTES[k][2]), k === "intel" ? "Intelligence" : ROUTES[k][1].split(" ")[0])));
  setBody(h("div", { id: "app" }, side, top, main), tabbar, drawer);
  setProjectLabel();
  // таймкод активных задач (реальное время выполнения)
  let liveT0 = null;
  const upd = m => {
    const live = [...m.values()].filter(j => j.status === "queued" || j.status === "running");
    monitor.classList.toggle("live", live.length > 0);
    $(".lbl", monitor).textContent = live.length ? (live.length > 1 ? `${live.length} задачи · ` : "") + (live[0].message || live[0].title) : "Нет активных задач";
    if (live.length && !liveT0) liveT0 = Math.min(...live.map(j => j.t0 || Date.now()));
    if (!live.length) liveT0 = null;
    for (const j of m.values()) if (j.status === "done" && !j._seen) { j._seen = true; toast("Готово: " + (j.title || "")); orb?.pulse(); }
    orb?.setBusy(live.length > 0);
  };
  onJobs(upd);
  setInterval(() => { $(".tc", monitor).textContent = liveT0 ? tc((Date.now() - liveT0) / 1000) : "00:00:00:00"; }, 40);
  // подхватываем задачи, запущенные до перезагрузки
  api("/api/jobs?limit=20").then(js => { const { trackJob } = window.__lib; js.filter(j => j.status === "queued" || j.status === "running").forEach(j => trackJob(j.id, j.title)); }).catch(() => { });
  window.addEventListener("hashchange", route);
  route();
}

function setProjectLabel() { $(".proj-pick span").textContent = state.project ? state.project.title : "Без проекта"; }
export function setProject(p) {
  state.project = p; if (p) localStorage.setItem("mai_project", p.id); else localStorage.removeItem("mai_project");
  setProjectLabel(); window.dispatchEvent(new Event("mai:project"));
}
window.__setProject = setProject;

async function pickProject() {
  const list = h("div.list", {}, h("div.dim", {}, "Загрузка…"));
  const name = h("input.in", { placeholder: "Название нового проекта", maxLength: 120 });
  const create = async () => {
    try { const p = await api("/api/projects", { body: { title: name.value.trim() || "Новый проект" } }); setProject(p); m.close(); toast("Проект создан"); } catch (e) { fail(e); }
  };
  name.onkeydown = e => { if (e.key === "Enter") create(); };
  const m = modal("Проект", h("div.col", {}, h("p.muted", {}, "Всё, что вы создаёте, сохраняется в текущий проект. Ассистент помнит переписку внутри проекта."),
    h("div.row", {}, h("div", { style: { flex: "1" } }, name), btn("Создать", create, "pri", "plus")),
    h("div.mono-up", {}, "Недавние проекты"), list), { size: "sm", foot: [btn("Работать без проекта", () => { setProject(null); m.close(); }, "ghost")] });
  try {
    const ps = await api("/api/projects");
    list.replaceChildren(...(ps.length ? ps.slice(0, 30).map(p => h("div.it", { onclick: async () => { setProject(await api("/api/projects/" + p.id)); m.close(); } },
      h("div.th", { style: { backgroundImage: p.cover_url ? `url("${p.cover_url}")` : "" } }), h("div.t", {}, p.title), h("span.dim", {}, fmtDate(p.updated)))) : [h("div.dim", {}, "Проектов пока нет")]));
  } catch (e) { list.replaceChildren(h("div.err", {}, e.message)); }
}

async function logout() { try { await api("/api/auth/logout", { body: {} }); } catch { } localStorage.removeItem("mai_project"); location.hash = "#/"; location.reload(); }

async function route() {
  const [k, arg] = location.hash.replace(/^#\/?/, "").split("/");
  const r = ROUTES[k] ?? ROUTES[""];
  $$("[data-r]").forEach(a => a.classList.toggle("on", a.dataset.r === k || (k === "project" && a.dataset.r === "projects") || (["analyze", "recreate"].includes(k) && a.dataset.r === "intel")));
  $(".crumb").textContent = r[1];
  document.title = r[1] + " · MaisonAI";
  if (cleanup) { try { cleanup(); } catch { } cleanup = null; }
  const main = $("#main"); main.scrollTop = 0;
  const page = h("div.page"); main.replaceChildren(page);
  try {
    if (r[0] === "home") cleanup = await home(page);
    else {
      modules[r[0]] ||= await import(`./${r[0]}.js`);
      cleanup = await modules[r[0]].render(page, k, arg);
    }
  } catch (e) { console.error(e); page.replaceChildren(h("div.err", {}, "Не удалось открыть раздел: " + e.message)); }
}

// ---------- главная ----------
async function home(page) {
  const hr = new Date().getHours();
  const greet = hr < 5 ? "Доброй ночи" : hr < 12 ? "Доброе утро" : hr < 18 ? "Добрый день" : "Добрый вечер";
  const ta = h("textarea", { placeholder: "Например: «Хочу вирусный ролик про путешествия» или «Сделай видео в стиле этого ролика, но в чёрном костюме и другом городе»", "aria-label": "Что создаём сегодня?" });
  const send = () => { const v = ta.value.trim(); if (!v) { ta.focus(); return; } handoff.set("ask", v); go("#/assistant"); };
  ta.onkeydown = e => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) send(); };
  const quick = [["intel/analyze", "TikTok Intelligence", "Загрузите примеры — MaisonAI изучит стиль, соберёт Visual DNA и поможет снять новое", "radar", "wide"],
    ["intel/dna", "Visual DNA", "Профили стилей для повторного использования", "dna"],
    ["video", "Видео", "Текст или картинка → ролик 9:16", "film"], ["image", "Изображение", "Генерация и правка: одежда, причёска, фон", "image"],
    ["script", "Сценарий", "Хук, текст озвучки, сцены, хештеги", "script"], ["voice", "Озвучка", "Украинские, русские и другие голоса", "mic"],
    ["editor", "Редактор", "Обрезка, склейка, субтитры, экспорт", "cut"]];
  const counters = h("div.counters", {}, ...["Проекты", "Видео", "Изображения", "Озвучки", "Сценарии"].map(l => h("div", {}, h("b", {}, "—"), h("span.mono-up", {}, l))));
  const recent = h("div.list", {}, h("div.dim", {}, "Загрузка…"));
  const caps = h("div.caps");
  page.append(
    h("div.hero", {}, h("div", {},
      h("div.hello", {}, h("h1", {}, `${greet},`, h("br"), state.user.display_name), h("span.sub", {}, new Date().toLocaleDateString("ru-RU", { weekday: "long", day: "numeric", month: "long" }))),
    h("div.prompt-box", {}, h("div.mono-up", { style: { padding: "16px 22px 0" } }, "Что создаём сегодня?"), ta,
      h("div.pbar", {}, h("span.dim", { style: { fontSize: "12px" } }, "Ассистент разберёт задачу и предложит шаги"), h("div", { style: { flex: "1" } }), btn("Начать", send, "pri", "arrow")))),
      h("div.orb-slot", { "data-orb": "hero", "aria-hidden": "true" })),
    h("div.tiles", {}, ...quick.map(([r, n, d, ic, w], i) => h("a.tile" + (w ? ".wide" : ""), { href: "#/" + r, style: { "--i": i } }, icon(ic), h("span.n", {}, n), h("p", {}, d), icon("arrow", "ix")))),
    h("div.dash", {},
      h("div.col", {}, counters, h("div.panel", {}, h("div.row", { style: { marginBottom: "6px" } }, h("h3", { style: { margin: 0, flex: 1 } }, "Последние проекты"), btn("Все", () => go("#/projects"), "sm ghost")), recent)),
      h("div.panel", {}, h("h3", {}, "Подключённые модели"), caps, btn("Настроить", () => go("#/settings/providers"), "sm wide", "gear", { style: { marginTop: "12px" } }))));
  api("/api/stats").then(s => { const v = [s.projects, s.videos, s.images, s.audio, s.scripts]; $$("b", counters).forEach((b, i) => fx.countUp(b, v[i])); }).catch(() => { });
  api("/api/projects").then(ps => {
    recent.replaceChildren(...(ps.length ? ps.slice(0, 6).map(p => h("div.it", { onclick: () => go("#/project/" + p.id) }, h("div.th", { style: { backgroundImage: p.cover_url ? `url("${p.cover_url}")` : "" } }),
      h("div.t", {}, p.title), h("span.dim", {}, `${p.n_assets} файлов · ${fmtDate(p.updated)}`))) : [h("div.empty", {}, "Проектов пока нет. Создайте первый в верхней панели.")]));
  }).catch(e => recent.replaceChildren(h("div.err", {}, e.message)));
  loadProviders(true).then(s => {
    caps.replaceChildren(...["text", "image", "image_edit", "tts", "video", "video_understanding", "stt"].map(c => h("div.cap", {}, h("span.muted", {}, s.cap_labels[c]), providerBadge(c))));
  }).catch(() => { });
  setTimeout(() => ta.focus(), 100);
}

import * as lib from "./lib.js";
window.__lib = lib;
boot();
