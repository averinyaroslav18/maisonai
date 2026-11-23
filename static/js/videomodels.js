// «Все модели видео»: бесплатные и платные способы генерации в одном списке, выбор одним нажатием.
import { api, h, btn, toast, fail, modal, loadProviders, go } from "./lib.js";

const SRC = { agnes: "Agnes AI", hf_spaces: "Hugging Face", comfyui: "Ваш компьютер", slideshow: "MaisonAI", fal: "fal.ai", veo: "Google", runway: "Runway" };
const usd = v => v == null ? "цена неизвестна" : v === 0 ? "бесплатно" : "$" + (v < 0.1 ? v.toFixed(3) : v.toFixed(2));

export async function openVideoModels(onDone) {
  const body = h("div.vm", {}, h("div.vm-load", {}, "Загружаю все модели и цены…"));
  const m = modal("Все модели видео", body, { size: "wide" });
  let d, budget = null;
  try { [d, budget] = await Promise.all([api("/api/video/catalog"), api("/api/costs").then(r => r.budget).catch(() => null)]); }
  catch (x) { body.replaceChildren(h("div.note.warn", {}, x.message)); return; }
  let tab = d.current.pid && ["fal", "veo", "runway"].includes(d.current.pid) ? "paid" : "free", q = "", src = "", kind = "", sort = "cheap";
  const isCur = x => x.pid === d.current.pid && (!x.model || x.model === d.current.model);
  const choose = async x => {
    if (!d.can_edit) { toast("Модель выбирает владелец программы", true); return; }
    try {
      await api("/api/video/choose", { body: { pid: x.pid, model: x.model } });
      d.current = { pid: x.pid, model: x.model }; await loadProviders(true);
      const paid = ["fal", "veo", "runway"].includes(x.pid);
      toast(d.configured[x.pid] ? (paid ? `Выбрано: ${x.label}. Перед каждым запуском покажу цену и попрошу подтвердить.` : `Выбрано: ${x.label}`) : `Выбрано: ${x.label}. Осталось подключить ключ ${SRC[x.pid]} в Настройках → Провайдеры.`, !d.configured[x.pid]);
      draw(); onDone && onDone();
    } catch (e) { fail(e); }
  };
  const row = x => h("div.vm-row" + (isCur(x) ? ".on" : ""), {},
    h("div.vm-main", {}, h("b", {}, x.label), h("div.vm-meta", {}, h("span.tag", {}, SRC[x.pid] || x.src), h("span.dim", {}, x.kind),
      x.pid === "fal" && x.price != null ? h("span.dim", {}, `$${x.price} ${["second", "seconds", "sec", "s"].includes(x.unit) ? "за секунду" : /token/.test(x.unit || "") ? "за " + x.unit.replace("tokens", "токенов") : ["video", "videos"].includes(x.unit) ? "за ролик" : x.unit}`) : null), x.note ? h("div.vm-note", {}, x.note) : null),
    h("div.vm-price", {}, h("b", {}, usd(x.price5)), h("span.dim", {}, x.price5 ? "за ролик 5 с" : "")),
    h("div.vm-act", {}, isCur(x) ? h("span.tag.ok", {}, "выбрано") : btn("Выбрать", () => choose(x), "sm" + (x.price5 == null && x.pid === "fal" ? " ghost" : " pri"), null, x.price5 == null && x.pid === "fal" ? { disabled: true, title: "fal.ai не сообщает цену этой модели — MaisonAI её не запускает" } : {}),
      !d.configured[x.pid] && x.pid !== "slideshow" ? h("a.vm-key", { href: "#settings", onclick: () => m.close() }, "нужен ключ") : null));
  const list = h("div.vm-list"), cnt = h("span.dim");
  const tabs = h("div.seg", {}, ...[["free", "Бесплатно"], ["paid", "Платно"]].map(([k, l]) => h("button" + (tab === k ? ".on" : ""), { type: "button", onclick: () => { tab = k; draw(); } }, l)));
  const qIn = h("input.in", { placeholder: "Поиск: kling, veo, seedance, wan, hailuo…", oninput: e => { q = e.target.value.toLowerCase(); draw(); } });
  const srcSel = h("select.in", { onchange: e => { src = e.target.value; draw(); } }, ...[["", "Все сервисы"], ["fal", "fal.ai"], ["veo", "Google Veo"], ["runway", "Runway"]].map(([v, l]) => h("option", { value: v }, l)));
  const kindSel = h("select.in", { onchange: e => { kind = e.target.value; draw(); } }, ...[["", "Фото и текст"], ["картинка", "Оживить фото"], ["текст", "Только из текста"]].map(([v, l]) => h("option", { value: v }, l)));
  const sortSel = h("select.in", { onchange: e => { sort = e.target.value; draw(); } }, ...[["cheap", "Сначала дешёвые"], ["exp", "Сначала дорогие (обычно качественнее)"], ["name", "По названию"]].map(([v, l]) => h("option", { value: v }, l)));
  const filters = h("div.vm-filters", {}, qIn, srcSel, kindSel, sortSel);
  const warn = h("div");
  function draw() {
    tabs.querySelectorAll("button").forEach((b, i) => b.classList.toggle("on", (i ? "paid" : "free") === tab));
    filters.style.display = tab === "paid" ? "" : "none";
    let items = tab === "free" ? d.free : d.paid.filter(x => (!src || x.pid === src) && (!kind || x.kind.includes(kind)) && (!q || (x.label + " " + x.model).toLowerCase().includes(q)));
    if (tab === "paid") items = [...items].sort((a, b) => sort === "name" ? a.label.localeCompare(b.label) : ((a.price5 ?? 1e9) - (b.price5 ?? 1e9)) * (sort === "exp" ? -1 : 1));
    cnt.textContent = tab === "paid" ? `${items.length} моделей · fal.ai: ${d.fal_models}` : "";
    list.replaceChildren(...items.slice(0, 400).map(row));
    warn.replaceChildren(...(tab === "paid" ? [h("div.note", {}, "Платные модели списывают деньги с вашего баланса у выбранного сервиса (fal.ai, Google или Runway). MaisonAI перед каждым запуском показывает точную цену и ждёт «Подтвердить». Цены — живые с fal.ai и официальные тарифы Google/Runway."),
      budget && budget.daily <= 0 ? h("div.note.warn", {}, "Сейчас бюджет на платные запуски 0 $ — платное видео не запустится. Поднимите лимит: Настройки → Расходы.", " ", h("a", { href: "#settings", onclick: () => m.close() }, "Открыть")) : null,
      !d.paid.some(x => x.pid === "fal" && !["minimax/h3-max-turbo/image-to-video", "minimax/h3-max/image-to-video", "fal-ai/kling-video/v3/pro/image-to-video", "bytedance/seedance-2.0/image-to-video", "fal-ai/minimax/hailuo-02-fast/image-to-video", "fal-ai/kling-video/v2.5-turbo/pro/image-to-video"].includes(x.model)) ? h("div.note", {}, "Полный живой список fal.ai загрузится, когда будет интернет (и ключ fal.ai — для цен).") : null] : [h("div.note", {}, "Бесплатные способы. Лучшее настоящее видео бесплатно сейчас — Agnes Video 2.5 Flash (персонажи двигаются, до 12 с, ключ бесплатный). Запасной — Wan 2.2 через Hugging Face.")]).filter(Boolean));
  }
  body.replaceChildren(h("div.vm-top", {}, tabs, cnt, h("div.sp"), btn("Обновить цены", async e => { const b = e.currentTarget; b.disabled = true; try { d = { ...await api("/api/video/catalog?refresh=true"), can_edit: d.can_edit }; draw(); toast("Список обновлён"); } catch (x) { fail(x); } b.disabled = false; }, "sm ghost", "refresh")), warn, filters, list);
  draw();
}
