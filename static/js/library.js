import { api, h, icon, btn, fail, toast, go, modal, assetCard, previewModal, deleteAsset, download, fmtDate, copy } from "./lib.js";

// Project Library — все видео, картинки, аудио, сценарии, персонажи и проекты: поиск, фильтры, папки, избранное
const KINDS = [["", "Всё"], ["video", "Видео"], ["image", "Изображения"], ["audio", "Аудио"], ["script", "Сценарии"], ["character", "Персонажи"], ["project", "Проекты"]];

export async function render(page) {
  let kind = "", folder = "", fav = false, q = "", t = null;
  const search = h("input.in.search-in", { type: "search", placeholder: "Поиск по названию и описанию", oninput: e => { q = e.target.value; clearTimeout(t); t = setTimeout(load, 300); } });
  const chips = h("div.chips"), folders = h("div.chips"), grid = h("div.lib-grid"), count = h("span.dim");
  const drawChips = () => chips.replaceChildren(...KINDS.map(([k, l]) => h("button.chip" + (kind === k ? ".on" : ""), { type: "button", onclick: () => { kind = k; drawChips(); load(); } }, l)),
    h("button.chip" + (fav ? ".on" : ""), { type: "button", onclick: () => { fav = !fav; drawChips(); load(); } }, icon("star"), "Избранное"));
  async function drawFolders() {
    const fs = await api("/api/library/folders").catch(() => []);
    folders.replaceChildren(h("button.chip" + (!folder ? ".on" : ""), { type: "button", onclick: () => { folder = ""; drawFolders(); load(); } }, icon("folder"), "Все папки"),
      ...fs.map(f => h("button.chip" + (folder === f ? ".on" : ""), { type: "button", onclick: () => { folder = f; drawFolders(); load(); } }, icon("folder"), f)));
  }
  const toFolder = async (it) => {
    const fs = await api("/api/library/folders").catch(() => []);
    const inp = h("input.in", { value: it.folder || "", placeholder: "Название папки", list: "fl" }), dl = h("datalist", { id: "fl" }, ...fs.map(f => h("option", { value: f })));
    const m = modal("Переместить в папку", h("div.col", {}, inp, dl, h("p.dim", {}, "Пустое поле — убрать из папки.")), { size: "sm", foot: [btn("Отмена", () => m.close()), btn("Сохранить", async () => {
      try { await api("/api/library/move", { body: { type: it.type, id: String(it.id), folder: inp.value } }); m.close(); toast("Перемещено"); drawFolders(); load(); } catch (e) { fail(e); } }, "pri", "check")] });
  };
  const favBtn = it => btn("", async () => { try { await api("/api/library/favorite", { body: { type: it.type, id: String(it.id), favorite: !it.favorite } }); load(); } catch (e) { fail(e); } }, "sm icon ghost" + (it.favorite ? " on" : ""), "star", { title: "Избранное" });
  function card(it, i) {
    if (it.type === "asset") return h("div.lib-it", { style: { "--i": i } }, assetCard(it, { onClick: () => previewModal(it), actions: [favBtn(it), btn("", () => toFolder(it), "sm icon ghost", "folder", { title: "В папку" }), btn("", () => download(it.url, it.name), "sm icon ghost", "download", { title: "Скачать" }), btn("", () => deleteAsset(it, load), "sm icon ghost danger", "trash", { title: "Удалить" })] }), it.folder ? h("span.fold", {}, it.folder) : null);
    if (it.type === "project") return h("div.lib-it", { style: { "--i": i } }, h("div.card.proj", { onclick: () => go(it.project_kind === "flow" ? "#/flow/" + it.id : "#/project/" + it.id) },
      h("div.media.ic", {}, icon(it.project_kind === "flow" ? "sparkles" : "folder")), h("span.badge", {}, it.project_kind === "flow" ? "Flow" : "проект"),
      h("div.acts", { onclick: e => e.stopPropagation() }, favBtn(it), btn("", () => toFolder(it), "sm icon ghost", "folder")), h("div.cap", {}, it.favorite ? "★ " : "", it.name)), it.folder ? h("span.fold", {}, it.folder) : null);
    if (it.type === "script") return h("div.lib-it", { style: { "--i": i } }, h("div.card.proj", { onclick: () => showScript(it) }, h("div.media.ic", {}, icon("script")), h("span.badge", {}, "сценарий"), h("div.cap", {}, it.name)));
    return h("div.lib-it", { style: { "--i": i } }, h("div.card.proj", { onclick: () => go("#/characters") }, it.url ? h("div.media", { style: { backgroundImage: `url("${it.url}")` } }) : h("div.media.ic", {}, icon("character")), h("span.badge", {}, "персонаж"), h("div.cap", {}, it.name)));
  }
  function showScript(it) {
    const d = it.data || {}; const txt = [d.title, d.hook && "Хук: " + d.hook, d.voiceover || d.script, (d.hashtags || []).join(" ")].filter(Boolean).join("\n\n");
    modal(it.name, h("div.copy-block", { style: { whiteSpace: "pre-wrap" } }, txt || JSON.stringify(d, null, 2)), { foot: [btn("Копировать", () => copy(txt), "", "copy")] });
  }
  async function load() {
    const p = new URLSearchParams({ kind, q, folder }); if (fav) p.set("favorite", "true");
    try {
      const r = await api("/api/library?" + p);
      count.textContent = `${r.items.length} шт.`;
      grid.replaceChildren(...(r.items.length ? r.items.map(card) : [h("div.empty", {}, q ? "Ничего не нашлось." : "Здесь будут все ваши файлы, сценарии и проекты.")]));
    } catch (e) { grid.replaceChildren(h("div.err", {}, e.message)); }
  }
  page.append(h("div.ph", {}, h("h1", {}, "Project Library"), h("p.muted", {}, "Все видео, изображения, аудио, сценарии, персонажи и проекты в одном месте.")),
    h("div.row.wrap", { style: { gap: "10px", marginBottom: "10px" } }, search, count), chips, folders, grid);
  drawChips(); drawFolders(); load();
}
