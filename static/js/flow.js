import { state, api, paidApi, h, icon, btn, fail, toast, go, field, select, segmented, RATIOS, LANGS, trackJob, waitJob, jobCard, handoff, pickAsset, download, fmtDate, confirmBox, styleSelect, copy } from "./lib.js";

// Maison Flow: идея → концепция → сценарий → раскадровка → сцены → озвучка → субтитры → предпросмотр → экспорт → обложка
export async function render(page, _k, arg) {
  if (arg && /^\d+$/.test(arg)) return editor(page, +arg);
  return start(page);
}

async function job(path, body, box, title) {   // запуск задачи (с ценой, если есть платное) и ожидание
  const r = await paidApi(path, { body: body || {} });
  trackJob(r.job, title); if (box) jobCard(box, r.job, title);
  return waitJob(r.job);
}

// ---------- старт: идея ----------
async function start(page) {
  const idea = h("textarea.in.big-in", { rows: 3, placeholder: "Одна идея — например: «Почему утро решает всё: мотивация для тех, кто только начал ходить в зал»" });
  const pre = handoff.take("flow_idea"); if (pre) idea.value = pre;
  const own = h("textarea.in", { rows: 4, placeholder: "Вставьте свой текст озвучки — ИИ разобьёт его на сцены и придумает визуал" });
  const ownBox = h("div.hidden", {}, field("Свой сценарий", own));
  const src = segmented([["ai", "Сценарий пишет ИИ"], ["own", "У меня свой сценарий"]], "ai", v => ownBox.classList.toggle("hidden", v !== "own"));
  const ratio = segmented(RATIOS, "9:16");
  const dur = select([[15, "15 с"], [30, "30 с"], [45, "45 с"], [60, "60 с"], [90, "90 с"]], "30");
  const scenes = select([[0, "Авто"], ...[3, 4, 5, 6, 8, 10].map(n => [n, n + " сцен"])], "0");
  const lang = select(LANGS, state.user?.prefs?.language || "ru");
  const style = h("input.in", { placeholder: "Например: чёрно-белое кино, жёсткий контраст, плёночное зерно" });
  const sty = styleSelect();
  const voice = h("select.in");
  const chars = h("select.in", {}, h("option", { value: "" }, "Без сохранённого персонажа"));
  const out = h("div");
  api("/api/tools/voices").then(r => voice.replaceChildren(...r.voices.filter(v => v.locale === "multi" || /^(ru|uk|en)-/i.test(v.locale)).map(v => h("option", { value: v.id }, v.name || v.id)))).then(() => { voice.value = "ru-RU-SvetlanaNeural"; }).catch(() => { });
  const preChar = handoff.take("flow_char");
  api("/api/intel/characters").then(cs => { chars.append(...cs.map(c => h("option", { value: c.id }, c.name))); if (preChar) chars.value = preChar; }).catch(() => { });
  const go_ = btn("Создать концепцию и раскадровку", async () => {
    if (!idea.value.trim() && !(src.value === "own" && own.value.trim())) return toast("Опишите идею ролика", true);
    go_.disabled = true;
    try {
      const r = await job("/api/flow/start", { idea: idea.value, own_script: src.value === "own" ? own.value : "", ratio: ratio.value, duration: +dur.value, scenes: +scenes.value,
        language: lang.value, style: style.value, voice: voice.value || "ru-RU-SvetlanaNeural", character_id: chars.value || null, style_id: sty.value || null }, out, "Maison Flow: концепция");
      go("#/flow/" + r.project_id);
    } catch (e) { out.replaceChildren(h("div.err", {}, e.message)); }
    go_.disabled = false;
  }, "pri wide lg", "sparkles");
  const list = h("div.flow-list");
  page.append(
    h("section.flow-hero", {},
      h("div.eyebrow", {}, "Maison Flow"),
      h("h1.display", {}, "Одна идея.", h("br"), h("span", {}, "Готовый ролик.")),
      h("p.lead", {}, "Концепция, сценарий, раскадровка от AI Director, сцены, озвучка, субтитры, обложка и экспорт MP4 — в одном проекте. Каждую сцену можно посмотреть и перегенерировать отдельно."),
      h("ol.pipeline", {}, ...["Сценарий", "Раскадровка", "Сцены", "Озвучка", "Субтитры", "Монтаж", "MP4"].map((t, i) => h("li", { style: { "--i": i } }, h("b", {}, String(i + 1).padStart(2, "0")), t)))),
    h("div.grid-flow", {},
      h("div.panel.glass.col", {}, field("Идея", idea), src, ownBox,
        h("div.grid2", {}, field("Формат", ratio), field("Длительность", dur)),
        h("div.grid2", {}, field("Сцен", scenes), field("Язык", lang)),
        field("Визуальный стиль", style, "необязательно"), field("Visual DNA", sty, "сохранённый стиль"),
        h("div.grid2", {}, field("Голос", voice), field("Персонаж", chars, "Character Lab")),
        go_, out),
      h("div.col", {}, h("div.row", {}, h("h3", { style: { margin: 0, flex: 1 } }, "Мои Flow-проекты")), list)));
  try {
    const fs = await api("/api/flow");
    list.replaceChildren(...(fs.length ? fs.map((f, i) => h("a.flow-card", { href: "#/flow/" + f.id, style: { "--i": i } },
      h("div.fc-cover", { style: { backgroundImage: f.cover_url ? `url("${f.cover_url}")` : "" } }, f.final ? h("span.tag.ok", {}, "MP4 готов") : null),
      h("div.fc-body", {}, h("b", {}, f.title), h("span.dim", {}, `${f.ready}/${f.scenes} сцен готово · ${fmtDate(f.updated)}`)))) : [h("div.empty", {}, "Здесь появятся ваши ролики.")]));
  } catch (e) { list.replaceChildren(h("div.err", {}, e.message)); }
}

// ---------- проект ----------
const STATUS = { draft: "черновик", changed: "изменено", frame: "рисую кадр…", frame_ready: "кадр готов", clip: "оживляю…", ready: "готово" };
const CAM = ["push in", "pull out", "pan left", "pan right", "tilt up", "tilt down", "orbit", "handheld", "static"];

async function editor(page, pid) {
  let f = await api("/api/flow/" + pid);
  let dirty = false, saveT = null;
  const save = async () => {
    clearTimeout(saveT); if (!dirty) return;
    dirty = false;
    try { f = await api("/api/flow/" + pid, { method: "PUT", body: { flow: { title: f.title, voiceover_full: f.voiceover_full, character: f.character, caption: f.caption, hashtags: f.hashtags, cover: f.cover, settings: f.settings, scenes: f.scenes } } }); }
    catch (e) { fail(e); }
  };
  const touch = () => { dirty = true; clearTimeout(saveT); saveT = setTimeout(save, 900); };
  const reload = async () => { await save(); f = await api("/api/flow/" + pid); draw(); };
  const busy = h("div");
  const runAll = async (path, body, title) => { await save(); try { const r = await job(path, body, busy, title); busy.replaceChildren(); await reload(); return r; } catch (e) { busy.replaceChildren(h("div.err", {}, e.message)); } };
  const root = h("div.flow-editor"); page.append(root);

  function draw() {
    const st = f.settings;
    const title = h("input.title-in", { value: f.title, oninput: e => { f.title = e.target.value; touch(); }, "aria-label": "Название ролика" });
    const ready = f.scenes.filter(s => s.clip).length, frames = f.scenes.filter(s => s.frame).length;
    const total = f.scenes.reduce((a, s) => a + s.duration, 0);
    const steps = [["Сценарий", true], ["Раскадровка", true], ["Кадры", frames === f.scenes.length], ["Клипы", ready === f.scenes.length], ["Озвучка", !!f.voice_a], ["Предпросмотр", !!f.preview_a], ["MP4", !!f.final_a]];
    const provNote = f.video_paid ? h("div.note", {}, "Видео делает fal.ai — перед запуском покажу цену, без подтверждения ничего не списывается.")
      : ["hf_spaces", "comfyui"].includes(f.video_provider) ? h("div.note", {}, "Клипы оживляет нейросеть (бесплатный лимит). Когда лимит кончится, сцена соберётся движением камеры — бесплатно.")
      : h("div.note.warn", {}, "Нейросетевое видео не подключено — сцены соберутся из кадров с движением камеры (бесплатно). Подключить: Настройки → Провайдеры (Hugging Face — бесплатно, fal.ai — платно).");

    // --- концепция ---
    const c = f.concept || {};
    const concept = h("div.panel.glass.col.concept", {},
      h("div.row", {}, h("h3", { style: { margin: 0, flex: 1 } }, "Концепция"), btn("Новая версия", async () => {
        if (!await confirmBox("Пересоздать концепцию, сценарий и раскадровку по той же идее? Текущие сцены будут заменены.", "Пересоздать")) return;
        await runAll("/api/flow/start", { idea: f.idea, ratio: st.ratio, duration: Math.round(total), language: st.language, style: st.style, voice: st.voice, project_id: pid }, "Новая версия");
      }, "sm ghost", "refresh")),
      h("div.ckv", {}, ...[["Суть", c.logline], ["Хук", c.hook], ["Аудитория", c.audience], ["Тон", c.tone], ["Музыка", c.music_mood]].filter(x => x[1]).map(([k, v]) => h("div", {}, h("span.mono-up", {}, k), h("p", {}, v)))),
      field("Визуальный стиль", h("input.in", { value: st.style || "", oninput: e => { st.style = e.target.value; touch(); } })),
      field("Персонаж (одинаковый во всех сценах)", h("input.in", { value: f.character || "", oninput: e => { f.character = e.target.value; touch(); } })));

    // --- сценарий / озвучка ---
    const vo = h("textarea.in", { rows: 5, oninput: e => { f.voiceover_full = e.target.value; touch(); } }); vo.value = f.voiceover_full || "";
    const voice = h("select.in"), emo = select([["", "Обычно"], ["calm", "Спокойно"], ["happy", "Бодро"], ["excited", "Как хук TikTok"], ["serious", "Серьёзно"], ["ad", "Как реклама"], ["whisper", "Шёпот"]], st.emotion || "");
    api("/api/tools/voices").then(r => { voice.replaceChildren(...r.voices.filter(v => v.locale === "multi" || /^(ru|uk|en)-/i.test(v.locale)).map(v => h("option", { value: v.id }, v.name || v.id))); voice.value = st.voice; }).catch(() => { });
    const script = h("div.panel.glass.col", {}, h("h3", { style: { margin: 0 } }, "Озвучка и субтитры"), vo,
      h("div.grid2", {}, field("Голос", voice), field("Подача", emo, "для голосов Gemini")),
      f.voice_a ? h("audio", { src: f.voice_a.url, controls: true, style: { width: "100%" } }) : null,
      h("div.row", {}, btn(f.voice_a ? "Переозвучить" : "Озвучить", async () => {
        st.voice = voice.value; st.emotion = emo.value; touch();
        await runAll(`/api/flow/${pid}/voice`, { voice: voice.value, emotion: emo.value }, "Озвучка");
      }, "pri", "mic"),
        h("label.row", {}, h("input", { type: "checkbox", checked: st.subtitles, onchange: e => { st.subtitles = e.target.checked; touch(); } }), "Субтитры"),
        h("label.row", {}, h("input", { type: "checkbox", checked: st.transitions, onchange: e => { st.transitions = e.target.checked; touch(); } }), "Переходы")),
      h("div.row", {}, f.music_a ? h("span.tag", {}, "Музыка: " + f.music_a.name) : h("span.dim", {}, "Без музыки"),
        btn(f.music_a ? "Сменить" : "Добавить музыку", async () => { const a = await pickAsset(["audio"], "Музыка"); if (a) { st.music_id = a.id; touch(); await reload(); } }, "sm ghost", "volume"),
        f.music_a ? btn("", async () => { st.music_id = null; touch(); await reload(); }, "sm icon ghost", "x", { title: "Убрать музыку" }) : null));

    // --- сцены ---
    const sceneEls = f.scenes.map((s, i) => sceneCard(s, i));
    const scenesBox = h("div.scenes", {}, ...sceneEls,
      h("button.scene-add", { type: "button", onclick: () => { f.scenes.push({ voiceover: "", visual: "", duration: 3, camera_move: "push in" }); touch(); save().then(reload); } }, icon("plus"), "Добавить сцену"));

    // --- результат ---
    let hd;
    const result = h("div.panel.glass.col.result", {},
      h("h3", { style: { margin: 0 } }, "Предпросмотр и экспорт"),
      f.final_a || f.preview_a ? h("div.viewer.vert", {}, h("video", { src: (f.final_a || f.preview_a).url, controls: true, playsInline: true })) : h("div.empty", {}, "Соберите предпросмотр, чтобы увидеть ролик целиком."),
      h("div.row.wrap", {},
        btn("Предпросмотр", () => runAll(`/api/flow/${pid}/render`, { final: false }, "Предпросмотр"), "", "play"),
        btn("Экспорт MP4", () => runAll(`/api/flow/${pid}/render`, { final: true, hd: hd.checked }, "Экспорт MP4"), "pri", "download"),
        h("label.row", {}, (hd = h("input", { type: "checkbox" })), "1080p")),
      f.final_a ? h("div.row.wrap", {}, btn("Скачать MP4", () => download(f.final_a.url, (f.title || "MaisonAI") + ".mp4"), "sm", "download"),
        btn("Открыть в редакторе", () => { handoff.set("editor", f.spec); go("#/editor"); }, "sm ghost", "cut")) : null,
      h("div.sep"),
      h("div.row", {}, h("b", { style: { flex: 1 } }, "Обложка"), btn(f.thumbnail_a ? "Пересоздать" : "Создать обложку", () => runAll(`/api/flow/${pid}/cover`, {}, "Обложка"), "sm", "image")),
      f.thumbnail_a ? h("img.cover-prev", { src: f.thumbnail_a.url + "?v=" + Date.now(), alt: "Обложка" }) : null,
      f.caption ? h("div.copy-block", { onclick: () => copy(f.caption + "\n" + (f.hashtags || []).join(" ")), title: "Нажмите, чтобы скопировать" }, f.caption, h("br"), (f.hashtags || []).join(" ")) : null);

    root.replaceChildren(
      h("div.flow-top", {}, btn("", () => go("#/flow"), "ghost icon", "arrow", { style: { transform: "scaleX(-1)" }, "aria-label": "Назад" }), title,
        h("span.dim", {}, `${f.scenes.length} сцен · ${total.toFixed(1)} с · ${st.ratio}`)),
      h("ol.stepper", {}, ...steps.map(([t, ok], i) => h("li", { class: ok ? "ok" : "" }, h("b", {}, ok ? icon("check") : String(i + 1)), t))),
      provNote,
      h("div.flow-actions", {},
        btn("AI Director: доработать ракурсы и свет", () => runAll(`/api/flow/${pid}/director`, { note: "" }, "AI Director"), "", "camera"),
        btn("Нарисовать все кадры", () => runAll(`/api/flow/${pid}/build`, { what: "frames", mode: "auto" }, "Кадры сцен"), "", "image"),
        btn("Сгенерировать все сцены", () => runAll(`/api/flow/${pid}/build`, { what: "all", mode: "auto" }, "Сцены"), "pri", "film"),
        btn("Без нейровидео (бесплатно)", () => runAll(`/api/flow/${pid}/build`, { what: "all", mode: "motion" }, "Сцены: монтаж"), "ghost", "layers")),
      busy,
      h("div.flow-grid", {}, h("div.col", {}, concept, script), h("div.col", {}, h("div.row", {}, h("h3", { style: { margin: 0 } }, "Раскадровка")), scenesBox), result));
  }

  function sceneCard(s, i) {
    const box = h("div");
    const media_ = s.clip_a ? h("video", { src: s.clip_a.url, muted: true, loop: true, playsInline: true, onmouseenter: e => e.target.play(), onmouseleave: e => e.target.pause(), onclick: e => e.target.paused ? e.target.play() : e.target.pause() })
      : s.frame_a ? h("img", { src: s.frame_a.url, alt: "Кадр сцены " + (i + 1) }) : h("div.ph-frame", {}, icon("image"), h("span", {}, "кадра нет"));
    const inp = (k, ph, rows) => { const e = rows ? h("textarea.in", { rows, placeholder: ph }) : h("input.in", { placeholder: ph }); e.value = s[k] || ""; e.oninput = () => { s[k] = e.value; touch(); }; return e; };
    const dur = h("input.in", { type: "number", min: 1.5, max: 15, step: 0.5, value: s.duration, oninput: e => { s.duration = Math.max(1.5, Math.min(15, +e.target.value || 3)); touch(); } });
    const cam = select(CAM.map(x => [x, x]), CAM.includes(s.camera_move) ? s.camera_move : "push in", { onchange: e => { s.camera_move = e.target.value; touch(); } });
    const details = h("details.scene-more", {}, h("summary", {}, "Режиссёр: ракурс, свет, композиция"),
      h("div.col", { style: { gap: "8px", marginTop: "8px" } }, field("Что в кадре (для генерации)", inp("visual", "по-английски", 3)), field("Что движется", inp("action", "по-английски")),
        h("div.grid2", {}, field("Ракурс", inp("camera_angle", "low angle…")), field("Объектив", inp("lens", "35mm…"))),
        h("div.grid2", {}, field("Свет", inp("lighting", "rim light…")), field("Композиция", inp("composition", "rule of thirds…"))),
        btn("AI Director для этой сцены", async () => { await save(); try { await job(`/api/flow/${pid}/director`, { scene_ids: [s.id] }, box, "AI Director"); box.replaceChildren(); reload(); } catch (e) { box.replaceChildren(h("div.err", {}, e.message)); } }, "sm ghost", "camera")));
    const run = async (kind, body) => { await save(); try { await job(`/api/flow/${pid}/scenes/${s.id}/${kind}`, body, box, `Сцена ${i + 1}`); box.replaceChildren(); reload(); } catch (e) { box.replaceChildren(h("div.err", {}, e.message)); } };
    return h("article.scene", { style: { "--i": i } },
      h("div.scene-media", {}, media_, h("span.scene-n", {}, String(i + 1).padStart(2, "0")), h("span.scene-st" + (s.clip ? ".ok" : ""), {}, s.clip_kind === "ai" ? "нейровидео" : s.clip_kind === "motion" ? "движение камеры" : STATUS[s.status] || "")),
      h("div.scene-body", {},
        field("Озвучка сцены", inp("voiceover", "фраза", 2)), field("Текст на экране", inp("on_screen_text", "необязательно")),
        h("div.grid2", {}, field("Секунд", dur), field("Камера", cam)),
        details, s.note ? h("div.note.warn", { style: { fontSize: "12px" } }, s.note) : null,
        h("div.row.wrap", {},
          btn(s.frame ? "Новый кадр" : "Кадр", () => run("frame", {}), "sm", "image"),
          btn(s.clip ? "Новый клип" : "Клип", () => run("clip", { mode: "auto" }), "sm pri", "film"),
          btn("", () => run("clip", { mode: "motion" }), "sm ghost icon", "layers", { title: "Клип движением камеры (бесплатно)" }),
          h("div", { style: { flex: 1 } }),
          btn("", () => { if (i > 0) { [f.scenes[i - 1], f.scenes[i]] = [f.scenes[i], f.scenes[i - 1]]; touch(); draw(); } }, "sm ghost icon", "up", { title: "Выше" }),
          btn("", () => { if (i < f.scenes.length - 1) { [f.scenes[i + 1], f.scenes[i]] = [f.scenes[i], f.scenes[i + 1]]; touch(); draw(); } }, "sm ghost icon", "down", { title: "Ниже" }),
          btn("", async () => { if (f.scenes.length < 2) return toast("Нужна хотя бы одна сцена", true); if (await confirmBox(`Удалить сцену ${i + 1}?`)) { f.scenes.splice(i, 1); touch(); draw(); } }, "sm ghost icon danger", "trash", { title: "Удалить" })),
        box));
  }
  draw();
  return () => { save(); };
}
