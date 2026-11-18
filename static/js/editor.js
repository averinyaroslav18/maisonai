import { state, api, h, icon, btn, fail, toast, runTool, handoff, go, field, select, segmented, RATIOS, pickAsset, uploadFiles, assetCard, thumbUrl, download, mmss, confirmBox } from "./lib.js";

const MOTIONS = [["zoom_in", "Наезд"], ["zoom_out", "Отъезд"], ["pan_right", "Панорама →"], ["pan_left", "Панорама ←"], ["none", "Без движения"]];
const RAT = { "9:16": 9 / 16, "1:1": 1, "4:5": 4 / 5, "16:9": 16 / 9 };

function mediaDuration(url, kind) {
  return new Promise(res => {
    const m = document.createElement(kind === "audio" ? "audio" : "video"); m.preload = "metadata"; m.src = url;
    m.onloadedmetadata = () => res(isFinite(m.duration) ? m.duration : 0); m.onerror = () => res(0);
    setTimeout(() => res(0), 15000);
  });
}

export async function render(page) {
  let spec = { format: state.user.prefs?.ratio || "9:16", clips: [], audio: [], subtitles: [], texts: [], clip_volume: 1, fade: true, sub_size: "m", sub_position: "bottom", sub_style: "caption" };
  const assetsById = new Map();
  let sel = null, pps = 40, playing = false, t = 0, raf = null, t0 = 0;

  // ---------- загрузка состояния ----------
  async function hydrate(s) {
    const ids = [...(s.clips || []), ...(s.audio || [])].map(x => x.asset);
    for (const id of ids) if (!assetsById.has(id)) {
      try { const list = await api("/api/assets?limit=500"); list.forEach(a => assetsById.set(a.id, a)); break; } catch { }
    }
    for (const c of s.clips || []) { const a = assetsById.get(c.asset); if (!a) continue; c.kind = a.kind; c.name = a.name; c.url = a.url; if (a.kind === "video") { c.src_duration ||= await mediaDuration(a.url, "video"); if (c.end == null) c.end = c.src_duration; c.start ||= 0; } else c.duration ||= 3; }
    for (const x of s.audio || []) { const a = assetsById.get(x.asset); if (!a) continue; x.name = a.name; x.url = a.url; x.kind = a.kind; x.src_duration ||= await mediaDuration(a.url, a.kind); x.start ||= 0; if (x.end == null) x.end = x.src_duration; }
    s.clips = (s.clips || []).filter(c => c.url); s.audio = (s.audio || []).filter(x => x.url);
    spec = { ...spec, ...s };
  }
  const clipLen = c => c.kind === "image" ? (+c.duration || 3) : Math.max(0.1, ((+c.end || c.src_duration || 0) - (+c.start || 0)) / (+c.speed || 1));
  const total = () => spec.clips.reduce((s, c) => s + clipLen(c), 0);
  const clipAt = tt => { let a = 0; for (const c of spec.clips) { const l = clipLen(c); if (tt < a + l) return [c, tt - a, a]; a += l; } return [null, 0, a]; };

  // ---------- разметка ----------
  const fmt = segmented(RATIOS, spec.format, v => { spec.format = v; layoutFrame(); save(); });
  const bin = h("div.gallery");
  const binSeg = segmented([["project", "Проект"], ["all", "Все"]], state.project ? "project" : "all", () => loadBin());
  const frame = h("div.ed-frame"), stage = h("div.ed-stage", {}, frame);
  const vEl = h("video", { playsInline: true, muted: false, preload: "auto" }), iEl = h("img", { alt: "" });
  const subEl = h("div.ov.bottom"), txtEl = h("div.ov.top.box");
  frame.append(iEl, vEl, txtEl, subEl);
  const playB = btn("", () => playing ? pause() : play(), "pri icon sm", "play", { "aria-label": "Просмотр" });
  const timeL = h("span.dim", {}, "0:00 / 0:00");
  const zoom = h("input", { type: "range", min: 10, max: 160, value: pps, style: { width: "120px" }, "aria-label": "Масштаб таймлайна", oninput: e => { pps = +e.target.value; drawTL(); } });
  const insp = h("div.ed-insp");
  const tl = h("div.ed-tl");
  const out = h("div");
  const exportHd = segmented([["0", "720p"], ["1", "1080p"]], "0");
  page.classList.add("wide"); page.style.maxWidth = "none";
  page.append(
    h("div.ph", {}, h("div", {}, h("h1", {}, "Редактор"), h("p", {}, "Обрезка, склейка, озвучка, субтитры, текст, громкость и формат. Предпросмотр приблизительный — итог собирается при экспорте.")), h("div.sp"),
      h("div.row", {}, fmt, btn("Очистить", async () => { if (await confirmBox("Очистить таймлайн?", "Очистить")) { spec.clips = []; spec.audio = []; spec.subtitles = []; spec.texts = []; sel = null; redraw(); save(); } }, "ghost sm", "trash"))),
    h("div.editor", {},
      h("div.ed-bin", {}, h("div.row", { style: { marginBottom: "8px" } }, binSeg), btn("Загрузить файлы", async () => { const inp = h("input", { type: "file", multiple: true, accept: "video/*,image/*,audio/*" }); inp.onchange = async () => { await uploadFiles([...inp.files]); loadBin(); }; inp.click(); }, "sm wide", "upload"), h("div", { style: { height: "8px" } }), bin),
      h("div.ed-view", {}, stage, h("div.ed-tbar", {}, playB, timeL, h("div", { style: { flex: 1 } }), h("span.dim", { style: { fontSize: "11px" } }, "Масштаб"), zoom)),
      insp, tl),
    h("div.panel", { style: { marginTop: "16px" } }, h("div.row", {}, h("h3", { style: { margin: 0, flex: 1 } }, "Экспорт"), exportHd,
      btn("Экспортировать MP4", doExport, "pri", "download")), out));

  // ---------- библиотека ----------
  async function loadBin() {
    const q = new URLSearchParams({ kind: "image,video,audio", limit: 200 });
    if (binSeg.value === "project" && state.project) q.set("project_id", state.project.id);
    try {
      const items = await api("/api/assets?" + q);
      items.forEach(a => assetsById.set(a.id, a));
      bin.replaceChildren(...(items.length ? items.map(a => assetCard(a, { onClick: () => add(a), square: true })) : [h("div.dim", { style: { gridColumn: "1/-1", fontSize: "12px" } }, "Нет файлов. Загрузите или создайте их в других разделах.")]));
    } catch (e) { bin.replaceChildren(h("div.err", {}, e.message)); }
  }
  async function add(a) {
    assetsById.set(a.id, a);
    if (a.kind === "audio") {
      const d = await mediaDuration(a.url, "audio");
      spec.audio.push({ asset: a.id, name: a.name, url: a.url, kind: "audio", at: 0, start: 0, end: d, src_duration: d, volume: 1 });
      if (a.meta?.segments?.length && !spec.subtitles.length && await confirmBox("У этой озвучки есть точные тайминги слов. Добавить субтитры автоматически?", "Добавить")) spec.subtitles = a.meta.segments.map(s => ({ ...s }));
      sel = { type: "audio", i: spec.audio.length - 1 };
    } else {
      const c = { asset: a.id, name: a.name, url: a.url, kind: a.kind, volume: 1, speed: 1 };
      if (a.kind === "video") { c.src_duration = await mediaDuration(a.url, "video"); c.start = 0; c.end = c.src_duration; } else { c.duration = 3; c.motion = MOTIONS[spec.clips.length % 4][0]; }
      spec.clips.push(c); sel = { type: "clip", i: spec.clips.length - 1 };
    }
    redraw(); save(); toast("Добавлено на таймлайн");
  }

  // ---------- кадр предпросмотра ----------
  function layoutFrame() {
    const r = RAT[spec.format] || 9 / 16, sw = stage.clientWidth - 24, sh = stage.clientHeight - 24;
    let w = sw, hh = w / r; if (hh > sh) { hh = sh; w = hh * r; }
    frame.style.width = Math.max(80, w) + "px"; frame.style.height = Math.max(80, hh) + "px";
    const base = Math.min(w, hh) * (r < 1 ? 1.25 : 1);
    subEl.style.fontSize = ({ s: .04, m: .055, l: .075, xl: .095 }[spec.sub_size] || .055) * base + "px";
    subEl.className = "ov " + (spec.sub_position || "bottom") + (spec.sub_style === "box" ? " box" : "");
    txtEl.style.fontSize = .075 * base + "px";
    showAt(t);
  }
  let curClip = null;
  function showAt(tt, fromPlay = false) {
    const [c, off] = clipAt(tt);
    if (!c) { vEl.style.display = "none"; iEl.style.display = "none"; }
    else if (c.kind === "image") {
      vEl.style.display = "none"; vEl.pause(); iEl.style.display = "block"; if (iEl.dataset.u !== c.url) { iEl.src = c.url; iEl.dataset.u = c.url; }
      const k = off / clipLen(c), z = { zoom_in: 1 + .18 * k, zoom_out: 1.18 - .18 * k, pan_left: 1.15, pan_right: 1.15, none: 1 }[c.motion || "zoom_in"];
      const x = c.motion === "pan_left" ? (1 - k) * 7 - 3.5 : c.motion === "pan_right" ? k * 7 - 3.5 : 0;
      iEl.style.transform = `scale(${z}) translateX(${x}%)`;
    } else {
      iEl.style.display = "none"; vEl.style.display = "block";
      if (curClip !== c) { if (vEl.dataset.u !== c.url) { vEl.src = c.url; vEl.dataset.u = c.url; } curClip = c; vEl.playbackRate = +c.speed || 1; }
      const want = (+c.start || 0) + off * (+c.speed || 1);
      if (!fromPlay || Math.abs(vEl.currentTime - want) > 0.35) { try { vEl.currentTime = want; } catch { } }
      vEl.volume = Math.max(0, Math.min(1, (+c.volume || 0) * (+spec.clip_volume || 0)));
      if (fromPlay && vEl.paused) vEl.play().catch(() => { });
    }
    const s = spec.subtitles.find(s => tt >= s.start && tt < s.end); subEl.textContent = s ? s.text : ""; subEl.style.display = s ? "" : "none";
    const x = spec.texts.find(s => tt >= s.start && tt < s.end); txtEl.textContent = x ? x.text : ""; txtEl.style.display = x ? "" : "none";
    if (x) txtEl.className = "ov box " + (x.position || "top");
    timeL.textContent = `${mmss(tt)} / ${mmss(total())}`;
    const ph = tl.querySelector(".playhead"), ln = tl.querySelector(".lane"); if (ph) ph.style.left = ((ln ? ln.offsetLeft : 100) + tt * pps) + "px";
  }
  const audios = new Map();
  function play() {
    if (!spec.clips.length) return toast("Добавьте клипы на таймлайн", true);
    if (t >= total()) t = 0;
    playing = true; playB.replaceChildren(icon("pause")); t0 = performance.now() - t * 1000; curClip = null;
    for (const x of spec.audio) {
      let a = audios.get(x); if (!a) { a = new Audio(x.url); audios.set(x, a); }
      a.volume = Math.max(0, Math.min(1, +x.volume || 0));
      const rel = t - (+x.at || 0);
      if (rel >= 0 && rel < (x.end - x.start)) { a.currentTime = (+x.start || 0) + rel; a.play().catch(() => { }); }
      else if (rel < 0) { a.currentTime = +x.start || 0; a._wait = true; }
    }
    const loop = () => {
      if (!playing) return;
      t = (performance.now() - t0) / 1000;
      if (t >= total()) { pause(); t = total(); showAt(t); return; }
      for (const x of spec.audio) { const a = audios.get(x); if (a && a._wait && t >= (+x.at || 0)) { a._wait = false; a.play().catch(() => { }); } if (a && !a.paused && t - (+x.at || 0) >= x.end - x.start) a.pause(); }
      showAt(t, true); raf = requestAnimationFrame(loop);
    };
    loop();
  }
  function pause() { playing = false; cancelAnimationFrame(raf); vEl.pause(); for (const a of audios.values()) a.pause(); playB.replaceChildren(icon("play")); }

  // ---------- таймлайн ----------
  function drawTL() {
    const T = Math.max(total(), ...spec.audio.map(x => (+x.at || 0) + (x.end - x.start)), ...spec.subtitles.map(s => s.end), 10);
    const width = T * pps + 40;
    const ruler = h("div.ruler", { style: { width: width + "px" } });
    const stepS = pps < 25 ? 5 : pps < 60 ? 2 : 1;
    for (let s = 0; s <= T; s += stepS) ruler.append(h("span", { style: { left: s * pps + "px" } }, mmss(s)));
    ruler.onclick = e => { const r = ruler.getBoundingClientRect(); t = Math.max(0, (e.clientX - r.left) / pps); if (playing) { pause(); } showAt(t); };
    const lane = (name, blocks) => h("div.trk", {}, h("div.nm", {}, name), h("div.lane", { style: { width: width + "px" } }, ...blocks));
    let acc = 0;
    const vb = spec.clips.map((c, i) => { const l = clipLen(c); const b = blk(c.name, acc, l, { type: "clip", i }, c.kind === "image" ? "" : "", c); acc += l; return b; });
    const ab = spec.audio.map((x, i) => blk(x.name, +x.at || 0, x.end - x.start, { type: "audio", i }, "au", x));
    const sb = spec.subtitles.map((s, i) => blk(s.text, s.start, s.end - s.start, { type: "sub", i }, "sub", s));
    const tb = spec.texts.map((s, i) => blk(s.text, s.start, s.end - s.start, { type: "text", i }, "sub", s));
    const wrap = h("div", { style: { position: "relative", minWidth: width + 100 + "px" } }, ruler,
      lane("Видео", vb), lane("Звук", ab), lane("Субтитры", sb), lane("Текст", tb), h("div.playhead"));
    tl.replaceChildren(wrap);
    const ln0 = wrap.querySelector(".lane"); ruler.style.marginLeft = ln0.offsetLeft + "px"; wrap.querySelector(".playhead").style.left = (ln0.offsetLeft + t * pps) + "px";
    if (!spec.clips.length) tl.append(h("div.dim", { style: { fontSize: "12px", padding: "6px 0" } }, "Нажмите на файл слева, чтобы добавить его на таймлайн. Блоки видео можно перетаскивать для смены порядка."));
  }
  function blk(label, start, len, ref, cls, obj) {
    const isSel = sel && sel.type === ref.type && sel.i === ref.i;
    const b = h("div.blk" + (cls ? "." + cls : "") + (isSel ? ".sel" : ""), { style: { left: start * pps + "px", width: Math.max(8, len * pps - 2) + "px" }, title: label },
      h("span.lb", {}, label));
    if (ref.type === "clip" && (obj.kind === "image" || obj.kind === "video")) b.style.backgroundImage = `url("${thumbUrl({ kind: obj.kind, url: obj.url })}")`;
    // перетаскивание: клипы — смена порядка, остальное — сдвиг по времени
    b.onpointerdown = e => {
      e.preventDefault(); sel = ref; drawInsp(); tl.querySelectorAll(".blk.sel").forEach(x => x.classList.remove("sel")); b.classList.add("sel");
      const x0 = e.clientX, left0 = start * pps; let moved = false; b.setPointerCapture(e.pointerId);
      b.onpointermove = ev => { const dx = ev.clientX - x0; if (Math.abs(dx) > 3) moved = true; b.style.left = Math.max(0, left0 + dx) + "px"; };
      b.onpointerup = ev => {
        b.onpointermove = b.onpointerup = null; if (!moved) return;
        const ns = Math.max(0, (left0 + ev.clientX - x0) / pps);
        if (ref.type === "clip") {
          const [c] = spec.clips.splice(ref.i, 1); let acc = 0, idx = spec.clips.length;
          for (let k = 0; k < spec.clips.length; k++) { const l = clipLen(spec.clips[k]); if (ns < acc + l / 2) { idx = k; break; } acc += l; }
          spec.clips.splice(idx, 0, c); sel = { type: "clip", i: idx };
        } else if (ref.type === "audio") obj.at = +ns.toFixed(2);
        else { const d = obj.end - obj.start; obj.start = +ns.toFixed(2); obj.end = +(ns + d).toFixed(2); }
        redraw(); save();
      };
    };
    return b;
  }

  // ---------- инспектор ----------
  function num(obj, key, label, step = 0.1, min = 0, max = 9999, after) {
    return field(label, h("input.in", { type: "number", step, min, max, value: obj[key] ?? "", onchange: e => { obj[key] = e.target.value === "" ? null : Math.max(min, Math.min(max, +e.target.value)); after && after(); redraw(); save(); } }));
  }
  function drawInsp() {
    const tabs = h("div.seg", { style: { marginBottom: "12px" } });
    const body = h("div.col");
    const mk = (id, l) => h("button", { type: "button", class: inspTab === id ? "on" : "", onclick: () => { inspTab = id; drawInsp(); } }, l);
    tabs.append(mk("item", "Элемент"), mk("subs", "Субтитры"), mk("set", "Общее"));
    if (inspTab === "item") {
      if (!sel) body.append(h("p.dim", { style: { fontSize: "13px" } }, "Выберите блок на таймлайне."));
      else if (sel.type === "clip") {
        const c = spec.clips[sel.i]; if (!c) { sel = null; return drawInsp(); }
        body.append(h("b", {}, c.name));
        if (c.kind === "image") body.append(num(c, "duration", "Длительность, с", 0.5, 0.5, 60), field("Движение камеры", select(MOTIONS, c.motion || "zoom_in", { onchange: e => { c.motion = e.target.value; save(); showAt(t); } })));
        else body.append(h("div.dim", { style: { fontSize: "12px" } }, `Исходник: ${mmss(c.src_duration)}`), h("div.grid2", {}, num(c, "start", "Начало, с", 0.1, 0, c.src_duration), num(c, "end", "Конец, с", 0.1, 0, c.src_duration)),
          field("Громкость клипа", h("input", { type: "range", min: 0, max: 2, step: 0.05, value: c.volume ?? 1, oninput: e => { c.volume = +e.target.value; save(); } })),
          field("Скорость", select([[0.5, "0.5×"], [0.75, "0.75×"], [1, "1×"], [1.25, "1.25×"], [1.5, "1.5×"], [2, "2×"]].map(([v, l]) => [String(v), l]), String(c.speed || 1), { onchange: e => { c.speed = +e.target.value; redraw(); save(); } })),
          btn("Обрезать по текущему моменту", () => { const [cc, off] = clipAt(t); if (cc !== c) return toast("Поставьте курсор внутри этого клипа", true); c.end = +((+c.start || 0) + off * (c.speed || 1)).toFixed(2); redraw(); save(); }, "sm", "cut"));
        body.append(h("div.row", {}, btn("", () => move(-1), "sm icon", "up", { title: "Раньше" }), btn("", () => move(1), "sm icon", "down", { title: "Позже" }), btn("Дублировать", () => { spec.clips.splice(sel.i + 1, 0, { ...c }); redraw(); save(); }, "sm", "copy"), btn("", del, "sm icon danger", "trash", { title: "Удалить" })));
      } else if (sel.type === "audio") {
        const x = spec.audio[sel.i]; if (!x) { sel = null; return drawInsp(); }
        body.append(h("b", {}, x.name), num(x, "at", "Начинать на секунде", 0.1, 0, 3600), h("div.grid2", {}, num(x, "start", "Обрезать начало", 0.1, 0, x.src_duration), num(x, "end", "Обрезать конец", 0.1, 0, x.src_duration)),
          field("Громкость", h("input", { type: "range", min: 0, max: 2, step: 0.05, value: x.volume ?? 1, oninput: e => { x.volume = +e.target.value; save(); } })),
          btn("Субтитры из этой дорожки", () => autoSubs(x), "sm", "text"), btn("Удалить", del, "sm danger", "trash"));
      } else {
        const arr = sel.type === "sub" ? spec.subtitles : spec.texts, x = arr[sel.i]; if (!x) { sel = null; return drawInsp(); }
        body.append(field("Текст", h("textarea.in", { rows: 3, value: x.text, oninput: e => { x.text = e.target.value; showAt(t); save(); }, onchange: () => drawTL() })),
          h("div.grid2", {}, num(x, "start", "С", 0.1, 0, 3600), num(x, "end", "До", 0.1, 0, 3600)),
          sel.type === "text" ? field("Положение", select([["top", "Сверху"], ["center", "По центру"], ["bottom", "Снизу"]], x.position || "top", { onchange: e => { x.position = e.target.value; save(); showAt(t); } })) : null,
          btn("Удалить", del, "sm danger", "trash"));
      }
    } else if (inspTab === "subs") {
      body.append(h("div.row", {}, btn("Строка", () => { spec.subtitles.push({ start: +t.toFixed(2), end: +(t + 2).toFixed(2), text: "Текст" }); redraw(); save(); }, "sm", "plus"),
        btn("Текст на экране", () => { spec.texts.push({ start: +t.toFixed(2), end: +(t + 3).toFixed(2), text: "ЗАГОЛОВОК", position: "top" }); sel = { type: "text", i: spec.texts.length - 1 }; inspTab = "item"; redraw(); save(); }, "sm", "text")),
        h("p.dim", { style: { fontSize: "12px" } }, "Автосубтитры: выберите аудиодорожку или видеоклип и нажмите «Субтитры из этой дорожки», либо:"),
        btn("Распознать речь из клипов", () => { const v = spec.clips.find(c => c.kind === "video"); if (!v) return toast("На таймлайне нет видео", true); autoSubs(v); }, "sm", "mic"),
        field("Размер", select([["s", "Маленький"], ["m", "Средний"], ["l", "Крупный"], ["xl", "Очень крупный"]], spec.sub_size, { onchange: e => { spec.sub_size = e.target.value; layoutFrame(); save(); } })),
        field("Положение", select([["bottom", "Снизу"], ["center", "По центру"], ["top", "Сверху"]], spec.sub_position, { onchange: e => { spec.sub_position = e.target.value; layoutFrame(); save(); } })),
        field("Оформление", select([["caption", "Белый с обводкой"], ["box", "На тёмной плашке"]], spec.sub_style, { onchange: e => { spec.sub_style = e.target.value; layoutFrame(); save(); } })),
        h("div.sublist", {}, ...spec.subtitles.map((s, i) => h("div.s", {},
          h("input.in", { type: "number", step: 0.1, value: s.start, "aria-label": "Начало", onchange: e => { s.start = +e.target.value; drawTL(); save(); } }),
          h("input.in", { type: "number", step: 0.1, value: s.end, "aria-label": "Конец", onchange: e => { s.end = +e.target.value; drawTL(); save(); } }),
          h("input.in", { value: s.text, "aria-label": "Текст", oninput: e => { s.text = e.target.value; showAt(t); save(); }, onchange: () => drawTL() }),
          btn("", () => { spec.subtitles.splice(i, 1); redraw(); save(); }, "sm icon ghost", "x", { "aria-label": "Удалить" })))));
    } else {
      body.append(field("Громкость звука из клипов", h("input", { type: "range", min: 0, max: 1.5, step: 0.05, value: spec.clip_volume, oninput: e => { spec.clip_volume = +e.target.value; save(); } })),
        h("label.row", {}, h("input", { type: "checkbox", checked: spec.fade, onchange: e => { spec.fade = e.target.checked; save(); } }), "Плавное появление и затухание"),
        h("dl.kv", {}, h("dt", {}, "Длительность"), h("dd", {}, mmss(total())), h("dt", {}, "Клипов"), h("dd", {}, spec.clips.length), h("dt", {}, "Аудио"), h("dd", {}, spec.audio.length), h("dt", {}, "Субтитров"), h("dd", {}, spec.subtitles.length)));
    }
    insp.replaceChildren(tabs, body);
  }
  let inspTab = "item";
  function move(d) { const i = sel.i, j = i + d; if (j < 0 || j >= spec.clips.length) return; [spec.clips[i], spec.clips[j]] = [spec.clips[j], spec.clips[i]]; sel.i = j; redraw(); save(); }
  function del() {
    const arr = { clip: spec.clips, audio: spec.audio, sub: spec.subtitles, text: spec.texts }[sel.type]; arr.splice(sel.i, 1); sel = null; redraw(); save();
  }
  async function autoSubs(x) {
    const box = h("div"); insp.prepend(box);
    try {
      const r = await runTool("/api/tools/editor/subtitles", { asset_id: x.asset }, box, "Субтитры");
      let offset = 0;
      if (spec.audio.includes(x)) offset = (+x.at || 0) - (+x.start || 0);
      else { let acc = 0; for (const c of spec.clips) { if (c === x) { offset = acc - (+c.start || 0); break; } acc += clipLen(c); } }
      spec.subtitles = r.segments.map(s => ({ start: +(s.start + offset).toFixed(2), end: +(s.end + offset).toFixed(2), text: s.text })).filter(s => s.end > 0);
      box.remove(); inspTab = "subs"; redraw(); save(); toast(`Субтитры готовы (${r.provider}${r.approx ? ", тайминги приблизительные" : ""})`);
    } catch (e) { box.replaceChildren(h("div.err", {}, e.message)); }
  }

  // ---------- сохранение и экспорт ----------
  const clean = () => ({
    format: spec.format, clip_volume: spec.clip_volume, fade: spec.fade, sub_size: spec.sub_size, sub_position: spec.sub_position, sub_style: spec.sub_style,
    clips: spec.clips.map(c => c.kind === "image" ? { asset: c.asset, duration: +c.duration || 3, motion: c.motion || "zoom_in" } : { asset: c.asset, start: +c.start || 0, end: c.end != null ? +c.end : null, volume: +(c.volume ?? 1), speed: +c.speed || 1 }),
    audio: spec.audio.map(x => ({ asset: x.asset, at: +x.at || 0, start: +x.start || 0, end: x.end != null ? +x.end : null, volume: +(x.volume ?? 1) })),
    subtitles: spec.subtitles.filter(s => s.end > s.start), texts: spec.texts.filter(s => s.end > s.start),
  });
  let saveT = null;
  function save() {
    clearTimeout(saveT);
    saveT = setTimeout(() => {
      const data = clean();
      try { localStorage.setItem("mai_editor_" + (state.project?.id || 0), JSON.stringify(data)); } catch { }
      if (state.project) api("/api/projects/" + state.project.id, { method: "PATCH", body: { data: { editor: data } } }).catch(() => { });
    }, 600);
  }
  async function doExport() {
    if (!spec.clips.length) return toast("Добавьте хотя бы один клип", true);
    pause();
    try {
      const r = await runTool("/api/tools/editor/render", { spec: clean(), name: (state.project?.title || "Монтаж"), hd: exportHd.value === "1" }, out, "Экспорт");
      out.replaceChildren(h("div.split", { style: { marginTop: "12px" } }, h("div.viewer", {}, h("video", { src: r.video.url, controls: true, playsInline: true })),
        h("div.col", {}, h("dl.kv", {}, h("dt", {}, "Длительность"), h("dd", {}, r.info.duration + " с"), h("dt", {}, "Размер"), h("dd", {}, `${r.info.width}×${r.info.height}`), h("dt", {}, "Формат"), h("dd", {}, r.info.format)),
          btn("Скачать MP4", () => download(r.video.url, r.video.name), "pri", "download"))));
    } catch (e) { out.replaceChildren(h("div.err", {}, e.message)); }
  }
  function redraw() { drawTL(); drawInsp(); showAt(Math.min(t, total())); }

  // ---------- начальное состояние ----------
  const fromHand = handoff.take("editor"), addH = handoff.take("editor_add");
  let initial = fromHand;
  if (!initial && state.project) { try { initial = (await api("/api/projects/" + state.project.id)).data?.editor; } catch { } }
  if (!initial) { try { initial = JSON.parse(localStorage.getItem("mai_editor_" + (state.project?.id || 0)) || "null"); } catch { } }
  await loadBin();
  if (initial) await hydrate(JSON.parse(JSON.stringify(initial)));
  if (addH) { for (const id of [addH.video, addH.audio].filter(Boolean)) { let a = assetsById.get(id); if (!a) { const l = await api("/api/assets?limit=500"); l.forEach(x => assetsById.set(x.id, x)); a = assetsById.get(id); } if (a) await add(a); } }
  fmt.querySelectorAll("button").forEach(b => b.classList.toggle("on", b.textContent === spec.format)); fmt.value = spec.format;
  const ro = new ResizeObserver(() => layoutFrame()); ro.observe(stage);
  redraw(); layoutFrame();
  const onProj = () => window.dispatchEvent(new HashChangeEvent("hashchange"));
  window.addEventListener("mai:project", onProj);
  return () => { pause(); ro.disconnect(); window.removeEventListener("mai:project", onProj); save(); };
}
