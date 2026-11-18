import { state, api, h, icon, btn, fail, toast, runTool, handoff, go, field, select, segmented, RATIOS, download, providerBadge, loadProviders } from "./lib.js";
import { sourcePicker } from "./analyze.js";

const FIELDS = [["environment", "Окружение"], ["lighting", "Освещение"], ["palette_words", "Цветовая палитра"], ["camera_style", "Стиль съёмки"], ["camera_moves", "Движения камеры"],
  ["editing", "Монтаж и темп"], ["mood", "Атмосфера"], ["audio", "Звук"]];
const CHAR_FIELDS = [["appearance", "Внешность"], ["clothing", "Одежда"], ["hair", "Причёска"], ["expression", "Мимика и поведение"]];

export async function render(page) {
  await loadProviders().catch(() => { });
  const pre = handoff.take("recreate") || {};
  let step = 1, src = null, dna = null, frames = [], plan = null;
  const locks = {};
  const stepsEl = h("div.steps");
  const body = h("div");
  const drawSteps = () => stepsEl.replaceChildren(...["1 · Референс", "2 · Визуальная ДНК", "3 · Новый сценарий", "4 · Готовый ролик"].map((t, i) => h("div", { class: i + 1 === step ? "on" : i + 1 < step ? "done" : "" }, t)));
  page.append(
    h("div.ph", {}, h("div", {}, h("h1", {}, "Воссоздание стиля"), h("p", {}, "Загрузите ролик-референс: ИИ разберёт персонажей, одежду, свет, палитру, камеру и монтаж. Вы меняете нужное — и получаете новый оригинальный ролик, а не копию.")), h("div.sp"),
      h("div.row", {}, providerBadge("video_understanding"), providerBadge("image"), providerBadge("video"))),
    stepsEl, body);

  // ---------- шаг 1 ----------
  function s1() {
    step = 1; drawSteps();
    const out = h("div");
    const go1 = btn("Разобрать референс", async () => {
      if (!src) return toast("Загрузите видео или вставьте ссылку", true);
      go1.disabled = true;
      try {
        const r = await runTool("/api/tools/recreate/analyze", { asset_id: src.asset?.id || null, url: src.url || null }, out, "Разбор референса");
        dna = r.dna; frames = r.frames || []; s2();
      } catch (e) { out.replaceChildren(h("div.err", {}, e.message)); go1.disabled = false; }
    }, "pri wide", "scan");
    body.replaceChildren(h("div.split", {}, h("div.panel.col", {}, sourcePicker(v => src = v), go1,
      h("p.dim", { style: { fontSize: "12px" } }, "Используйте ролики, на которые у вас есть права, или берите их только как визуальный ориентир. Реальные люди и логотипы в новый ролик не переносятся.")), out));
  }

  // ---------- шаг 2: ДНК с замками ----------
  function s2() {
    step = 2; drawSteps();
    const fld = (key, label, obj, k) => {
      const ta = h("textarea", { value: obj[k] ?? "", oninput: e => obj[k] = e.target.value, "aria-label": label });
      const lk = locks[key] ? "lock" : "unlock";
      const box = h("div.fld" + (locks[key] ? ".locked" : ""), {}, h("div.hd", {}, label,
        h("button.btn.sm.ghost.lock", { type: "button", title: "Сохранить без изменений", onclick: e => { locks[key] = !locks[key]; box.classList.toggle("locked", locks[key]); e.currentTarget.replaceChildren(icon(locks[key] ? "lock" : "unlock"), locks[key] ? "сохранить" : "можно менять"); } }, icon(lk), locks[key] ? "сохранить" : "можно менять")), ta);
      return box;
    };
    const chars = (dna.characters || []).map((c, i) => h("div.panel", {}, h("h3", {}, "Персонаж " + (i + 1) + (c.role ? " · " + c.role : "")),
      h("div.dna", {}, ...CHAR_FIELDS.map(([k, l]) => fld(`characters.${i}.${k}`, l, c, k)))));
    const pal = (dna.palette || []).filter(x => /^#[0-9a-f]{3,8}$/i.test(x));
    const instr = h("textarea.in", { rows: 4, placeholder: "Например: такой же визуальный стиль, но персонаж в чёрном костюме, другая причёска, действие в ночном Токио, полностью новый сценарий", value: pre.instructions || "" });
    const dur = segmented([[10, "10 с"], [15, "15 с"], [20, "20 с"], [30, "30 с"]], 15);
    const lang = select([["ru", "Русский"], ["uk", "Українська"], ["en", "English"]], state.user.prefs?.language === "uk" ? "uk" : "ru");
    const ratio = segmented(RATIOS, "9:16");
    const out = h("div");
    const next = btn("Составить новый сценарий", async () => {
      next.disabled = true;
      try {
        const r = await runTool("/api/tools/recreate/plan", { dna, locks, instructions: instr.value, duration: +dur.value, language: lang.value, ratio: ratio.value }, out, "Новый сценарий");
        plan = r.plan; plan._ratio = ratio.value; plan._lang = lang.value; s3();
      } catch (e) { out.replaceChildren(h("div.err", {}, e.message)); next.disabled = false; }
    }, "pri", "arrow");
    body.replaceChildren(h("div.col", {},
      frames.length ? h("div.panel", {}, h("h3", {}, "Кадры референса"), h("div.frames", {}, ...frames.map(f => h("img", { src: f.url, alt: f.name })))) : null,
      ...chars,
      h("div.panel", {}, h("div.row", { style: { marginBottom: "12px" } }, h("h3", { style: { margin: 0, flex: 1 } }, "Сцена и стиль"), pal.length ? h("div.sw", { style: { width: "200px" }, title: pal.join(" ") }, ...pal.map(c => h("i", { style: { background: c } }))) : null),
        h("div.dna", {}, ...FIELDS.filter(([k]) => dna[k] !== undefined).map(([k, l]) => fld(k, l, dna, k)))),
      dna.scenes?.length ? h("div.panel", {}, h("h3", {}, "Последовательность сцен референса"), h("div.scenes", {}, ...dna.scenes.map(s => h("div.sc", { style: { gridTemplateColumns: "72px 1fr" } }, h("span.t", {}, s.time), h("div", {}, s.description))))) : null,
      h("div.panel.col", {}, h("h3", { style: { margin: 0 } }, "Что изменить"), instr, h("div.grid3", {}, field("Длительность", dur), field("Язык", lang), field("Формат", ratio)),
        h("div.row", {}, btn("Назад", s1, "ghost"), h("div", { style: { flex: 1 } }), next), out)));
  }

  // ---------- шаг 3: план сцен ----------
  function s3() {
    step = 3; drawSteps();
    const voice = h("select.in");
    api("/api/tools/voices").then(r => {
      const l = plan._lang === "uk" ? "uk" : plan._lang === "en" ? "en" : "ru";
      voice.replaceChildren(...r.voices.filter(v => v.locale.toLowerCase().startsWith(l)).map(v => h("option", { value: v.id }, v.id)));
    }).catch(fail);
    const withVoice = h("input", { type: "checkbox", checked: true }), withSubs = h("input", { type: "checkbox", checked: true });
    const vo = h("textarea.in", { rows: 3, value: plan.voiceover_full || "", oninput: e => plan.voiceover_full = e.target.value });
    const out = h("div");
    const produce = btn("Создать ролик", async () => {
      produce.disabled = true;
      try {
        const r = await runTool("/api/tools/recreate/produce", { plan, ratio: plan._ratio, voice: voice.value || "ru-RU-SvetlanaNeural", with_voice: withVoice.checked, with_subs: withSubs.checked }, out, "Новый ролик");
        s4(r);
      } catch (e) { out.replaceChildren(h("div.err", {}, e.message)); produce.disabled = false; }
    }, "pri", "film");
    body.replaceChildren(h("div.col", {},
      h("div.panel", {}, h("h3", {}, plan.title || "Новый ролик"), h("p", {}, plan.concept || ""), plan.changes?.length ? h("ul.dash-list", { style: { marginTop: "10px" } }, ...plan.changes.map(c => h("li", {}, c))) : null),
      ...(plan.scenes || []).map((s, i) => h("div.plan-scene", {}, h("div.no", {}, String(i + 1).padStart(2, "0")), h("div.col", {},
        h("div.grid2", {}, field("Длительность, с", h("input.in", { type: "number", min: 1, max: 15, value: s.duration, oninput: e => s.duration = +e.target.value })), field("Текст на экране", h("input.in", { value: s.on_screen_text || "", oninput: e => s.on_screen_text = e.target.value }))),
        field("Кадр (промпт)", h("textarea.in", { rows: 3, value: s.image_prompt || "", oninput: e => s.image_prompt = e.target.value })),
        field("Движение", h("input.in", { value: s.motion_prompt || "", oninput: e => s.motion_prompt = e.target.value }))))),
      h("div.panel.col", {}, field("Текст озвучки", vo), field("Голос", voice), h("label.row", {}, withVoice, "Озвучка"), h("label.row", {}, withSubs, "Субтитры по озвучке"),
        h("div.row", {}, btn("Назад", s2, "ghost"), h("div", { style: { flex: 1 } }), produce), out)));
  }

  // ---------- шаг 4 ----------
  function s4(r) {
    step = 4; drawSteps();
    body.replaceChildren(h("div.split", {}, h("div.viewer", {}, h("video", { src: r.video.url, controls: true, playsInline: true, autoplay: true })),
      h("div.panel.col", {}, h("h3", {}, "Готово"), h("dl.kv", {}, h("dt", {}, "Длительность"), h("dd", {}, r.info.duration + " с"), h("dt", {}, "Размер"), h("dd", {}, `${r.info.width}×${r.info.height}`)),
        btn("Скачать MP4", () => download(r.video.url, r.video.name), "pri", "download"),
        btn("Доработать в редакторе", () => { handoff.set("editor", r.spec); go("#/editor"); }, "", "cut"),
        btn("Изменить сценарий", s3, "ghost", "edit"), btn("Новый референс", () => { dna = null; plan = null; s1(); }, "ghost", "refresh"))));
  }
  s1();
}
