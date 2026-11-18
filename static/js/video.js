import { api, h, icon, btn, fail, toast, runTool, handoff, go, field, select, segmented, RATIOS, pickAsset, assetCard, previewModal, toggleFav, deleteAsset, download, providerBadge, loadProviders, styleSelect, uploadFiles, dropZone, state } from "./lib.js";

const CAMERA = [["", "На выбор ИИ"], ["static locked-off shot", "Статичная камера"], ["slow dolly in", "Плавный наезд"], ["slow dolly out", "Плавный отъезд"], ["smooth tracking shot following the subject", "Сопровождение"],
  ["orbit around the subject", "Облёт вокруг"], ["handheld documentary camera", "Ручная камера"], ["drone aerial shot", "Дрон"], ["slow pan left to right", "Панорама"]];
const STYLES = [["", "На выбор ИИ"], ["photorealistic, cinematic, natural light", "Реалистичный, кино"], ["35mm film, grain, warm tones", "Плёнка 35 мм"], ["anime style", "Аниме"],
  ["3D animation, Pixar-like", "3D-анимация"], ["moody noir, high contrast black and white", "Нуар"], ["bright commercial look, clean", "Рекламный"], ["vintage VHS aesthetic", "VHS"]];

export async function render(page) {
  const prov = await loadProviders(true).catch(() => null);
  const pre = handoff.take("video") || {};
  const pid = prov?.active?.video || "";
  const caps = prov?.video_caps?.[pid] || { t2v: true, i2v: true, v2v: false, durations: [5] };
  const disabled = {};
  if (!caps.i2v) disabled.i2v = "Выбранный генератор не поддерживает стартовую картинку";
  disabled.v2v = "Ни один из бесплатных генераторов пока не умеет «видео → видео». Используйте «Воссоздание стиля».";
  const mode = segmented([["photos", "Много фото → видео"], ["t2v", "Текст → видео"], ["i2v", "Картинка → видео"], ["v2v", "Видео → видео"]], pre.mode && !disabled[pre.mode] ? pre.mode : "photos", v => drawMode(v), disabled);
  const realAI = ["hf_spaces", "comfyui"].includes(pid);
  // ---------- режим «Много фото → видео» ----------
  let photos = [];
  const pgrid = h("div.pgrid");
  const drawPhotos = () => {
    pgrid.replaceChildren(...photos.map((a, i) => h("div.pitem", { style: { "--i": i } },
      h("div.pimg", { style: { backgroundImage: `url("${a.url}")` } }), h("span.pnum", {}, String(i + 1)),
      h("div.pact", {}, btn("", () => { if (i > 0) { [photos[i - 1], photos[i]] = [photos[i], photos[i - 1]]; drawPhotos(); } }, "sm icon", "up", { title: "Раньше" }),
        btn("", () => { photos.splice(i, 1); drawPhotos(); }, "sm icon danger", "x", { title: "Убрать" })))));
    pcount.textContent = photos.length ? `${photos.length} фото · ≈ ${Math.round(photos.length * +perClip.value)} с видео` : "Добавьте от 1 до 20 фото";
  };
  const pcount = h("span.dim");
  const pzone = dropZone("Загрузите фото — можно сразу много", "image/*", async fs => { const as = await uploadFiles(fs.slice(0, 20 - photos.length)); photos.push(...as); drawPhotos(); }, true);
  const plib = btn("Из библиотеки", async () => { const a = await pickAsset(["image"], "Фото"); if (a && photos.length < 20) { photos.push(a); drawPhotos(); } }, "sm ghost", "folder");
  const idea = h("textarea.in", { rows: 3, placeholder: "О чём ролик? Например: наша поездка в горы — весело и тепло. ИИ сам придумает, как оживить каждое фото." });
  const pratio = segmented(RATIOS, "9:16");
  const perClip = select([[3, "3 с"], [4, "4 с"], [5, "5 с"]], "4", { onchange: () => drawPhotos() });
  const aiMotion = h("input", { type: "checkbox", checked: realAI, disabled: !realAI });
  const voMode = segmented([["none", "Без голоса"], ["auto", "ИИ напишет текст"], ["text", "Свой текст"]], "auto", v => voText.classList.toggle("hidden", v !== "text"));
  const voText = h("textarea.in.hidden", { rows: 3, placeholder: "Текст озвучки" });
  const voice = h("select.in");
  api("/api/tools/voices").then(r => { const l = state.user?.prefs?.language || "uk"; voice.replaceChildren(...r.voices.filter(v => v.locale.toLowerCase().startsWith(l === "uk" ? "uk" : l === "en" ? "en" : "ru") || v.locale.toLowerCase().startsWith("ru")).map(v => h("option", { value: v.id }, v.id))); }).catch(() => { });
  const subs = h("input", { type: "checkbox", checked: true }), caps2 = h("input", { type: "checkbox" }), trans = h("input", { type: "checkbox", checked: true });
  let music = null; const mbox = h("div");
  const drawMusic = () => mbox.replaceChildren(music ? h("div.src-thumb", {}, h("div.th.ic", {}, icon("volume")), h("div", { style: { flex: 1, minWidth: 0 } }, h("b", {}, "Музыка"), h("div.dim", {}, music.name)), btn("", () => { music = null; drawMusic(); }, "sm icon ghost", "x"))
    : btn("Добавить музыку", async () => { const a = await pickAsset(["audio"], "Музыка"); if (a) { music = a; drawMusic(); } }, "sm ghost", "volume"));
  drawMusic();
  const photosPanel = h("div.col", {},
    h("div", { class: realAI ? "note" : "note warn" }, realAI ? "Каждое фото оживёт настоящей нейросетью Wan 2.2: двигаются люди, волосы, одежда, вода, свет. Бесплатно ≈5–8 фото в день; если лимит кончится, остальные фото соберутся динамичным монтажом."
      : "Сейчас фото соберутся динамичным монтажом с переходами. Чтобы фото по-настоящему оживали (двигались люди и предметы), подключите бесплатный Hugging Face: Настройки → Провайдеры → «Hugging Face · Wan 2.2»."),
    pzone, h("div.row", {}, plib, pcount), pgrid, field("Идея ролика", idea), h("div.grid2", {}, field("Секунд на фото", perClip), field("Формат", pratio)),
    h("label.row", {}, aiMotion, "Оживить фото нейросетью" + (realAI ? "" : " (нужен Hugging Face или ComfyUI)")),
    field("Озвучка", voMode), voText, field("Голос", voice), h("label.row", {}, subs, "Субтитры по озвучке"), h("label.row", {}, caps2, "Подписи к кадрам"),
    h("label.row", {}, trans, "Красивые переходы между фото"), mbox);
  drawPhotos();
  const prompt = h("textarea.in", { rows: 5, placeholder: "Например: реалистичное видео девушки, которая гуляет по Парижу, кинематографичная камера, естественные движения", value: pre.prompt || "" });
  const ratio = segmented(RATIOS, pre.ratio || "9:16");
  const durs = caps.durations.length > 10 ? [3, 5, 8, 10, 15, 20, 30] : caps.durations;
  const duration = select(durs.map(d => [d, d + " с"]), String(pre.duration && durs.includes(+pre.duration) ? pre.duration : durs.includes(5) ? 5 : durs[0]));
  const res = segmented([["720p", "720p"], ["1080p", "1080p"]], "720p");
  const style = select(STYLES, ""), camera = select(CAMERA, "");
  const styleSel = styleSelect(pre.style_id || "");
  const chars = h("input.in", { placeholder: "Например: девушка 25 лет, каре, бежевый тренч" });
  let source = pre.source || null;
  const srcBox = h("div");
  const drawSrc = () => srcBox.replaceChildren(source ? h("div.src-thumb", {}, h("div.th", { style: { backgroundImage: `url("${source.url}")` } }), h("div", { style: { flex: 1 } }, h("b", {}, "Стартовый кадр"), h("div.dim", {}, source.name)), btn("", () => { source = null; drawSrc(); }, "sm icon ghost", "x"))
    : btn("Выбрать стартовую картинку", async () => { const a = await pickAsset(["image"], "Стартовый кадр"); if (a) { source = a; drawSrc(); } }, "wide", "image"));
  const textOnly = [];
  const drawMode = v => { srcBox.classList.toggle("hidden", v !== "i2v"); photosPanel.classList.toggle("hidden", v !== "photos"); textOnly.forEach(e => e.classList.toggle("hidden", v === "photos")); drawSrc(); };
  setTimeout(() => drawMode(mode.value));
  const out = h("div"), gal = h("div.gallery");
  const improve = btn("Улучшить промпт с ИИ", async () => {
    if (!prompt.value.trim()) return toast("Сначала опишите идею", true);
    improve.disabled = true;
    try { const r = await api("/api/tools/improve", { body: { text: prompt.value, target: "video", ratio: ratio.value, style: style.value, camera: camera.value, characters: chars.value } }); prompt.value = r.prompt; toast(r.summary_ru || "Готово"); }
    catch (e) { fail(e); } improve.disabled = false;
  }, "sm", "wand");
  const gen = btn("Создать видео", async () => {
    if (mode.value === "photos") return makeFromPhotos();
    if (!prompt.value.trim()) return toast("Опишите видео", true);
    if (mode.value === "i2v" && !source) return toast("Выберите стартовую картинку", true);
    gen.disabled = true;
    try {
      const r = await runTool("/api/tools/video", { prompt: prompt.value.trim(), mode: mode.value, ratio: ratio.value, duration: +duration.value, source: source?.id || null, style: style.value, camera: camera.value, characters: chars.value, resolution: res.value, style_id: styleSel.value || null }, out, "Видео");
      out.replaceChildren(h("div.col", {}, h("div.viewer", {}, h("video", { src: r.asset.url, controls: true, playsInline: true, autoplay: true, loop: true })),
        r.ai_video === false ? h("div.note", {}, "Это монтаж из ИИ-кадров с движением камеры. Для настоящего нейросетевого видео подключите бесплатный Hugging Face (Настройки → Провайдеры).") : h("div.note", {}, "Сделано: " + r.provider),
        h("div.row", {}, btn("Скачать", () => download(r.asset.url, r.asset.name), "", "download"), btn("Добавить озвучку", () => { handoff.set("editor_add", { video: r.asset.id }); go("#/editor"); }, "", "mic"),
          btn("В редактор", () => { handoff.set("editor_add", { video: r.asset.id }); go("#/editor"); }, "", "cut"))));
      load();
    } catch (e) { out.replaceChildren(h("div.err", {}, e.message)); }
    gen.disabled = false;
  }, "pri wide", "film");
  async function makeFromPhotos() {
    if (!photos.length) return toast("Добавьте фото", true);
    gen.disabled = true;
    try {
      const r = await runTool("/api/tools/photos_video", { asset_ids: photos.map(a => a.id), idea: idea.value, ratio: pratio.value, per_clip: +perClip.value, ai_motion: aiMotion.checked,
        voiceover: voMode.value === "text" ? voText.value : "", auto_voice: voMode.value === "auto", voice: voice.value || "ru-RU-SvetlanaNeural",
        language: (voice.value || "ru").slice(0, 2), subtitles: subs.checked, captions: caps2.checked, music_id: music?.id || null, transitions: trans.checked }, out, "Видео из фото");
      out.replaceChildren(h("div.col.result-in", {}, h("div.viewer", {}, h("video", { src: r.video.url, controls: true, playsInline: true, autoplay: true, loop: true })),
        h("div.row", {}, r.ai_clips ? h("span.tag.ok", {}, `оживлено нейросетью: ${r.ai_clips}`) : null, r.montage_clips ? h("span.tag", {}, `монтажом: ${r.montage_clips}`) : null, h("span.dim", {}, `${r.info.duration} с · ${r.info.width}×${r.info.height}`)),
        r.notes?.length ? h("div.note.warn", {}, r.notes.slice(0, 3).join(" ")) : null,
        r.voiceover ? h("div.copy-block", {}, r.voiceover) : null,
        h("div.row", {}, btn("Скачать MP4", () => download(r.video.url, r.video.name), "pri", "download"), btn("Доработать в редакторе", () => { handoff.set("editor", r.spec); go("#/editor"); }, "", "cut"))));
      load();
    } catch (e) { out.replaceChildren(h("div.err", {}, e.message)); }
    gen.disabled = false;
  }
  async function load() {
    try {
      const items = (await api("/api/assets?kind=video&limit=60")).filter(a => !a.meta?.uploaded);
      gal.replaceChildren(...(items.length ? items.map(a => assetCard(a, { onClick: () => previewModal(a), actions: [btn("", () => toggleFav(a, load), "sm icon", "star"), btn("", () => download(a.url, a.name), "sm icon", "download"), btn("", () => deleteAsset(a, load), "sm icon danger", "trash")] })) : [h("div.empty", { style: { gridColumn: "1/-1" } }, "Здесь появятся ваши видео")]));
    } catch (e) { gal.replaceChildren(h("div.err", {}, e.message)); }
  }
  page.append(
    h("div.ph", {}, h("div", {}, h("h1", {}, "Видео"), h("p", {}, "Опишите ролик обычным текстом — ИИ превратит его в задание для видеомодели. Вертикальный формат 9:16 по умолчанию.")), h("div.sp"), providerBadge("video")),
    caps.note ? h("div.note", { style: { marginBottom: "16px" } }, caps.note, pid === "slideshow" ? " Настоящее нейросетевое видео бесплатно — подключите Hugging Face в Настройках → Провайдеры (5 минут видеокарты в день)." : "") : null,
    h("div.split", {},
      h("div.panel.col.sticky", {}, field("Режим", mode), photosPanel, srcBox, ...(textOnly.push(field("Описание видео", prompt), h("div.row", {}, improve),
        field("Соотношение сторон", ratio), h("div.grid2", {}, field("Длительность", duration), field("Качество", res)),
        field("Visual DNA", styleSel, "сохранённый стиль"), field("Стиль", style), field("Движение камеры", camera), field("Персонажи", chars)), textOnly), gen),
      h("div.col", {}, out, h("div.mono-up", {}, "Мои видео"), gal)));
  load();
}
