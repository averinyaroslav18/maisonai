import { state, api, h, icon, btn, fail, toast, go, modal, confirmBox, fmtDate, assetCard, previewModal, toggleFav, deleteAsset, download, segmented, handoff } from "./lib.js";

const TOOLS = { script: "Сценарий", image: "Изображение", voice: "Озвучка", video: "Видео", analyze: "Анализ", recreate_analyze: "Разбор референса", recreate_plan: "План ролика", recreate: "Воссоздание", render: "Экспорт", subtitles: "Субтитры", mux: "Озвучка к видео", assistant: "Ассистент" };
const STATUS = { queued: "в очереди", running: "выполняется", done: "готово", error: "ошибка", cancelled: "отменено" };

export async function render(page, key, arg) {
  if (key === "project") return project(page, +arg);
  if (key === "history") return history(page);
  if (key === "favorites") return favorites(page);
  return projects(page);
}

async function projects(page) {
  const grid = h("div.gallery", { style: { gridTemplateColumns: "repeat(auto-fill,minmax(220px,1fr))" } });
  const q = h("input.in", { type: "search", placeholder: "Поиск по названию", style: { maxWidth: "280px" } });
  const name = h("input.in", { placeholder: "Название нового проекта", style: { maxWidth: "280px" } });
  const create = async () => { try { const p = await api("/api/projects", { body: { title: name.value.trim() || "Новый проект" } }); window.__setProject(p); go("#/project/" + p.id); } catch (e) { fail(e); } };
  name.onkeydown = e => { if (e.key === "Enter") create(); };
  const load = async () => {
    try {
      const ps = await api("/api/projects?q=" + encodeURIComponent(q.value.trim()));
      grid.replaceChildren(...(ps.length ? ps.map(p => h("div.card", { onclick: () => go("#/project/" + p.id) },
        h("div.media", { style: { aspectRatio: "4/3", backgroundImage: p.cover_url ? `url("${p.cover_url}")` : "" } }),
        p.favorite ? h("span.badge", {}, "★ избранное") : null,
        h("div.cap", {}, h("b", { style: { color: "var(--tx)" } }, p.title), h("br"), `${p.n_assets} файлов · ${fmtDate(p.updated)}`))) : [h("div.empty", { style: { gridColumn: "1/-1" } }, q.value ? "Ничего не найдено" : "Проектов пока нет. Создайте первый.")]));
    } catch (e) { grid.replaceChildren(h("div.err", {}, e.message)); }
  };
  let tmr; q.oninput = () => { clearTimeout(tmr); tmr = setTimeout(load, 250); };
  page.append(h("div.ph", {}, h("div", {}, h("h1", {}, "Проекты"), h("p", {}, "Каждый проект хранит свои файлы, генерации, монтаж и переписку с ассистентом.")), h("div.sp"), h("div.row", {}, name, btn("Создать", create, "pri", "plus"))),
    h("div.row", { style: { marginBottom: "16px" } }, q), grid);
  load();
}

async function project(page, id) {
  let p;
  try { p = await api("/api/projects/" + id); } catch (e) { page.append(h("div.err", {}, e.message)); return; }
  const title = h("input.in", { value: p.title, style: { fontSize: "20px", fontWeight: 600, maxWidth: "520px" }, "aria-label": "Название проекта",
    onchange: async e => { try { await api("/api/projects/" + id, { method: "PATCH", body: { title: e.target.value } }); if (state.project?.id === id) window.__setProject({ ...state.project, title: e.target.value }); toast("Сохранено"); } catch (x) { fail(x); } } });
  const filter = segmented([["", "Все"], ["video", "Видео"], ["image", "Изображения"], ["audio", "Аудио"], ["script", "Сценарии"]], "", () => drawAssets());
  const grid = h("div.gallery");
  const drawAssets = () => {
    const items = p.assets.filter(a => !filter.value || a.kind === filter.value);
    grid.replaceChildren(...(items.length ? items.map(a => assetCard(a, {
      onClick: () => a.kind === "script" ? api(`/api/assets/${a.id}/text`).then(s => { handoff.set("script", { script: s }); go("#/script"); }).catch(fail) : previewModal(a),
      actions: [btn("", () => toggleFav(a, () => drawAssets()), "sm icon", "star"), a.kind !== "script" ? btn("", () => download(a.url, a.name), "sm icon", "download") : null,
        btn("", () => deleteAsset(a, async () => { p = await api("/api/projects/" + id); drawAssets(); }), "sm icon danger", "trash")].filter(Boolean)
    })) : [h("div.empty", { style: { gridColumn: "1/-1" } }, "Файлов пока нет")]));
  };
  const isCur = state.project?.id === id;
  page.append(
    h("div.ph", {}, h("div.col", { style: { gap: "6px" } }, title, h("span.dim", {}, `Создан ${fmtDate(p.created)} · обновлён ${fmtDate(p.updated)}`)), h("div.sp"),
      h("div.row", {},
        isCur ? h("span.tag.free", {}, "текущий проект") : btn("Сделать текущим", () => { window.__setProject(p); toast("Теперь всё новое сохраняется в «" + p.title + "»"); go("#/project/" + id); }, "pri", "check"),
        btn(p.favorite ? "В избранном" : "В избранное", async e => { p.favorite = !p.favorite; await api("/api/projects/" + id, { method: "PATCH", body: { favorite: p.favorite } }); e.currentTarget.lastChild.textContent = p.favorite ? "В избранном" : "В избранное"; }, "", "star"),
        btn("Ассистент", () => { window.__setProject(p); go("#/assistant"); }, "", "chat"),
        btn("Редактор", () => { window.__setProject(p); go("#/editor"); }, "", "cut"),
        btn("Удалить", async () => {
          if (!await confirmBox(`Удалить проект «${p.title}» и все его файлы? Файлы из «Избранного» сохранятся.`)) return;
          try { await api("/api/projects/" + id, { method: "DELETE" }); if (state.project?.id === id) window.__setProject(null); toast("Проект удалён"); go("#/projects"); } catch (e) { fail(e); }
        }, "ghost danger", "trash"))),
    h("div.row", { style: { marginBottom: "14px" } }, filter), grid,
    h("div.panel", { style: { marginTop: "24px" } }, h("h3", {}, "Генерации в проекте"), jobsList(p.jobs)));
  drawAssets();
}

function jobsList(js, reload) {
  if (!js.length) return h("div.empty", {}, "Задач пока нет");
  return h("div.list", {}, ...js.map(j => {
    const res = j.result || {};
    const a = res.asset || res.video || (res.assets && res.assets[0]) || res.thumbnail;
    return h("div.it", { onclick: () => openJob(j) },
      h("div.th", { style: { backgroundImage: a && (a.kind === "image" || a.kind === "video") ? `url("${a.kind === "video" ? a.url + "?thumb=1" : a.url}")` : "" } }),
      h("div.t", {}, h("div", { style: { overflow: "hidden", textOverflow: "ellipsis" } }, j.title), h("div.dim", { style: { fontSize: "12px" } }, `${TOOLS[j.tool] || j.tool} · ${j.provider || "—"} · ${j.elapsed ? j.elapsed + " с" : ""}`)),
      h("span.tag" + (j.status === "error" ? ".paid" : ""), {}, STATUS[j.status] || j.status),
      h("span.dim", { style: { fontSize: "12px", minWidth: "110px", textAlign: "right" } }, fmtDate(j.created)),
      reload ? btn("", async e => { e.stopPropagation(); await api(`/api/jobs/${j.id}/favorite?on=${!j.favorite}`, { body: {} }); j.favorite = !j.favorite; reload(); }, "sm icon ghost" + (j.favorite ? "" : ""), "star", { title: j.favorite ? "Убрать из избранного" : "В избранное", style: { color: j.favorite ? "var(--white)" : "var(--tx3)" } }) : null,
      reload && !["queued", "running"].includes(j.status) ? btn("", async e => { e.stopPropagation(); await api("/api/jobs/" + j.id, { method: "DELETE" }); reload(); }, "sm icon ghost danger", "trash", { title: "Удалить из истории" }) : null);
  }));
}

function openJob(j) {
  const r = j.result || {};
  if (j.status === "error") return modal(j.title, h("div.err", {}, j.error || "Ошибка"), { size: "sm" });
  if (j.tool === "script" && r.script) { handoff.set("script", r); return go("#/script"); }
  const a = r.asset || r.video || (r.assets && r.assets[0]);
  if (a) return previewModal(a);
  if (j.tool === "analyze") return go("#/analyze");
  if (j.tool === "assistant") return go("#/assistant");
  modal(j.title, h("div.copy-block", {}, JSON.stringify(r, null, 1).slice(0, 4000)));
}

async function history(page) {
  const tool = segmented([["", "Все"], ["video", "Видео"], ["image", "Изображения"], ["voice", "Озвучка"], ["script", "Сценарии"], ["analyze", "Анализ"], ["recreate", "Воссоздание"], ["render", "Монтаж"]], "", () => load());
  const st = segmented([["", "Любой статус"], ["running", "Идут"], ["done", "Готово"], ["error", "Ошибки"]], "", () => load());
  const box = h("div.panel");
  const load = async () => {
    try { const js = await api(`/api/jobs?limit=200&tool=${tool.value}&status=${st.value}`); box.replaceChildren(jobsList(js, load)); }
    catch (e) { box.replaceChildren(h("div.err", {}, e.message)); }
  };
  page.append(h("div.ph", {}, h("div", {}, h("h1", {}, "История"), h("p", {}, "Все генерации: какой инструмент, какой провайдер, сколько заняло и чем закончилось."))),
    h("div.col", { style: { marginBottom: "14px" } }, tool, st), box);
  load();
  const t = setInterval(() => { if (st.value === "running" || !st.value) load(); }, 4000);
  return () => clearInterval(t);
}

async function favorites(page) {
  const grid = h("div.gallery"), pl = h("div.list"), jl = h("div");
  const load = async () => {
    try {
      const [as, ps, js] = await Promise.all([api("/api/assets?favorite=true&limit=300"), api("/api/projects?favorite=true"), api("/api/jobs?favorite=true&limit=100")]);
      grid.replaceChildren(...(as.length ? as.map(a => assetCard(a, { onClick: () => previewModal(a), actions: [btn("", () => toggleFav(a, load), "sm icon", "star", { title: "Убрать из избранного" }), btn("", () => download(a.url, a.name), "sm icon", "download")] })) : [h("div.empty", { style: { gridColumn: "1/-1" } }, "Отмечайте файлы звёздочкой — они появятся здесь")]));
      pl.replaceChildren(...(ps.length ? ps.map(p => h("div.it", { onclick: () => go("#/project/" + p.id) }, h("div.th", { style: { backgroundImage: p.cover_url ? `url("${p.cover_url}")` : "" } }), h("div.t", {}, p.title), h("span.dim", {}, fmtDate(p.updated)))) : [h("div.dim", {}, "Нет избранных проектов")]));
      jl.replaceChildren(js.length ? jobsList(js, load) : h("div.dim", {}, "Нет избранных генераций"));
    } catch (e) { grid.replaceChildren(h("div.err", {}, e.message)); }
  };
  page.append(h("div.ph", {}, h("div", {}, h("h1", {}, "Избранное"))), grid,
    h("div.grid2", { style: { marginTop: "20px" } }, h("div.panel", {}, h("h3", {}, "Проекты"), pl), h("div.panel", {}, h("h3", {}, "Генерации"), jl)));
  load();
}
