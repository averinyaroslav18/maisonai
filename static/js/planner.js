import { api, h, btn, fail, toast, field, select, modal, confirmBox, runTool, handoff, go, LANGS } from "./lib.js";

// Content Planner — календарь публикаций: идеи → сценарий → производство → готово → опубликовано
const ST = [["idea", "Идея"], ["script", "Сценарий"], ["production", "В работе"], ["ready", "Готово"], ["published", "Опубликовано"]];
const PL = [["tiktok", "TikTok"], ["reels", "Reels"], ["shorts", "Shorts"], ["youtube", "YouTube"], ["other", "Другое"]];
const iso = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

export async function render(page) {
  let cur = new Date(); cur.setDate(1);
  let view = matchMedia("(max-width: 760px)").matches ? "list" : "month";
  const head = h("div.row.cal-head"), body = h("div"), out = h("div");
  page.append(h("div.ph", {}, h("h1", {}, "Content Planner"), h("p.muted", {}, "Календарь контента: идеи, сценарии, съёмки и публикации. Нажмите на день, чтобы добавить запись.")), head, out, body);

  async function draw() {
    const month = iso(cur).slice(0, 7);
    let items = [];
    try { items = await api("/api/planner?month=" + month); } catch (e) { body.replaceChildren(h("div.err", {}, e.message)); return; }
    const title = cur.toLocaleDateString("ru-RU", { month: "long", year: "numeric" });
    head.replaceChildren(btn("", () => { cur.setMonth(cur.getMonth() - 1); draw(); }, "ghost icon", "chevron", { style: { transform: "scaleX(-1)" }, "aria-label": "Предыдущий месяц" }),
      h("h2.cal-title", {}, title[0].toUpperCase() + title.slice(1)), btn("", () => { cur.setMonth(cur.getMonth() + 1); draw(); }, "ghost icon", "chevron", { "aria-label": "Следующий месяц" }),
      btn("Сегодня", () => { cur = new Date(); cur.setDate(1); draw(); }, "sm ghost"), h("div", { style: { flex: 1 } }),
      btn(view === "month" ? "Списком" : "Календарём", () => { view = view === "month" ? "list" : "month"; draw(); }, "sm ghost", view === "month" ? "list" : "grid"),
      btn("ИИ-идеи на месяц", ideas, "sm", "sparkles"), btn("Добавить", () => edit({ day: iso(new Date()) }), "sm pri", "plus"));
    const byDay = {}; items.forEach(x => (byDay[x.day] ||= []).push(x));
    const chip = x => h("button.cal-item." + x.status, { type: "button", onclick: e => { e.stopPropagation(); edit(x); } }, h("span.pl", {}, PL.find(p => p[0] === x.platform)?.[1] || ""), x.time ? h("span.dim", {}, x.time) : null, h("span.t", {}, x.title));
    if (view === "list") {
      const days = Object.keys(byDay).sort();
      body.replaceChildren(h("div.cal-list", {}, ...(days.length ? days.map(d => h("div.cal-lday", {}, h("div.mono-up", {}, new Date(d + "T12:00").toLocaleDateString("ru-RU", { weekday: "short", day: "numeric", month: "short" })), ...byDay[d].map(chip)))
        : [h("div.empty", {}, "В этом месяце пока пусто. Добавьте запись или попросите ИИ придумать идеи.")])));
      return;
    }
    const first = new Date(cur), start = new Date(first); start.setDate(1 - ((first.getDay() + 6) % 7));
    const today = iso(new Date());
    const cells = [];
    for (let i = 0; i < 42; i++) {
      const d = new Date(start); d.setDate(start.getDate() + i); const k = iso(d);
      cells.push(h("div.cal-day" + (d.getMonth() !== cur.getMonth() ? ".out" : "") + (k === today ? ".today" : ""), { onclick: () => edit({ day: k }), style: { "--i": i } },
        h("span.dn", {}, d.getDate()), ...(byDay[k] || []).map(chip)));
    }
    body.replaceChildren(h("div.cal-week", {}, ...["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"].map(d => h("span.mono-up", {}, d))), h("div.cal-grid", {}, ...cells),
      h("div.row.wrap.cal-legend", {}, ...ST.map(([k, l]) => h("span.cal-item." + k, {}, l))));
  }

  function edit(x) {
    const day = h("input.in", { type: "date", value: x.day }), time = h("input.in", { type: "time", value: x.time || "" });
    const title = h("input.in", { value: x.title || "", placeholder: "О чём ролик", maxLength: 200 });
    const plat = select(PL, x.platform || "tiktok"), st = select(ST, x.status || "idea");
    const notes = h("textarea.in", { rows: 5, placeholder: "Хук, что показать, ссылки…" }); notes.value = x.notes || "";
    const save = async () => {
      const b = { day: day.value, time: time.value, title: title.value, platform: plat.value, status: st.value, notes: notes.value, project_id: x.project_id || null };
      try { if (x.id) await api("/api/planner/" + x.id, { method: "PUT", body: b }); else await api("/api/planner", { body: b }); m.close(); draw(); toast("Сохранено"); } catch (e) { fail(e); }
    };
    const toFlow = btn("Сделать ролик во Flow", () => { m.close(); handoff.set("flow_idea", title.value + (notes.value ? "\n" + notes.value : "")); go("#/flow"); }, "ghost", "sparkles");
    const m = modal(x.id ? "Запись" : "Новая запись", h("div.col", {}, field("Название", title), h("div.grid2", {}, field("Дата", day), field("Время", time)),
      h("div.grid2", {}, field("Платформа", plat), field("Статус", st)), field("Заметки", notes), x.id ? toFlow : null),
      { foot: [x.id ? btn("Удалить", async () => { if (await confirmBox("Удалить запись?")) { await api("/api/planner/" + x.id, { method: "DELETE" }); m.close(); draw(); } }, "ghost danger", "trash") : null, h("div", { style: { flex: 1 } }), btn("Отмена", () => m.close()), btn("Сохранить", save, "pri", "check")] });
    setTimeout(() => title.focus(), 50);
  }

  function ideas() {
    const niche = h("input.in", { placeholder: "Например: тренировки и питание для новичков" }), aud = h("input.in", { placeholder: "Аудитория (необязательно)" });
    const count = select([5, 7, 10, 15, 20, 30].map(n => [n, n + " идей"]), "7"), every = select([[1, "каждый день"], [2, "через день"], [3, "раз в 3 дня"], [7, "раз в неделю"]], "1");
    const plat = select(PL, "tiktok"), lang = select(LANGS, "ru"), start = h("input.in", { type: "date", value: iso(new Date()) }), box = h("div");
    const goB = btn("Придумать и разложить", async () => {
      if (!niche.value.trim()) return toast("Опишите тему", true);
      goB.disabled = true;
      try { const r = await runTool("/api/planner/ideas", { niche: niche.value, audience: aud.value, count: +count.value, every: +every.value, platform: plat.value, language: lang.value, start: start.value }, box, "Идеи для контента"); m.close(); toast(`Добавлено идей: ${r.added}`); draw(); }
      catch (e) { box.replaceChildren(h("div.err", {}, e.message)); goB.disabled = false; }
    }, "pri", "sparkles");
    const m = modal("ИИ-идеи для календаря", h("div.col", {}, field("Тема / ниша", niche), field("Аудитория", aud), h("div.grid2", {}, field("Сколько", count), field("Как часто", every)),
      h("div.grid2", {}, field("Платформа", plat), field("Язык", lang)), field("С какого дня", start), h("p.dim", { style: { fontSize: "12px" } }, "ИИ придумывает только идеи — без выдуманной статистики просмотров."), box), { foot: [btn("Отмена", () => m.close()), goB] });
  }
  draw();
}
