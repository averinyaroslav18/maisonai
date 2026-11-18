import { state, api, h, icon, btn, fail, toast, runTool, handoff, go, copy, field, select, segmented, LANGS, providerBadge, loadProviders, styleSelect } from "./lib.js";

export async function render(page) {
  await loadProviders().catch(() => { });
  const topic = h("textarea.in", { placeholder: "О чём ролик? Например: как собрать чемодан на неделю в одну ручную кладь", rows: 3 });
  const dur = segmented([[15, "15 с"], [30, "30 с"], [45, "45 с"], [60, "60 с"]], 30);
  const lang = select(LANGS, state.user.prefs?.language || "uk");
  const style = h("input.in", { placeholder: "Например: дружелюбно, с юмором, экспертно", list: "styles" });
  const aud = h("input.in", { placeholder: "Например: студенты 18–24, любят путешествовать" });
  const goal = select([["", "На выбор ИИ"], ["удержание до конца", "Досмотр до конца"], ["сохранения и репосты", "Сохранения и репосты"], ["комментарии", "Комментарии"], ["переход в профиль / подписка", "Подписки"], ["продажа продукта", "Продажа"]], "");
  const extra = h("input.in", { placeholder: "Пожелания: упомянуть акцию, без сленга…" });
  const styleSel = styleSelect("");
  const out = h("div");
  let last = null; const titles = [];
  const go_ = async (again = false) => {
    if (!topic.value.trim()) { topic.focus(); return toast("Опишите тему ролика", true); }
    gen.disabled = true;
    try {
      const r = await runTool("/api/tools/script", { topic: topic.value.trim(), duration: +dur.value, language: lang.value, style: style.value, audience: aud.value, goal: goal.value, extra: extra.value, avoid: again ? titles : [], style_id: styleSel.value || null }, out, "Сценарий");
      show(r);
    } catch (e) { out.replaceChildren(h("div.err", {}, e.message)); }
    gen.disabled = false;
  };
  const gen = btn("Сгенерировать", () => go_(false), "pri wide", "wand");
  page.append(
    h("div.ph", {}, h("div", {}, h("h1", {}, "Сценарии"), h("p", {}, "Идея, хук, полный сценарий, текст озвучки, сцены, субтитры, заголовок, описание и хештеги. Каждая генерация — новый угол подачи.")), h("div.sp"), providerBadge("text")),
    h("div.split", {},
      h("div.panel.sticky.col", {}, field("Тема", topic), field("Длительность", dur), field("Язык", lang), field("Стиль подачи", style), field("Целевая аудитория", aud), field("Желаемый результат", goal), field("Дополнительно", extra), field("Стиль Visual DNA", styleSel, "хуки и подача"), gen,
        h("datalist", { id: "styles" }, ...["дружелюбно", "экспертно", "с юмором", "дерзко", "вдохновляюще", "спокойно и эстетично", "сторителлинг"].map(v => h("option", { value: v })))),
      out));
  out.append(h("div.empty", {}, "Здесь появится сценарий"));

  function show(r) {
    const s = r.script; last = r; titles.push(s.title);
    const sec = (title, body, copyText) => h("div.sec", {}, h("h4", {}, title, copyText ? btn("", () => copy(copyText), "sm ghost icon", "copy", { "aria-label": "Копировать" }) : null), body);
    out.replaceChildren(h("div.panel", {},
      h("div.row", { style: { marginBottom: "14px" } }, h("span.tag", {}, "Подход: " + s.angle), h("div", { style: { flex: 1 } }),
        btn("Сгенерировать ещё", () => go_(true), "sm", "refresh")),
      sec("Хук · 0–3 секунды", h("div.big-hook", {}, s.hook), s.hook),
      sec("Идея", h("p", {}, s.idea)),
      sec("Сцены", h("div.scenes", {}, ...s.scenes.map(x => h("div.sc", {}, h("span.t", {}, x.time), h("div", {}, x.visual, x.on_screen_text ? h("div.dim", {}, "Текст: " + x.on_screen_text) : null), h("div.muted", {}, x.voiceover))))),
      sec("Текст озвучки", h("div.copy-block", {}, s.voiceover), s.voiceover),
      sec("Полный сценарий", h("div.copy-block", {}, s.script), s.script),
      s.visual_tips.length ? sec("Рекомендации по визуалу", h("ul.dash-list", {}, ...s.visual_tips.map(t => h("li", {}, t)))) : null,
      s.subtitles.length ? sec("Субтитры", h("div.copy-block", {}, s.subtitles.join("\n")), s.subtitles.join("\n")) : null,
      sec("Заголовок", h("p", {}, h("b", {}, s.title)), s.title),
      sec("Описание публикации", h("p", {}, s.description), s.description),
      sec("Хештеги", h("p", {}, s.hashtags.join(" ")), s.hashtags.join(" ")),
      h("div.sec", {}, h("h4", {}, "Дальше"), h("div.row", {},
        btn("Озвучить", () => { handoff.set("voice", { text: s.voiceover, language: s.params?.language }); go("#/voice"); }, "", "mic"),
        btn("Кадры по сценам", frames, "", "image"),
        btn("Видео по сценарию", () => { handoff.set("video", { prompt: s.video_prompt || s.image_prompts.join(". "), duration: s.params?.duration }); go("#/video"); }, "", "film"),
        btn("Спросить ассистента", () => { handoff.set("ask", `Помоги снять ролик по сценарию «${s.title}». Хук: ${s.hook}`); go("#/assistant"); }, "ghost", "chat")))));
  }

  async function frames() {
    const s = last?.script; if (!s?.image_prompts?.length) return toast("В сценарии нет описаний кадров", true);
    const box = h("div"); out.querySelector(".panel").append(box);
    try {
      const prompts = s.image_prompts.slice(0, 6);
      for (let i = 0; i < prompts.length; i++) {
        const r = await runTool("/api/tools/image", { prompt: prompts[i], ratio: "9:16", preset: "frame" }, box, `Кадр ${i + 1}`);
        toast(`Кадр ${i + 1} из ${prompts.length} готов`);
      }
      box.replaceChildren(h("div.note", {}, "Кадры сохранены. Откройте «Изображения» или соберите ролик в редакторе."), btn("Открыть изображения", () => go("#/image"), "sm"));
    } catch (e) { box.replaceChildren(h("div.err", {}, e.message)); }
  }

  const pre = handoff.take("script");
  if (pre) { topic.value = pre.script.params?.topic || ""; show(pre); }
  const t = handoff.take("script_topic"); if (t) { topic.value = t.topic || ""; if (t.extra) extra.value = t.extra; }
}
