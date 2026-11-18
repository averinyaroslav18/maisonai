// TikTok Intelligence — анализ роликов и скриншотов, Visual DNA, тренды, план ролика (blueprint), память стилей.
import { state, api, h, icon, btn, fail, toast, runTool, handoff, go, field, select, segmented, RATIOS, dropZone, uploadFiles, pickAsset, mmss, fmtDate, confirmBox, modal, copy, download, providerBadge, loadProviders, trackJob, waitJob, jobCard, onJobs } from "./lib.js";

const TABS = [["analyze", "Анализ", "scan"], ["dna", "Visual DNA", "dna"], ["create", "Создать по референсу", "wand"], ["trends", "Тренды", "trend"], ["score", "Оценка ролика", "target"], ["memory", "Память", "library"]];
const MODE = { video: "ИИ смотрел видео целиком", frames: "ИИ изучил ключевые кадры", images: "скриншоты" };
const KEEP = [["style", "Визуальный стиль"], ["lighting", "Освещение"], ["palette", "Палитра"], ["camera", "Камера"], ["editing", "Монтаж"], ["environment", "Окружение"],
  ["character", "Персонаж"], ["clothing", "Одежда"], ["hair", "Причёска"], ["hook", "Структура хука"], ["text_style", "Субтитры"], ["voice", "Озвучка"]];
const LANG = () => state.user.prefs?.language === "uk" ? "uk" : "ru";

export async function render(page, _k, tab) {
  tab = TABS.some(t => t[0] === tab) ? tab : "analyze";
  await loadProviders().catch(() => { });
  const memLine = h("div.row", { style: { gap: "6px" } });
  api("/api/intel/memory").then(m => memLine.replaceChildren(
    ...[["videos", "роликов"], ["styles", "стилей"], ["characters", "персонажей"], ["blueprints", "планов"]].map(([k, l]) => h("span.tag", {}, `${m[k]} ${l}`)))).catch(() => { });
  const tabs = h("div.tabs.intel-tabs", { role: "tablist" }, ...TABS.map(([id, l, ic]) => h("button", { type: "button", class: id === tab ? "on" : "", role: "tab", onclick: () => go("#/intel/" + id) }, icon(ic), l)));
  const body = h("div");
  page.append(
    h("div.ph.intel-head", {}, h("div", {}, h("div.mono-up", {}, "Ключевая функция"), h("h1", {}, "TikTok Intelligence"),
      h("p", {}, "Загрузите примеры роликов — MaisonAI изучит их визуальную структуру, соберёт профиль стиля и поможет создать новые оригинальные видео.")), h("div.sp"),
      h("div.col", { style: { alignItems: "flex-end", gap: "8px" } }, memLine, h("div.row", {}, providerBadge("video_understanding"), providerBadge("vision")))),
    tabs, body);
  const f = { analyze: tAnalyze, dna: tDna, create: tCreate, trends: tTrends, score: tScore, memory: tMemory }[tab];
  return f(body);
}

// ================= общие элементы =================
const swatches = (pal, big = false) => pal?.length ? h("div.swatches" + (big ? ".big" : ""), {}, ...pal.map(c => h("i", { style: { background: c.hex, flexGrow: Math.max(1, c.share) }, title: `${c.hex} · ${c.share}%` }))) : null;
const tagRow = tags => tags?.length ? h("div.chips", {}, ...tags.map(t => h("span.chip.static", {}, t))) : null;

function spark(vals, h_ = 40) {
  if (!vals?.length) return null;
  const W = 600, mx = Math.max(...vals) || 1;
  const pts = vals.map((v, i) => `${(i / (vals.length - 1 || 1)) * W},${h_ - (v / mx) * (h_ - 4) - 2}`).join(" ");
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${h_}`); svg.setAttribute("class", "spark"); svg.setAttribute("preserveAspectRatio", "none");
  svg.innerHTML = `<polyline points="${pts}" fill="none" stroke="#fff" stroke-width="1.5" vector-effect="non-scaling-stroke" class="draw"/>`;
  return svg;
}

function statusTag(v) {
  const t = { queued: ["в очереди", ""], running: ["анализ…", ".live"], done: [MODE[v.mode] ? "готово" : "готово", ".ok"], error: ["ошибка", ".paid"], cancelled: ["отменено", ""] }[v.status] || [v.status, ""];
  return h("span.tag" + t[1], {}, t[0]);
}

function videoCard(v, { onClick, selectable, selected, onToggle } = {}) {
  const card = h("div.card.icard" + (selected ? ".sel" : ""), { onclick: () => selectable ? onToggle(v, card) : onClick && onClick(v) },
    h("div.media", { style: { backgroundImage: v.thumb_url ? `url("${v.thumb_url}")` : "", aspectRatio: "3/4" } }),
    h("span.badge", {}, v.kind === "image" ? "скриншоты" : "видео"),
    selectable ? h("span.selmark", {}, icon("check")) : null,
    h("div.cap", {}, h("b", { style: { color: "var(--tx)", display: "block", overflow: "hidden", textOverflow: "ellipsis" } }, v.title || "Без названия"),
      h("div.row", { style: { gap: "6px", marginTop: "4px" } }, statusTag(v), v.measured?.duration ? h("span.dim", {}, mmss(v.measured.duration)) : null)),
    v.vision?.palette ? h("div", { style: { padding: "0 10px 10px" } }, swatches(v.vision.palette)) : null);
  return card;
}

async function loadVideos(status = "") { return api("/api/intel/videos" + (status ? "?status=" + status : "")); }

// ================= 1. Анализ =================
async function tAnalyze(body) {
  const queue = [];   // {asset} | {url} | {image}
  const qBox = h("div.queue");
  const links = h("textarea.in", { rows: 3, placeholder: "Ссылки на TikTok — по одной в строке\nhttps://www.tiktok.com/@…/video/…" });
  const lang = select([["ru", "Русский"], ["uk", "Українська"], ["en", "English"]], LANG());
  const focus = h("input.in", { placeholder: "Например: как построен хук, стиль одежды" });
  const drawQ = () => {
    qBox.replaceChildren(...queue.map((q, i) => h("div.qitem", {},
      q.asset ? h("div.th", { style: { backgroundImage: `url("${q.asset.kind === "video" ? q.asset.url + "?thumb=1" : q.asset.url}")` } }) : h("div.th.ic", {}, icon("link")),
      h("span", {}, q.asset ? q.asset.name : q.url), btn("", () => { queue.splice(i, 1); drawQ(); }, "sm icon ghost", "x", { "aria-label": "Убрать" }))));
    go_.replaceChildren(icon("sparkles"), `Анализировать${countAll() ? " (" + countAll() + ")" : ""}`);
  };
  const countAll = () => queue.length + links.value.split("\n").filter(x => x.trim()).length;
  links.oninput = drawQ;
  const zone = dropZone("Видео и скриншоты — можно сразу несколько", "video/*,image/*", async fs => { const as = await uploadFiles(fs); for (const a of as) queue.push({ asset: a }); drawQ(); }, true);
  const out = h("div.col");
  const go_ = btn("Анализировать", async () => {
    const urls = links.value.split("\n").map(x => x.trim()).filter(Boolean);
    const vids = queue.filter(q => q.asset?.kind === "video").map(q => ({ asset_id: q.asset.id }));
    const imgs = queue.filter(q => q.asset?.kind === "image").map(q => q.asset.id);
    if (!vids.length && !urls.length && !imgs.length) return toast("Добавьте видео, ссылки или скриншоты", true);
    go_.disabled = true;
    try {
      const r = await api("/api/intel/analyze", { body: { items: [...vids, ...urls.map(url => ({ url }))], image_ids: imgs, language: lang.value, focus: focus.value, project_id: state.project?.id ?? null } });
      r.items.forEach(it => trackJob(it.job, "Анализ"));
      toast(`Запущено анализов: ${r.items.length}. Можно работать в других разделах — результаты сохранятся.`);
      queue.length = 0; links.value = ""; drawQ(); refresh();
    } catch (e) { fail(e); }
    go_.disabled = false;
  }, "pri wide", "sparkles");
  const lib = btn("Из библиотеки", async () => { const a = await pickAsset(["video", "image"], "Видео или скриншот"); if (a) { queue.push({ asset: a }); drawQ(); } }, "sm ghost", "folder");
  const grid = h("div.gallery.igrid");
  body.append(h("div.split", {},
    h("div.panel.col.sticky", {}, h("h3", { style: { margin: 0 } }, "Что анализируем"), zone, lib, qBox, field("Ссылки TikTok", links), field("Язык", lang), field("На что обратить внимание", focus), go_,
      h("p.dim", { style: { fontSize: "12px" } }, "Ссылки работают для публичных роликов. Если TikTok не отдаёт видео — сохраните ролик в приложении («Поделиться» → «Сохранить видео») и загрузите файлом. Анализируйте ролики, которые вам разрешено использовать.")),
    h("div.col", {}, out, h("div.row", {}, h("div.mono-up", { style: { flex: 1 } }, "Проанализированные ролики"), btn("", refresh, "sm icon ghost", "refresh", { "aria-label": "Обновить" })), grid)));
  drawQ();
  async function refresh() {
    try {
      const vs = await loadVideos();
      grid.replaceChildren(...(vs.length ? vs.map(v => videoCard(v, { onClick: v => openVideo(v.id, out) })) : [h("div.empty", { style: { gridColumn: "1/-1" } }, "Здесь появятся результаты. Каждый анализ сохраняется в память — повторно анализировать не нужно.")]));
    } catch (e) { grid.replaceChildren(h("div.err", {}, e.message)); }
  }
  await refresh();
  const off = onJobs(m => { for (const j of m.values()) if (j.tool === undefined && ["done", "error"].includes(j.status) && !j._intelSeen) { j._intelSeen = true; refresh(); } });
  const t = setInterval(async () => { const vs = await loadVideos().catch(() => []); if (vs.some(v => ["queued", "running"].includes(v.status)) || grid.querySelector(".tag.live")) refresh(); }, 3000);
  const pre = handoff.take("intel_open"); if (pre) openVideo(pre, out);
  return () => { clearInterval(t); off(); };
}

// ---------- карточка анализа ----------
async function openVideo(id, box) {
  let v;
  try { v = await api("/api/intel/videos/" + id); } catch (e) { return fail(e); }
  const a = v.analysis || {}, m = v.measured || {}, vis = v.vision || {}, L = vis.light || {}, M = vis.motion || {};
  if (v.status !== "done") {
    const retry = v.status === "error" || v.status === "cancelled" ? btn("Повторить", async () => {
      try { const r = await api(`/api/intel/videos/${v.id}/retry`, { body: {} }); trackJob(r.job, "Повтор анализа"); toast("Анализ запущен заново"); jobCard(box, r.job, "Повтор анализа");
        waitJob(r.job).then(() => openVideo(v.id, box)).catch(() => openVideo(v.id, box)); } catch (e) { fail(e); }
    }, "pri", "refresh") : null;
    box.replaceChildren(h("div.panel", {}, h("h3", {}, v.title), statusTag(v), v.error ? h("div.err", { style: { marginTop: "10px" } }, v.error) : h("p.dim", { style: { marginTop: "8px" } }, "Анализ ещё идёт — результат появится автоматически."),
      retry ? h("div.row", { style: { marginTop: "12px" } }, retry, btn("Удалить", async () => { await api("/api/intel/videos/" + v.id, { method: "DELETE" }); box.replaceChildren(); }, "ghost danger", "trash")) : null));
    return;
  }
  const sec = (t, val, ic) => val ? h("div.sec.reveal", {}, h("h4", {}, h("span.row", { style: { gap: "6px" } }, ic ? icon(ic) : null, t)), typeof val === "string" ? h("p", {}, val) : val) : null;
  const obj = o => typeof o === "string" ? o : o ? h("dl.kv", {}, ...Object.entries(o).filter(([, x]) => x && (typeof x === "string" || x.length)).flatMap(([k, x]) => [h("dt", {}, ({ shots: "Планы", movement: "Движение", angle: "Ракурс", lens: "Объектив", pace: "Ритм", transitions: "Переходы", patterns: "Приёмы", subtitles: "Субтитры", overlays: "Текст в кадре", time: "Время", visual: "Что видно", why: "Почему цепляет" })[k] || k), h("dd", {}, Array.isArray(x) ? x.join(" · ") : x)])) : null;
  const kf = h("div.kf-strip", {}, ...(v.keyframes || []).map((id, i) => h("img", { src: "/files/" + id, alt: "Кадр " + (i + 1), loading: "lazy", style: { "--i": i } })));
  const chars = (a.characters || []).map((c, i) => h("div.charcard.reveal", { style: { "--i": i } }, h("div.row", {}, icon("character"), h("b", { style: { flex: 1 } }, c.role || "Персонаж"),
    btn("Сохранить", async () => { try { await api("/api/intel/characters", { body: { name: c.role || "Персонаж", sheet: c, image: v.keyframes?.[0] || null, source: v.title } }); toast("Персонаж сохранён в память"); } catch (e) { fail(e); } }, "sm ghost", "save")),
    h("dl.kv", {}, ...[["Внешность", c.appearance], ["Одежда", c.clothing], ["Причёска", c.hair], ["Аксессуары", c.accessories], ["Мимика", c.expression]].filter(x => x[1]).flatMap(([k, x]) => [h("dt", {}, k), h("dd", {}, x)]))));
  const metric = (k, val) => h("div", {}, h("span.mono-up", {}, k), h("b", {}, val ?? "—"));
  box.replaceChildren(h("div.col.result-in", {},
    h("div.panel", {}, h("div.row", { style: { alignItems: "flex-start", gap: "18px" } },
      v.thumb_url ? h("img.hero-thumb", { src: v.thumb_url, alt: "" }) : null,
      h("div.col", { style: { flex: 1, minWidth: "220px", gap: "8px" } }, h("div.row", {}, statusTag(v), h("span.dim", {}, MODE[v.mode] || ""), v.source_url ? h("a.dim", { href: v.source_url, target: "_blank", rel: "noopener", style: { textDecoration: "underline" } }, "источник") : null),
        h("h2.big-title", {}, a.title || v.title), h("p.muted", {}, a.concept || ""), tagRow(a.aesthetic_tags), a._note ? h("div.note", {}, a._note) : null,
        h("div.row", {},
          btn("Создать по этому ролику", () => { handoff.set("intel_source", { type: "video", id: v.id }); go("#/intel/create"); }, "pri sm", "wand"),
          btn("В Visual DNA", () => { handoff.set("intel_dna", [v.id]); go("#/intel/dna"); }, "sm", "dna"),
          btn("", async () => { if (await confirmBox("Удалить анализ из памяти?")) { await api("/api/intel/videos/" + v.id, { method: "DELETE" }); box.replaceChildren(); toast("Удалено"); } }, "sm icon ghost danger", "trash", { title: "Удалить" }))))),
    kf.children.length ? h("div.panel", {}, h("h3", {}, `Ключевые кадры · ${kf.children.length}`), kf) : null,
    h("div.panel", {}, h("h3", {}, h("span.row", { style: { gap: "6px" } }, icon("target"), "Измерено программой (компьютерное зрение)")),
      v.kind === "video" ? h("div.measured", {}, metric("Длительность", mmss(m.duration)), metric("Склеек", m.cut_count), metric("Средний план", m.avg_shot != null ? m.avg_shot + " с" : null), metric("Склеек / 10 с", m.cuts_per_10s),
        metric("Яркость", L.brightness != null ? `${L.brightness} · ${L.brightness_word}` : null), metric("Контраст", L.contrast != null ? `${L.contrast} · ${L.contrast_word}` : null),
        metric("Цвета", L.saturation_word), metric("Движение", M.motion != null ? `${M.motion} · ${M.motion_word}` : null)) :
        h("div.measured", {}, metric("Кадров", v.keyframes.length), metric("Яркость", L.brightness_word), metric("Контраст", L.contrast_word), metric("Температура", L.warmth_word)),
      vis.palette?.length ? h("div", { style: { marginTop: "14px" } }, h("div.mono-up", {}, "Доминирующие цвета"), swatches(vis.palette, true), h("div.chips", { style: { marginTop: "6px" } }, ...vis.palette.map(c => h("span.chip.static", {}, `${c.hex} · ${c.share}%`)))) : null,
      m.cuts?.length && m.duration ? h("div", { style: { marginTop: "14px" } }, h("div.mono-up", {}, "Склейки на шкале времени"), h("div.cutline", {}, ...m.cuts.map(c => h("i", { style: { left: (c / m.duration * 100) + "%" } })))) : null,
      M.timeline?.length ? h("div", { style: { marginTop: "12px" } }, h("div.mono-up", {}, "Интенсивность движения по времени"), spark(M.timeline)) : null,
      v.public_stats && Object.keys(v.public_stats).length ? h("div", { style: { marginTop: "12px" } }, h("div.mono-up", {}, "Публичные данные со страницы ролика"), h("dl.kv", { style: { marginTop: "6px" } },
        ...[["Автор", v.public_stats.uploader], ["Просмотры", v.public_stats.view_count?.toLocaleString("ru-RU")], ["Лайки", v.public_stats.like_count?.toLocaleString("ru-RU")], ["Комментарии", v.public_stats.comment_count?.toLocaleString("ru-RU")], ["Дата", v.public_stats.upload_date]]
          .filter(x => x[1] != null).flatMap(([k, x]) => [h("dt", {}, k), h("dd", {}, x)]))) : null),
    h("div.panel", {}, sec("Визуальный стиль", a.visual_style, "eye"), sec("Окружение и фон", a.environment, "image"), sec("Камера", obj(a.camera), "camera"), sec("Освещение", a.lighting, "sun"),
      sec("Палитра", a.palette_words, "palette"), sec("Монтаж", obj(a.editing), "cut"), sec("Субтитры и текст на экране", obj(a.on_screen_text), "text"),
      sec("Хук — первые секунды", obj(a.hook), "bolt"), sec("Темп", a.pace), sec("Озвучка", a.voice, "mic"), sec("Музыка и звук", a.music, "volume")),
    chars.length ? h("div.panel", {}, h("h3", {}, "Персонажи"), h("div.grid2", {}, ...chars)) : null,
    a.script_structure?.length ? h("div.panel", {}, h("h3", {}, "Структура сценария"), h("div.timeline", {}, ...a.script_structure.map((s, i) => h("div.tl-row.reveal", { style: { "--i": i } }, h("span.mono-up", {}, s.time), h("p", {}, s.beat))))) : null,
    v.transcript?.text ? h("div.panel", {}, h("h3", {}, "Расшифровка речи"), h("div.copy-block", {}, v.transcript.text)) : null));
  box.scrollIntoView?.({ behavior: "smooth", block: "start" });
}

// ================= 2. Visual DNA =================
async function tDna(body) {
  const pre = handoff.take("intel_dna") || [];
  const chosen = new Set(pre);
  const pick = h("div.gallery.igrid");
  const name = h("input.in", { placeholder: "Название стиля (необязательно)" });
  const out = h("div");
  const list = h("div.col");
  const build = btn("Собрать Visual DNA", async () => {
    if (!chosen.size) return toast("Отметьте референсы", true);
    build.disabled = true;
    try { const r = await runTool("/api/intel/styles", { ids: [...chosen], name: name.value, language: LANG() }, out, "Visual DNA"); out.replaceChildren(); toast("Стиль сохранён в память"); await drawList(r.style_id); }
    catch (e) { out.replaceChildren(h("div.err", {}, e.message)); }
    build.disabled = false;
  }, "pri", "dna");
  body.append(h("div.panel", {}, h("div.row", { style: { marginBottom: "10px" } }, h("h3", { style: { margin: 0, flex: 1 } }, "Из каких референсов собрать стиль"), h("span.dim", {}, "отметьте 1–20")), pick,
    h("div.row", { style: { marginTop: "14px" } }, h("div", { style: { flex: 1, minWidth: "200px" } }, name), build), out),
    h("div.mono-up", { style: { margin: "22px 0 10px" } }, "Сохранённые стили"), list);
  const vs = await loadVideos("done").catch(() => []);
  pick.replaceChildren(...(vs.length ? vs.map(v => videoCard(v, { selectable: true, selected: chosen.has(v.id), onToggle: (v, card) => { chosen.has(v.id) ? chosen.delete(v.id) : chosen.add(v.id); card.classList.toggle("sel"); } }))
    : [h("div.empty", { style: { gridColumn: "1/-1" } }, "Сначала проанализируйте несколько роликов на вкладке «Анализ».")]));
  async function drawList(openId) {
    const ss = await api("/api/intel/styles").catch(() => []);
    list.replaceChildren(...(ss.length ? ss.map(s => styleCard(s, openId === s.id)) : [h("div.empty", {}, "Стилей пока нет")]));
  }
  function styleCard(s, open) {
    const d = s.dna || {}, M = s.measured || {};
    const detail = h("div.col", { class: open ? "" : "hidden", style: { marginTop: "14px" } });
    const fld = (k, label, rows = 2) => field(label, h("textarea.in", { rows, value: Array.isArray(d[k]) ? d[k].join("\n") : d[k] || "", onchange: async e => {
      const val = Array.isArray(d[k]) ? e.target.value.split("\n").map(x => x.trim()).filter(Boolean) : e.target.value;
      try { await api(`/api/intel/styles/${s.id}`, { method: "PATCH", body: { dna: { [k]: val } } }); d[k] = val; toast("Сохранено"); } catch (x) { fail(x); } } }));
    detail.append(
      h("div.measured", {}, ...[["Роликов", M.videos], ["Склеек / 10 с", M.avg_cuts_per_10s], ["Средний план", M.avg_shot != null ? M.avg_shot + " с" : null], ["Яркость", M.brightness], ["Насыщенность", M.saturation], ["Движение", M.motion], ["Теплота", M.warmth], ["Длительность", M.avg_duration != null ? mmss(M.avg_duration) : null]]
        .map(([k, x]) => h("div", {}, h("span.mono-up", {}, k), h("b", {}, x ?? "—")))),
      h("div.grid2", {}, fld("summary", "Описание стиля", 4), fld("character_style", "Персонажи"), fld("visual_presentation", "Подача"), fld("lighting", "Освещение"), fld("camera", "Камера"),
        fld("atmosphere", "Атмосфера"), fld("text_style", "Субтитры и текст"), fld("voice_style", "Озвучка"), fld("editing_patterns", "Приёмы монтажа (по строке)", 3),
        fld("recurring_elements", "Повторяющиеся элементы", 3), fld("hook_patterns", "Хуки", 3), fld("do", "Сохранять", 3), fld("avoid", "Избегать", 3)),
      field("Стиль для генераторов (английский, добавляется к промптам)", h("textarea.in", { rows: 3, value: d.prompt_style || "", onchange: async e => { await api(`/api/intel/styles/${s.id}`, { method: "PATCH", body: { dna: { prompt_style: e.target.value } } }); toast("Сохранено"); } })));
    const card = h("div.panel.stylecard" + (open ? ".open" : ""), {},
      h("div.row", { style: { gap: "14px", cursor: "pointer" }, onclick: e => { if (e.target.closest("button")) return; detail.classList.toggle("hidden"); card.classList.toggle("open"); } },
        s.cover_url ? h("div.th", { style: { backgroundImage: `url("${s.cover_url}")` } }) : h("div.th.ic", {}, icon("dna")),
        h("div.col", { style: { flex: 1, minWidth: 0, gap: "6px" } }, h("b", { style: { fontSize: "16px" } }, s.name), swatches(M.palette), h("span.dim", { style: { fontSize: "12px" } }, `${s.sources.length} референсов · использован ${s.uses} раз · ${fmtDate(s.updated)}`)),
        h("div.row", {},
          btn("Создать ролик", () => { handoff.set("intel_source", { type: "style", id: s.id }); go("#/intel/create"); }, "sm pri", "wand"),
          btn("Картинка в стиле", () => { handoff.set("image", { style_id: s.id }); go("#/image"); }, "sm", "image"),
          btn("Видео в стиле", () => { handoff.set("video", { style_id: s.id }); go("#/video"); }, "sm", "film"),
          btn("", async () => { await api(`/api/intel/styles/${s.id}`, { method: "PATCH", body: { favorite: !s.favorite } }); drawList(); }, "sm icon ghost", "star", { title: "Избранное", style: { color: s.favorite ? "#fff" : "" } }),
          btn("", async () => { if (await confirmBox(`Удалить стиль «${s.name}»?`)) { await api(`/api/intel/styles/${s.id}`, { method: "DELETE" }); drawList(); } }, "sm icon ghost danger", "trash", { title: "Удалить" }))),
      detail);
    return card;
  }
  drawList(handoff.take("intel_style_open"));
}

// ================= 3. Создать по референсу =================
async function tCreate(body) {
  const pre = handoff.take("intel_source");
  const [vs, ss, cs] = await Promise.all([loadVideos("done").catch(() => []), api("/api/intel/styles").catch(() => []), api("/api/intel/characters").catch(() => [])]);
  const src = h("select.in", {}, h("option", { value: "" }, "Выберите референс…"),
    ss.length ? h("optgroup", { label: "Стили Visual DNA" }, ...ss.map(s => h("option", { value: "style:" + s.id, selected: pre?.type === "style" && pre.id === s.id }, s.name))) : null,
    vs.length ? h("optgroup", { label: "Проанализированные ролики" }, ...vs.filter(v => v.kind === "video").map(v => h("option", { value: "video:" + v.id, selected: pre?.type === "video" && pre.id === v.id }, v.title))) : null);
  const keep = { style: true, lighting: true, palette: true, camera: true, editing: true, environment: false, character: false, clothing: false, hair: false, hook: true, text_style: true, voice: true };
  const keepBox = h("div.chips.keep", {}, ...KEEP.map(([k, l]) => { const b = h("button.chip", { type: "button", class: keep[k] ? "on" : "", onclick: () => { keep[k] = !keep[k]; b.classList.toggle("on"); b.replaceChildren(icon(keep[k] ? "lock" : "unlock"), l); } }, icon(keep[k] ? "lock" : "unlock"), l); return b; }));
  const instr = h("textarea.in", { rows: 4, placeholder: "Например: такой же визуальный стиль, но новый персонаж — девушка в чёрном костюме, другая причёска, действие в ночном Токио, полностью новый сценарий" });
  const charSel = select([["", "Придумать нового персонажа"], ...cs.map(c => [c.id, "Персонаж из памяти: " + c.name])], "");
  const dur = segmented([[10, "10 с"], [15, "15 с"], [20, "20 с"], [30, "30 с"]], 15);
  const lang = select([["ru", "Русский"], ["uk", "Українська"], ["en", "English"]], LANG());
  const ratio = segmented(RATIOS, "9:16");
  const out = h("div"), editor = h("div");
  const make = btn("Составить план ролика", async () => {
    if (!src.value) return toast("Выберите референс: стиль или ролик", true);
    const [type, id] = src.value.split(":");
    make.disabled = true;
    try {
      const r = await runTool("/api/intel/blueprints", { source_type: type, source_id: id, keep, instructions: instr.value, duration: +dur.value, language: lang.value, ratio: ratio.value, character_id: charSel.value || null }, out, "План ролика");
      out.replaceChildren(); await openBlueprint(r.blueprint_id, editor);
    } catch (e) { out.replaceChildren(h("div.err", {}, e.message)); }
    make.disabled = false;
  }, "pri wide", "wand");
  const bpl = h("div.list");
  body.append(h("div.split", {},
    h("div.panel.col.sticky", {}, h("h3", { style: { margin: 0 } }, "Референс и изменения"), field("Референс", src),
      h("div.col", { style: { gap: "6px" } }, h("span.f-l", {}, "Что сохранить из референса"), h("span.dim", { style: { fontSize: "12px" } }, "Замок — сохранить, открытый замок — изменить"), keepBox),
      field("Что изменить", instr), field("Персонаж", charSel), field("Длительность", dur), h("div.grid2", {}, field("Язык", lang), field("Формат", ratio)), make, out,
      h("p.dim", { style: { fontSize: "12px" } }, "MaisonAI не копирует ролик покадрово: из референса берётся только выбранная эстетика, сюжет и персонаж — новые.")),
    h("div.col", {}, editor, h("div.panel", {}, h("h3", {}, "Планы роликов в памяти"), bpl))));
  const bps = await api("/api/intel/blueprints").catch(() => []);
  bpl.replaceChildren(...(bps.length ? bps.slice(0, 40).map(b => h("div.it", { onclick: () => openBlueprint(b.id, editor) }, h("div.th.ic", {}, icon(b.kind === "reverse" ? "scan" : "blueprint")),
    h("div.t", {}, b.title), h("span.tag" + (b.status === "produced" ? ".ok" : ""), {}, b.kind === "reverse" ? "разбор референса" : b.status === "produced" ? "ролик готов" : "черновик"), h("span.dim", { style: { fontSize: "12px" } }, fmtDate(b.updated)))) : [h("div.dim", {}, "Пока нет")]));
  if (pre?.blueprint) openBlueprint(pre.blueprint, editor);
  else if (!editor.children.length) editor.append(h("div.empty", {}, "Выберите референс слева — ИИ составит редактируемый план: концепция, персонаж, сценарий, хук, сцены с описанием кадров, камерой, светом, озвучкой, субтитрами и промптами."));
}

async function openBlueprint(id, box) {
  let b;
  try { b = await api("/api/intel/blueprints/" + id); } catch (e) { return fail(e); }
  const d = b.data; d.scenes ||= []; d.character ||= {}; d.subtitles ||= [];
  let saveT;
  const save = () => { clearTimeout(saveT); saveT = setTimeout(() => api("/api/intel/blueprints/" + id, { method: "PATCH", body: { data: d } }).then(() => saved.classList.add("on")).catch(fail), 500); saved.classList.remove("on"); };
  const saved = h("span.saved", {}, icon("check"), "сохранено");
  const ta = (obj, k, rows = 2, ph = "") => h("textarea.in", { rows, value: Array.isArray(obj[k]) ? obj[k].join("\n") : obj[k] ?? "", placeholder: ph, oninput: e => { obj[k] = Array.isArray(obj[k]) ? e.target.value.split("\n") : e.target.value; save(); } });
  const inp = (obj, k, ph = "", type = "text") => h("input.in", { type, value: obj[k] ?? "", placeholder: ph, oninput: e => { obj[k] = type === "number" ? +e.target.value : e.target.value; save(); } });
  const scenesBox = h("div.col");
  const drawScenes = () => scenesBox.replaceChildren(...d.scenes.map((s, i) => h("div.plan-scene.reveal", { style: { "--i": i } }, h("div.no", {}, String(i + 1).padStart(2, "0")),
    h("div.col", { style: { gap: "8px" } },
      h("div.grid3", {}, field("Длительность, с", inp(s, "duration", "", "number")), field("Камера", inp(s, "camera")), field("Свет", inp(s, "lighting"))),
      field("Описание кадра", ta(s, "frame")), h("div.grid2", {}, field("Озвучка", ta(s, "voiceover")), field("Субтитр / текст на экране", ta(s, "subtitle"))),
      field("Промпт генерации (английский)", ta(s, "prompt", 3)),
      h("div.row", {}, btn("Кадр", () => { handoff.set("image", { prompt: s.prompt + (d._style_prompt ? ", " + d._style_prompt : ""), ratio: d._ratio || "9:16" }); go("#/image"); }, "sm ghost", "image"),
        btn("Видео сцены", () => { handoff.set("video", { prompt: s.prompt, duration: Math.round(s.duration || 5), style_id: b.style_id || "" }); go("#/video"); }, "sm ghost", "film"),
        h("div", { style: { flex: 1 } }),
        btn("", () => { if (i > 0) { [d.scenes[i - 1], d.scenes[i]] = [d.scenes[i], d.scenes[i - 1]]; drawScenes(); save(); } }, "sm icon ghost", "up", { title: "Выше" }),
        btn("", () => { d.scenes.splice(i, 1); drawScenes(); save(); }, "sm icon ghost danger", "trash", { title: "Удалить сцену" }))))));
  drawScenes();
  const total = () => d.scenes.reduce((a, s) => a + (+s.duration || 0), 0);
  const voice = h("select.in");
  api("/api/tools/voices").then(r => { const l = d._language === "uk" ? "uk" : d._language === "en" ? "en" : "ru"; voice.replaceChildren(...r.voices.filter(v => v.locale.toLowerCase().startsWith(l)).map(v => h("option", { value: v.id }, v.id))); }).catch(() => { });
  const withVoice = h("input", { type: "checkbox", checked: true }), withSubs = h("input", { type: "checkbox", checked: true });
  const prodOut = h("div");
  const produce = btn("Создать ролик", async () => {
    if (!d.scenes.length) return toast("Добавьте хотя бы одну сцену", true);
    produce.disabled = true; clearTimeout(saveT); await api("/api/intel/blueprints/" + id, { method: "PATCH", body: { data: d } }).catch(() => { });
    try {
      const r = await runTool(`/api/intel/blueprints/${id}/produce`, { voice: voice.value || "ru-RU-SvetlanaNeural", with_voice: withVoice.checked, with_subs: withSubs.checked }, prodOut, "Ролик по плану");
      prodOut.replaceChildren(h("div.split.result-in", { style: { marginTop: "12px" } }, h("div.viewer", {}, h("video", { src: r.video.url, controls: true, playsInline: true, autoplay: true })),
        h("div.col", {}, h("dl.kv", {}, h("dt", {}, "Длительность"), h("dd", {}, r.info.duration + " с"), h("dt", {}, "Размер"), h("dd", {}, `${r.info.width}×${r.info.height}`)),
          btn("Скачать MP4", () => download(r.video.url, r.video.name), "pri", "download"), btn("Доработать в редакторе", () => { handoff.set("editor", r.spec); go("#/editor"); }, "", "cut"))));
    } catch (e) { prodOut.replaceChildren(h("div.err", {}, e.message)); }
    produce.disabled = false;
  }, "pri", "film");
  const c = d.character;
  box.replaceChildren(h("div.col.result-in", {},
    h("div.panel", {}, h("div.row", { style: { marginBottom: "10px" } }, h("span.tag", {}, b.kind === "reverse" ? "разбор референса" : "новый ролик"), saved, h("div", { style: { flex: 1 } }),
      btn("", async () => { if (await confirmBox("Удалить план?")) { await api("/api/intel/blueprints/" + id, { method: "DELETE" }); box.replaceChildren(); } }, "sm icon ghost danger", "trash", { title: "Удалить" })),
      field("Название концепции", inp(d, "concept_name")), d.logline !== undefined ? field("Логлайн", inp(d, "logline")) : null, field("Визуальный стиль", ta(d, "visual_style", 3)),
      d.changes?.length ? h("div", { style: { marginTop: "8px" } }, h("div.mono-up", {}, "Изменено по запросу"), h("ul.dash-list", {}, ...d.changes.map(x => h("li", {}, x)))) : null),
    b.kind !== "reverse" ? h("div.panel", {}, h("div.row", { style: { marginBottom: "10px" } }, h("h3", { style: { margin: 0, flex: 1 } }, "Персонаж"),
      btn("Сохранить в память", async () => { try { await api("/api/intel/characters", { body: { name: c.name || "Персонаж", sheet: c, source: d.concept_name } }); toast("Персонаж сохранён"); } catch (e) { fail(e); } }, "sm ghost", "save")),
      h("div.grid2", {}, field("Имя", inp(c, "name")), field("Внешность", ta(c, "appearance")), field("Одежда", ta(c, "clothing")), field("Причёска", ta(c, "hair")), field("Аксессуары", ta(c, "accessories")), field("Описание для генерации (англ.)", ta(c, "sheet_en", 3))))
      : field("Персонажи", ta(d, "characters", 2)),
    h("div.panel", {}, field("Хук — первые 3 секунды", ta(d, "hook")), field("Сценарий", ta(d, "script", 5)), field("Текст озвучки", ta(d, "voiceover", 3)), field("Субтитры (по строке)", ta(d, "subtitles", 3))),
    h("div.row", {}, h("h3", { style: { margin: 0, flex: 1 } }, `Сцены · ${d.scenes.length} · ${total()} с`),
      btn("Сцена", () => { d.scenes.push({ duration: 3, frame: "", camera: "", lighting: "", voiceover: "", subtitle: "", prompt: "" }); drawScenes(); save(); }, "sm", "plus")),
    scenesBox,
    h("div.panel.col", {}, h("h3", { style: { margin: 0 } }, "Передать в генерацию видео"), field("Голос", voice), h("label.row", {}, withVoice, "Озвучка"), h("label.row", {}, withSubs, "Субтитры по озвучке"),
      produce, h("p.dim", { style: { fontSize: "12px" } }, "Кадры рисует выбранный генератор, затем они оживают через ваш видео-провайдер (ComfyUI или монтаж из кадров), добавляются озвучка и субтитры."), prodOut)));
  box.scrollIntoView?.({ behavior: "smooth", block: "start" });
}

// ================= 4. Тренды =================
async function tTrends(body) {
  const chosen = new Set();
  const pick = h("div.gallery.igrid"), out = h("div"), list = h("div.col");
  const run = btn("Найти тренды", async () => {
    if (chosen.size < 2) return toast("Отметьте минимум 2 ролика", true);
    run.disabled = true;
    try { const r = await runTool("/api/intel/trends", { ids: [...chosen], language: LANG() }, out, "Тренды"); out.replaceChildren(); await drawList(r.report_id); }
    catch (e) { out.replaceChildren(h("div.err", {}, e.message)); }
    run.disabled = false;
  }, "pri", "trend");
  body.append(h("div.panel", {}, h("div.row", { style: { marginBottom: "10px" } }, h("h3", { style: { margin: 0, flex: 1 } }, "Какие ролики сравнить"), run), pick, out,
    h("p.dim", { style: { fontSize: "12px", marginTop: "10px" } }, "MaisonAI ищет повторяющиеся приёмы в ваших роликах. Популярность не выдумывается: публичные цифры показываются, только если их отдала страница ролика.")),
    h("div.mono-up", { style: { margin: "22px 0 10px" } }, "Отчёты"), list);
  const vs = (await loadVideos("done").catch(() => [])).filter(v => v.kind === "video");
  pick.replaceChildren(...(vs.length ? vs.map(v => videoCard(v, { selectable: true, onToggle: (v, card) => { chosen.has(v.id) ? chosen.delete(v.id) : chosen.add(v.id); card.classList.toggle("sel"); } })) : [h("div.empty", { style: { gridColumn: "1/-1" } }, "Проанализируйте хотя бы 2 ролика на вкладке «Анализ».")]));
  async function drawList(openId) {
    const rs = await api("/api/intel/trends").catch(() => []);
    list.replaceChildren(...(rs.length ? rs.map(r => report(r, openId === r.id || rs[0].id === r.id)) : [h("div.empty", {}, "Отчётов пока нет")]));
  }
  function report(r, open) {
    const d = r.data, srcN = n => (d.sources || []).find(s => String(s.n) === String(n).replace(/\D/g, ""))?.title || "ролик " + n;
    const seen = arr => (arr?.length ? h("div.chips", { style: { marginTop: "6px" } }, h("span.dim", { style: { fontSize: "12px" } }, `встречается в ${arr.length}:`), ...arr.map(n => h("span.chip.static", { title: srcN(n) }, "#" + String(n).replace(/\D/g, "")))) : null);
    const block = (title, items, key) => items?.length ? h("div.sec", {}, h("h4", {}, title), h("div.grid2", {}, ...items.map((x, i) => h("div.trendcard.reveal", { style: { "--i": i } }, h("b", {}, x.name || x.pattern), x.description ? h("p.muted", {}, x.description) : null, seen(x.seen_in))))) : null;
    const detail = h("div", { class: open ? "" : "hidden", style: { marginTop: "12px" } },
      h("p", {}, d.summary), block("Визуальные тренды", d.visual_trends), block("Форматы подачи", d.formats), block("Приёмы первых секунд", d.hooks), block("Приёмы монтажа", d.editing),
      d.ideas?.length ? h("div.sec", {}, h("h4", {}, "Идеи новых роликов"), h("div.grid2", {}, ...d.ideas.map((x, i) => h("div.trendcard.idea.reveal", { style: { "--i": i } }, h("b", {}, x.title), h("p", {}, x.concept), x.hook ? h("p.muted", {}, "Хук: " + x.hook) : null,
        x.format ? h("span.tag", {}, x.format) : null, x.why ? h("p.dim", { style: { fontSize: "12px" } }, x.why) : null,
        h("div.row", { style: { marginTop: "8px" } }, btn("Сценарий", () => { handoff.set("script_topic", { topic: x.title + ". " + x.concept, extra: "Хук: " + (x.hook || "") }); go("#/script"); }, "sm", "script")))))) : null,
      d.public_stats?.some(s => s.view_count != null) ? h("div.sec", {}, h("h4", {}, "Публичные данные (реально полученные)"), h("dl.kv", {}, ...d.public_stats.filter(s => s.view_count != null).flatMap(s => [h("dt", {}, "#" + s.n + " " + (s.title || "")), h("dd", {}, `${s.view_count?.toLocaleString("ru-RU")} просмотров` + (s.like_count != null ? ` · ${s.like_count.toLocaleString("ru-RU")} лайков` : ""))]))) : null);
    const card = h("div.panel", {}, h("div.row", { style: { cursor: "pointer" }, onclick: e => { if (!e.target.closest("button")) detail.classList.toggle("hidden"); } }, icon("trend"), h("b", { style: { flex: 1 } }, r.title), h("span.dim", {}, `${r.sources.length} роликов · ${fmtDate(r.created)}`),
      btn("", async () => { if (await confirmBox("Удалить отчёт?")) { await api("/api/intel/trends/" + r.id, { method: "DELETE" }); drawList(); } }, "sm icon ghost danger", "trash")), detail);
    return card;
  }
  drawList();
}

// ================= 5. Оценка ролика (прежний анализатор) =================
async function tScore(body) {
  const m = await import("./analyze.js");
  const inner = h("div"); body.append(inner);
  return m.render(inner, "analyze", "", { embedded: true });
}

// ================= 6. Память =================
async function tMemory(body) {
  const [vs, ss, cs, bs, ts] = await Promise.all(["videos", "styles", "characters", "blueprints", "trends"].map(k => api("/api/intel/" + k).catch(() => [])));
  const charsBox = h("div.grid3");
  const drawChars = list => charsBox.replaceChildren(...(list.length ? list.map((c, i) => h("div.charcard.reveal", { style: { "--i": i } },
    h("div.row", {}, c.image_url ? h("div.th", { style: { backgroundImage: `url("${c.image_url}")` } }) : h("div.th.ic", {}, icon("character")),
      h("input.in", { value: c.name, style: { flex: 1 }, onchange: e => api("/api/intel/characters/" + c.id, { method: "PATCH", body: { name: e.target.value } }).then(() => toast("Сохранено")).catch(fail) }),
      btn("", async () => { if (await confirmBox(`Удалить персонажа «${c.name}»?`)) { await api("/api/intel/characters/" + c.id, { method: "DELETE" }); drawChars(await api("/api/intel/characters")); } }, "sm icon ghost danger", "trash")),
    h("dl.kv", { style: { marginTop: "8px" } }, ...[["Внешность", c.sheet.appearance], ["Одежда", c.sheet.clothing], ["Причёска", c.sheet.hair]].filter(x => x[1]).flatMap(([k, x]) => [h("dt", {}, k), h("dd", {}, x)])),
    h("p.dim", { style: { fontSize: "12px", marginTop: "6px" } }, c.source ? "Из: " + c.source : ""))) : [h("div.empty", { style: { gridColumn: "1/-1" } }, "Сохраняйте персонажей из анализов и планов — их можно повторно использовать в новых роликах.")]));
  drawChars(cs);
  const counter = (n, l, ic, href) => h("a.memstat", { href }, icon(ic), h("b", {}, n), h("span", {}, l));
  body.append(
    h("div.memgrid", {}, counter(vs.filter(v => v.status === "done").length, "проанализировано", "scan", "#/intel/analyze"), counter(ss.length, "стилей Visual DNA", "dna", "#/intel/dna"),
      counter(cs.length, "персонажей", "character", "#/intel/memory"), counter(bs.length, "планов роликов", "blueprint", "#/intel/create"), counter(ts.length, "отчётов о трендах", "trend", "#/intel/trends")),
    h("div.panel", {}, h("h3", {}, "Персонажи"), charsBox),
    h("div.grid2", {},
      h("div.panel", {}, h("h3", {}, "Стили"), h("div.list", {}, ...(ss.length ? ss.map(s => h("div.it", { onclick: () => { handoff.set("intel_style_open", s.id); go("#/intel/dna"); } }, h("div.th", { style: { backgroundImage: s.cover_url ? `url("${s.cover_url}")` : "" } }), h("div.t", {}, s.name), swatches(s.measured?.palette))) : [h("div.dim", {}, "Пока нет")]))),
      h("div.panel", {}, h("h3", {}, "Последние анализы"), h("div.list", {}, ...(vs.length ? vs.slice(0, 12).map(v => h("div.it", { onclick: () => { handoff.set("intel_open", v.id); go("#/intel/analyze"); } }, h("div.th", { style: { backgroundImage: v.thumb_url ? `url("${v.thumb_url}")` : "" } }), h("div.t", {}, v.title), statusTag(v))) : [h("div.dim", {}, "Пока нет")])))));
}
