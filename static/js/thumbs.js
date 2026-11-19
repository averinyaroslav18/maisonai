import { api, h, btn, toast, field, segmented, runTool, pickAsset, uploadFiles, download, assetCard, previewModal } from "./lib.js";

// Thumbnail Studio — обложки для TikTok, Reels и YouTube Shorts
export async function render(page) {
  const meta = await api("/api/studio/thumbnail/styles");
  let bg = null;
  const title = h("input.in.big-in", { placeholder: "Как накачать пресс за 30 дней", maxLength: 80 });
  const sub = h("input.in", { placeholder: "Подзаголовок (необязательно)", maxLength: 80 });
  const ratio = segmented([["9:16", "TikTok / Reels"], ["16:9", "YouTube"], ["1:1", "Квадрат"], ["4:5", "Лента 4:5"]], "9:16", () => paint());
  const style = segmented(Object.entries(meta.styles).map(([k]) => [k, { bold: "Крупно", box: "Плашка", glow: "Неон", minimal: "Минимал", split: "Акцент" }[k]]), "bold", () => paint());
  const accent = h("input", { type: "color", value: "#ffffff", oninput: () => paint(), "aria-label": "Цвет акцента" });
  const prompt = h("textarea.in", { rows: 2, placeholder: "Или опишите фон — ИИ нарисует: спортсмен в зале на рассвете, кинематографичный свет" });
  const bgBox = h("div.bg-pick");
  const out = h("div"), gallery = h("div.lib-grid");
  const drawBg = () => bgBox.replaceChildren(bg ? h("div.src-thumb", {}, h("div.th", { style: { backgroundImage: `url("${bg.kind === "video" ? bg.url + "?thumb=1" : bg.url}")` } }), h("div", { style: { flex: 1 } }, h("b", {}, "Фон"), h("div.dim", {}, bg.name)), btn("", () => { bg = null; drawBg(); paint(); }, "sm icon ghost", "x"))
    : h("div.row.wrap", {}, btn("Выбрать из библиотеки", async () => { const a = await pickAsset(["image", "video"], "Фон обложки"); if (a) { bg = a; drawBg(); paint(); } }, "sm", "folder"),
      h("label.btn.sm.ghost", {}, "Загрузить", h("input", { type: "file", accept: "image/*", hidden: true, onchange: async e => { const [a] = await uploadFiles([...e.target.files]); if (a) { bg = a; drawBg(); paint(); } } }))));
  // живой предпросмотр в браузере (итоговый файл рисует сервер в полном размере)
  const cv = h("canvas.thumb-live", { "aria-label": "Предпросмотр обложки" });
  const img = new Image(); img.crossOrigin = "anonymous";
  function paint() {
    const [W, H] = meta.sizes[ratio.value]; const k = 420 / Math.max(W, H); cv.width = Math.round(W * k); cv.height = Math.round(H * k);
    const x = cv.getContext("2d"); x.fillStyle = "#111"; x.fillRect(0, 0, cv.width, cv.height);
    const src = bg ? (bg.kind === "video" ? bg.url + "?thumb=1" : bg.url) : null;
    const text = () => {
      const g = x.createLinearGradient(0, cv.height * 0.35, 0, cv.height); g.addColorStop(0, "rgba(0,0,0,0)"); g.addColorStop(1, "rgba(0,0,0,.85)"); x.fillStyle = g; x.fillRect(0, 0, cv.width, cv.height);
      const st = style.value, t = (st === "minimal" || st === "split" ? title.value : title.value.toUpperCase()) || "ЗАГОЛОВОК";
      let px = Math.min(cv.width, cv.height) * (cv.height > cv.width ? 0.13 : 0.11) * (st === "minimal" ? 0.55 : 1);
      x.font = `800 ${px}px Montserrat, Inter, sans-serif`; x.textBaseline = "top";
      const words = t.split(/\s+/), lines = []; let cur = "";
      for (const w of words) { const tt = (cur + " " + w).trim(); if (x.measureText(tt).width <= cv.width * 0.86 || !cur) cur = tt; else { lines.push(cur); cur = w; } } if (cur) lines.push(cur);
      const lh = px * 1.08, tot = lh * lines.length; let y0 = st === "minimal" ? cv.height * 0.86 - tot : cv.height * (cv.height > cv.width ? 0.62 : 0.55) - tot / 2;
      lines.forEach((ln, i) => {
        const tw = x.measureText(ln).width, xx = st === "minimal" ? cv.width * 0.07 : (cv.width - tw) / 2, y = y0 + i * lh;
        if (st === "box") { x.fillStyle = "rgba(0,0,0,.88)"; x.fillRect(xx - px * .22, y - px * .08, tw + px * .44, lh); x.fillStyle = "#fff"; x.fillText(ln, xx, y); return; }
        if (st === "glow") { x.shadowColor = accent.value; x.shadowBlur = px * .5; }
        x.lineWidth = st === "minimal" ? 0 : px * .14; x.strokeStyle = "#000"; if (x.lineWidth) x.strokeText(ln, xx, y);
        x.fillStyle = st === "split" && i === 0 ? accent.value : "#fff"; x.fillText(ln, xx, y); x.shadowBlur = 0;
      });
      if (sub.value) { x.font = `700 ${px * .36}px Inter, sans-serif`; x.fillStyle = "#eee"; const tw = x.measureText(sub.value).width; x.fillText(sub.value, style.value === "minimal" ? cv.width * .07 : (cv.width - tw) / 2, y0 + tot + px * .25); }
    };
    if (src) { img.onload = () => { const s = Math.max(cv.width / img.width, cv.height / img.height); x.drawImage(img, (cv.width - img.width * s) / 2, (cv.height - img.height * s) / 3, img.width * s, img.height * s); text(); }; img.src = src; }
    else { const g = x.createLinearGradient(0, 0, cv.width, cv.height); g.addColorStop(0, "#2a2a2e"); g.addColorStop(1, "#0b0b0c"); x.fillStyle = g; x.fillRect(0, 0, cv.width, cv.height); text(); }
  }
  title.oninput = sub.oninput = paint;
  const make = btn("Создать обложку", async () => {
    if (!title.value.trim()) return toast("Впишите заголовок", true);
    if (!bg && !prompt.value.trim()) return toast("Выберите фон или опишите его", true);
    make.disabled = true;
    try {
      const r = await runTool("/api/studio/thumbnail", { title: title.value, subtitle: sub.value, ratio: ratio.value, style: style.value, accent: accent.value, bg_asset: bg?.id || null, prompt: bg ? "" : prompt.value }, out, "Обложка");
      out.replaceChildren(h("div.col.result-in", {}, h("img.cover-prev", { src: r.asset.url, alt: "Обложка" }), h("div.row", {}, btn("Скачать", () => download(r.asset.url, r.asset.name), "pri", "download"))));
      load();
    } catch (e) { out.replaceChildren(h("div.err", {}, e.message)); }
    make.disabled = false;
  }, "pri wide lg", "sparkles");
  async function load() {
    const r = await api("/api/library?kind=image&limit=400");
    const items = r.items.filter(a => a.meta?.thumbnail);
    gallery.replaceChildren(...(items.length ? items.slice(0, 24).map(a => assetCard(a, { onClick: () => previewModal(a) })) : [h("div.empty", {}, "Здесь будут ваши обложки.")]));
  }
  page.append(h("div.ph", {}, h("h1", {}, "Thumbnail Studio"), h("p.muted", {}, "Обложки для TikTok, Reels и YouTube Shorts: ваш кадр или ИИ-фон + крупная типографика. Наложение текста — бесплатно, на этом устройстве.")),
    h("div.grid-flow", {}, h("div.panel.glass.col", {}, field("Заголовок", title), field("Подзаголовок", sub), field("Формат", ratio), field("Стиль", style),
      h("label.row", {}, accent, "Цвет акцента"), field("Фон", bgBox), field("ИИ-фон", prompt, "если фон не выбран"), make, out),
      h("div.col", { style: { alignItems: "center" } }, h("div.mono-up", {}, "Предпросмотр"), cv)),
    h("h3", { style: { marginTop: "28px" } }, "Мои обложки"), gallery);
  drawBg(); paint(); load();
}
