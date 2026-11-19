import { api, h, icon, btn, fail, toast, go, field, modal, confirmBox, runTool, pickAsset, handoff } from "./lib.js";

// Character Lab — библиотека своих персонажей: внешность, одежда, причёска, референс. Используются во Flow и генерации кадров.
const FIELDS = [["appearance", "Внешность", "возраст, телосложение, черты лица"], ["clothing", "Одежда", "что надето"], ["hair", "Причёска", "цвет, длина, укладка"],
  ["accessories", "Аксессуары", "очки, украшения…"], ["expression", "Мимика и поведение", "характер в кадре"], ["style", "Визуальный стиль", "в каком стиле рисовать"]];

export async function render(page) {
  const grid = h("div.char-grid");
  page.append(h("div.ph", {}, h("h1", {}, "Character Lab"), h("p.muted", {}, "Создайте персонажа один раз — он будет выглядеть одинаково во всех сценах Maison Flow (насколько позволяет выбранная модель: с референс-картинкой согласованность заметно выше).")),
    h("div.row", { style: { marginBottom: "14px" } }, btn("Новый персонаж", () => edit({ name: "", sheet: {} }), "pri", "plus")), grid);
  async function load() {
    try {
      const cs = await api("/api/intel/characters");
      grid.replaceChildren(...(cs.length ? cs.map((c, i) => h("article.char", { style: { "--i": i } },
        h("div.char-img", { style: { backgroundImage: c.image_url ? `url("${c.image_url}")` : "" } }, c.image_url ? null : icon("character")),
        h("div.char-b", {}, h("b", {}, c.name), h("p.dim", {}, [c.sheet.appearance, c.sheet.clothing, c.sheet.hair].filter(Boolean).join(" · ") || "Описание не заполнено"),
          h("div.row.wrap", {}, btn("Изменить", () => edit(c), "sm", "edit"), btn("Ролик во Flow", () => { handoff.set("flow_char", c.id); go("#/flow"); }, "sm ghost", "sparkles"),
            btn("", async () => { if (await confirmBox(`Удалить персонажа «${c.name}»?`)) { await api("/api/intel/characters/" + c.id, { method: "DELETE" }); load(); } }, "sm icon ghost danger", "trash"))))) : [h("div.empty", {}, "Персонажей пока нет. Создайте первого — или сохраните персонажа из разбора ролика в TikTok Intelligence.")]));
    } catch (e) { grid.replaceChildren(h("div.err", {}, e.message)); }
  }
  function edit(c) {
    const name = h("input.in", { value: c.name || "", placeholder: "Например: Тренер Макс", maxLength: 60 });
    const ins = Object.fromEntries(FIELDS.map(([k, , ph]) => { const e = h("textarea.in", { rows: 2, placeholder: ph }); e.value = c.sheet?.[k] || ""; return [k, e]; }));
    let image = c.image || null, imageUrl = c.image_url || null;
    const prev = h("div.char-img.lg"), box = h("div");
    const drawImg = () => { prev.style.backgroundImage = imageUrl ? `url("${imageUrl}")` : ""; prev.replaceChildren(imageUrl ? "" : icon("character")); };
    const sheet = () => Object.fromEntries(FIELDS.map(([k]) => [k, ins[k].value.trim()]));
    const genRef = btn("Сгенерировать референс", async () => {
      const s = sheet(); const desc = [s.appearance, s.clothing && "wearing " + s.clothing, s.hair && "hair: " + s.hair, s.accessories, s.expression, s.style].filter(Boolean).join(", ");
      if (!desc) return toast("Опишите внешность", true);
      genRef.disabled = true;
      try { const r = await runTool("/api/tools/image", { prompt: desc, preset: "character", ratio: "4:5" }, box, "Референс персонажа"); const a = r.assets[0]; image = a.id; imageUrl = a.url; drawImg(); box.replaceChildren(); }
      catch (e) { box.replaceChildren(h("div.err", {}, e.message)); }
      genRef.disabled = false;
    }, "sm", "sparkles");
    const save = async () => {
      if (!name.value.trim()) return toast("Дайте персонажу имя", true);
      try {
        if (c.id) await api("/api/intel/characters/" + c.id, { method: "PATCH", body: { name: name.value, sheet: { ...c.sheet, ...sheet() }, image: image || "" } });
        else await api("/api/intel/characters", { body: { name: name.value, sheet: sheet(), image, source: "Character Lab" } });
        m.close(); toast("Сохранено"); load();
      } catch (e) { fail(e); }
    };
    const m = modal(c.id ? c.name : "Новый персонаж", h("div.grid2", {}, h("div.col", {}, field("Имя", name), ...FIELDS.map(([k, l]) => field(l, ins[k]))),
      h("div.col", {}, h("div.mono-up", {}, "Референс"), prev, h("div.row.wrap", {}, genRef, btn("Выбрать фото", async () => { const a = await pickAsset(["image"], "Референс персонажа"); if (a) { image = a.id; imageUrl = a.url; drawImg(); } }, "sm ghost", "folder")), box,
        h("p.dim", { style: { fontSize: "12px" } }, "Референс-картинка подаётся в модель правки картинок, чтобы лицо и одежда совпадали между сценами."))),
      { size: "lg", foot: [btn("Отмена", () => m.close()), btn("Сохранить", save, "pri", "check")] });
    drawImg();
  }
  load();
}
