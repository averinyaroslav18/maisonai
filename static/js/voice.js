import { state, api, h, icon, btn, fail, toast, runTool, handoff, go, field, select, segmented, LANGS, mmss, download, pickAsset, uploadFiles, providerBadge, loadProviders, assetCard, deleteAsset, toggleFav } from "./lib.js";

// Плеер с волной (реальная форма сигнала из файла)
export function wavePlayer(url, name) {
  const audio = new Audio(url); audio.preload = "auto";
  const cv = h("canvas", { width: 1200, height: 168, "aria-label": "Звуковая волна, нажмите для перемотки" });
  const time = h("span.time", {}, "0:00 / 0:00");
  const play = btn("", () => audio.paused ? audio.play() : audio.pause(), "icon pri", "play", { "aria-label": "Воспроизвести" });
  let peaks = null;
  const draw = () => {
    const ctx = cv.getContext("2d"), W = cv.width, H = cv.height; ctx.clearRect(0, 0, W, H);
    const p = audio.duration ? audio.currentTime / audio.duration : 0;
    if (!peaks) { ctx.fillStyle = "#34343A"; ctx.fillRect(0, H / 2 - 1, W, 2); return; }
    const n = peaks.length, bw = W / n;
    for (let i = 0; i < n; i++) {
      const v = Math.max(0.03, peaks[i]) * (H * 0.92);
      ctx.fillStyle = i / n < p ? "#FFFFFF" : "#4A4A50";
      ctx.fillRect(i * bw + 1, (H - v) / 2, Math.max(1, bw - 2), v);
    }
    ctx.fillStyle = "#FF3B30"; ctx.fillRect(p * W - 1, 0, 2, H);
  };
  fetch(url, { credentials: "same-origin" }).then(r => r.arrayBuffer()).then(b => new (window.AudioContext || window.webkitAudioContext)().decodeAudioData(b)).then(buf => {
    const d = buf.getChannelData(0), n = 160, step = Math.floor(d.length / n); peaks = [];
    for (let i = 0; i < n; i++) { let m = 0; for (let j = i * step; j < (i + 1) * step; j += 16) m = Math.max(m, Math.abs(d[j] || 0)); peaks.push(m); }
    const mx = Math.max(...peaks) || 1; peaks = peaks.map(x => x / mx); draw();
  }).catch(() => draw());
  const upd = () => { time.textContent = `${mmss(audio.currentTime)} / ${mmss(audio.duration || 0)}`; draw(); };
  audio.ontimeupdate = upd; audio.onloadedmetadata = upd;
  audio.onplay = () => { play.replaceChildren(icon("pause")); const loop = () => { if (!audio.paused) { draw(); requestAnimationFrame(loop); } }; loop(); };
  audio.onpause = audio.onended = () => play.replaceChildren(icon("play"));
  cv.onclick = e => { const r = cv.getBoundingClientRect(); if (audio.duration) audio.currentTime = (e.clientX - r.left) / r.width * audio.duration; };
  draw();
  const el = h("div.player", {}, cv, h("div.ctl", {}, play, btn("Скачать MP3", () => download(url, name), "sm", "download"), time));
  el.stop = () => audio.pause();
  return el;
}

export async function render(page) {
  await loadProviders().catch(() => { });
  const pre = handoff.take("voice") || {};
  const text = h("textarea.in", { rows: 8, placeholder: "Текст для озвучки…", value: pre.text || "" });
  const counter = h("span.dim", {}, "");
  text.oninput = () => counter.textContent = `${text.value.length} симв. · ≈ ${Math.round(text.value.trim().split(/\s+/).filter(Boolean).length / 2.3)} с`;
  text.oninput();
  const lang = select([["uk", "Українська"], ["ru", "Русский"], ["en", "English"], ["de", "Deutsch"], ["pl", "Polski"], ["es", "Español"], ["fr", "Français"], ["it", "Italiano"], ["pt", "Português"], ["tr", "Türkçe"], ["*", "Все языки"]], pre.language || state.user.prefs?.language || "uk");
  const gender = segmented([["", "Все"], ["Female", "Женские"], ["Male", "Мужские"]], "");
  const voice = h("select.in");
  const rate = h("input", { type: "range", min: -50, max: 100, value: 0, step: 5 }), rateL = h("span.dim", {}, "0%");
  const pitch = h("input", { type: "range", min: -30, max: 30, value: 0, step: 2 }), pitchL = h("span.dim", {}, "0 Гц");
  const vol = h("input", { type: "range", min: -50, max: 50, value: 0, step: 5 }), volL = h("span.dim", {}, "0%");
  rate.oninput = () => rateL.textContent = (rate.value > 0 ? "+" : "") + rate.value + "%";
  pitch.oninput = () => pitchL.textContent = (pitch.value > 0 ? "+" : "") + pitch.value + " Гц";
  vol.oninput = () => volL.textContent = (vol.value > 0 ? "+" : "") + vol.value + "%";
  const out = h("div"), list = h("div.col");
  let voices = [];
  const fill = () => {
    const l = lang.value, g = gender.value;
    const vs = voices.filter(v => (l === "*" || v.locale.toLowerCase().startsWith(l)) && (!g || v.gender === g));
    voice.replaceChildren(...vs.map(v => h("option", { value: v.id }, `${v.id.split("-").slice(2).join("-").replace("Neural", "") || v.id} · ${v.gender === "Female" ? "жен." : v.gender === "Male" ? "муж." : ""} · ${v.locale}`)));
    const pref = state.user.prefs?.voice; if (pref && vs.some(v => v.id === pref)) voice.value = pref;
    if (!vs.length) voice.append(h("option", { value: "" }, "Нет голосов для этого фильтра"));
  };
  lang.onchange = fill; gender.addEventListener("click", () => setTimeout(fill));
  const gen = btn("Озвучить", async () => {
    if (!text.value.trim()) return toast("Введите текст", true);
    if (!voice.value) return toast("Выберите голос", true);
    gen.disabled = true;
    try {
      const r = await runTool("/api/tools/voice", { text: text.value, voice: voice.value, rate: +rate.value, pitch: +pitch.value, volume: +vol.value }, out, "Озвучка");
      showResult(r.asset); loadList();
      api("/api/account/profile", { body: { prefs: { voice: voice.value } } }).then(() => state.user.prefs = { ...state.user.prefs, voice: voice.value }).catch(() => { });
    } catch (e) { out.replaceChildren(h("div.err", {}, e.message)); }
    gen.disabled = false;
  }, "pri wide", "mic");

  function showResult(a) {
    out.replaceChildren(h("div.col", {}, h("div.mono-up", {}, "Результат"), wavePlayer(a.url, a.name),
      h("div.row", {}, btn("Добавить к видео", () => addToVideo(a), "", "film"), btn("В редактор", () => { handoff.set("editor_add", { audio: a.id }); go("#/editor"); }, "", "cut"))));
  }
  async function addToVideo(a) {
    const v = await pickAsset(["video"], "Выберите видео для озвучки"); if (!v) return;
    const box = h("div"); out.append(box);
    try { const r = await runTool("/api/tools/editor/mux", { video: v.id, audio: a.id }, box, "Озвучка к видео"); box.replaceChildren(h("div.note", {}, "Готово: «" + r.asset.name + "» сохранено в библиотеку."), h("video", { src: r.asset.url, controls: true, playsInline: true, style: { maxWidth: "100%", maxHeight: "60vh", marginTop: "8px" } })); }
    catch (e) { box.replaceChildren(h("div.err", {}, e.message)); }
  }
  async function loadList() {
    try {
      const items = await api("/api/assets?kind=audio&limit=30");
      list.replaceChildren(...(items.length ? items.map(a => h("div.prov", {}, h("div.hd", {}, icon("volume"), h("b", { style: { flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, a.name),
        a.meta?.voice ? h("span.tag", {}, a.meta.voice) : a.meta?.uploaded ? h("span.tag", {}, "загружено") : null,
        btn("", () => showResult(a), "sm icon ghost", "play", { "aria-label": "Открыть" }), btn("", () => toggleFav(a, loadList), "sm icon ghost", "star", { "aria-label": "В избранное" }),
        btn("", () => deleteAsset(a, loadList), "sm icon ghost danger", "trash", { "aria-label": "Удалить" })))) : [h("div.empty", {}, "Озвучек пока нет")]));
    } catch (e) { list.replaceChildren(h("div.err", {}, e.message)); }
  }
  page.append(
    h("div.ph", {}, h("div", {}, h("h1", {}, "Голос"), h("p", {}, "Текст в речь: мужские и женские голоса, украинский, русский, английский и другие языки. Тайминги слов сохраняются — по ним строятся точные субтитры.")), h("div.sp"), providerBadge("tts")),
    h("div.split", {},
      h("div.panel.col.sticky", {}, field("Текст", text, counter), field("Язык", lang), field("Голос", h("div.col", {}, gender, voice)),
        field("Скорость", rate, rateL), field("Высота (интонация)", pitch, pitchL), field("Громкость", vol, volL), gen),
      h("div.col", {}, out, h("div.panel", {}, h("h3", {}, "Своё аудио"), h("p.dim", { style: { marginBottom: "10px", fontSize: "13px" } }, "Загрузите запись голоса или музыку, чтобы добавить её к видео."),
        btn("Загрузить аудио", async () => { const a = await pickAsset(["audio"], "Аудио"); if (a) { showResult(a); loadList(); } }, "", "upload")),
        h("div.panel", {}, h("h3", {}, "Последние озвучки"), list))));
  out.append(h("div.empty", {}, "Здесь появится плеер с результатом"));
  try { voices = (await api("/api/tools/voices")).voices; } catch (e) { fail(e); }
  fill(); loadList();
}
