import { state, api, h, icon, btn, fail, toast, runTool, handoff, go, field, segmented, RATIOS, pickAsset, assetCard, previewModal, toggleFav, deleteAsset, download, providerBadge, loadProviders, styleSelect } from "./lib.js";

const EDITS = [["Одежда", "Change the person's outfit to "], ["Причёска", "Change the hairstyle to "], ["Окружение", "Place the subject in a new environment: "],
  ["Освещение", "Relight the scene with "], ["Стиль", "Restyle the whole image as "], ["Фон убрать", "Replace the background with a clean seamless studio backdrop"]];
const PRESETS = [["", "Свободно"], ["character", "Персонаж"], ["cover", "Обложка TikTok"], ["ad", "Реклама"], ["frame", "Кадр для видео"]];

export async function render(page) {
  await loadProviders().catch(() => { });
  const pre = handoff.take("image") || {};
  const prompt = h("textarea.in", { rows: 5, placeholder: "Опишите изображение (лучше на английском — модели понимают его точнее). Например: young woman in a red coat walking in Paris at golden hour, 35mm film look", value: pre.prompt || "" });
  const preset = segmented(PRESETS, pre.preset || "");
  const styleSel = styleSelect(pre.style_id || "");
  const ratio = segmented(RATIOS, pre.ratio || state.user.prefs?.ratio || "9:16");
  const count = segmented([[1, "1"], [2, "2"], [4, "4"]], 1);
  const seed = h("input.in", { type: "number", placeholder: "случайно", min: 0 });
  const strength = h("input", { type: "range", min: 0.2, max: 0.95, step: 0.05, value: 0.65 }), stL = h("span.dim", {}, "0.65");
  strength.oninput = () => stL.textContent = (+strength.value).toFixed(2);
  let source = pre.source || null;
  const srcBox = h("div");
  const editChips = h("div.chips", {}, ...EDITS.map(([l, t]) => h("button.chip", { type: "button", onclick: () => { prompt.value = t + (t.endsWith(" ") ? "" : ""); prompt.focus(); prompt.setSelectionRange(prompt.value.length, prompt.value.length); } }, l)));
  const editPanel = h("div.col", {}, h("div.mono-up", {}, "Что изменить"), editChips, field("Сила изменений (для ComfyUI)", strength, stL));
  const drawSrc = () => {
    editPanel.classList.toggle("hidden", !source);
    srcBox.replaceChildren(source ? h("div.src-thumb", {}, h("div.th", { style: { backgroundImage: `url("${source.url}")` } }), h("div", { style: { flex: 1, minWidth: 0 } }, h("b", {}, "Редактирование"), h("div.dim", { style: { fontSize: "12px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, source.name)),
      btn("", () => { source = null; drawSrc(); }, "sm icon ghost", "x", { "aria-label": "Убрать исходник" }))
      : btn("Загрузить или выбрать картинку для правки", async () => { const a = await pickAsset(["image"], "Исходная картинка"); if (a) { source = a; drawSrc(); } }, "wide", "upload"));
  };
  drawSrc();
  const out = h("div"), gal = h("div.gallery");
  const improve = btn("Улучшить промпт", async () => {
    if (!prompt.value.trim()) return toast("Сначала опишите идею", true);
    improve.disabled = true;
    try { const r = await api("/api/tools/improve", { body: { text: prompt.value, target: "image", ratio: ratio.value } }); prompt.value = r.prompt; toast(r.summary_ru || "Промпт улучшен"); }
    catch (e) { fail(e); } improve.disabled = false;
  }, "sm", "wand");
  const gen = btn("Сгенерировать", async () => {
    if (!prompt.value.trim()) return toast("Опишите изображение", true);
    gen.disabled = true;
    try {
      const r = await runTool("/api/tools/image", { prompt: prompt.value.trim(), ratio: ratio.value, preset: source ? "" : preset.value, count: +count.value, seed: seed.value ? +seed.value : null, source: source?.id || null, strength: +strength.value, style_id: styleSel.value || null }, out, "Изображение");
      out.replaceChildren(h("div.gallery", {}, ...r.assets.map(card)));
      load();
    } catch (e) { out.replaceChildren(h("div.err", {}, e.message)); }
    gen.disabled = false;
  }, "pri wide", "wand");

  function card(a) {
    return assetCard(a, {
      onClick: () => previewModal(a, [btn("Редактировать", () => { document.querySelector(".modal-bg")?.remove(); source = a; drawSrc(); prompt.value = ""; prompt.focus(); window.scrollTo(0, 0); }, "", "edit"),
        btn("В видео", () => { document.querySelector(".modal-bg")?.remove(); handoff.set("video", { mode: "i2v", source: a, prompt: a.meta?.prompt || "" }); go("#/video"); }, "", "film")]),
      actions: [btn("", () => { source = a; drawSrc(); prompt.focus(); }, "sm icon", "edit", { title: "Редактировать" }), btn("", () => toggleFav(a, load), "sm icon", "star", { title: "В избранное" }),
        btn("", () => download(a.url, a.name), "sm icon", "download", { title: "Скачать" }), btn("", () => deleteAsset(a, load), "sm icon danger", "trash", { title: "Удалить" })]
    });
  }
  async function load() {
    try {
      const items = (await api("/api/assets?kind=image&limit=120")).filter(a => !a.meta?.reference_frame);
      gal.replaceChildren(...(items.length ? items.map(card) : [h("div.empty", { style: { gridColumn: "1/-1" } }, "История генераций пуста")]));
    } catch (e) { gal.replaceChildren(h("div.err", {}, e.message)); }
  }
  page.append(
    h("div.ph", {}, h("div", {}, h("h1", {}, "Изображения"), h("p", {}, "Генерация с нуля и правка загруженных картинок: одежда, причёска, окружение, освещение, стиль.")), h("div.sp"),
      h("div.row", {}, providerBadge("image"), providerBadge("image_edit"))),
    h("div.split", {},
      h("div.panel.col.sticky", {}, srcBox, editPanel, field("Описание", prompt), h("div.row", {}, improve), field("Назначение", preset), field("Стиль", styleSel, "из TikTok Intelligence"), field("Соотношение сторон", ratio), h("div.grid2", {}, field("Количество", count), field("Seed", seed, "для повторяемости")), gen),
      h("div.col", {}, out, h("div.mono-up", {}, "История генераций"), gal)));
  load();
}
