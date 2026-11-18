import { state, api, h, icon, btn, fail, toast, runTool, handoff, go, field, select, copy, dropZone, uploadFiles, pickAsset, mmss, providerBadge, loadProviders, fmtDate } from "./lib.js";

// Источник видео: ссылка или файл (общий для анализа и воссоздания)
export function sourcePicker(onChange) {
  let cur = null;
  const url = h("input.in", { type: "url", placeholder: "https://www.tiktok.com/@…/video/…", inputMode: "url", autocapitalize: "none" });
  const info = h("div");
  const draw = () => info.replaceChildren(cur?.asset ? h("div.src-thumb", {}, h("div.th", { style: { backgroundImage: `url("${cur.asset.url}?thumb=1")` } }), h("div", { style: { flex: 1, minWidth: 0 } }, h("b", {}, "Видео загружено"), h("div.dim", { style: { overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, cur.asset.name)),
    btn("", () => { cur = null; draw(); onChange(null); }, "sm icon ghost", "x")) : "");
  url.oninput = () => { cur = url.value.trim() ? { url: url.value.trim() } : null; onChange(cur); };
  const zone = dropZone("Загрузить видео (MP4, MOV, WebM)", "video/*", async fs => { const [a] = await uploadFiles(fs); if (a) { cur = { asset: a }; url.value = ""; draw(); onChange(cur); } });
  return h("div.col", {}, field("Публичная ссылка", url), h("div.mono-up", { style: { textAlign: "center" } }, "или"), zone,
    btn("Выбрать из библиотеки", async () => { const a = await pickAsset(["video"], "Видео"); if (a) { cur = { asset: a }; url.value = ""; draw(); onChange(cur); } }, "sm ghost", "folder"), info);
}

export async function render(page) {
  await loadProviders().catch(() => { });
  let src = null;
  const picker = sourcePicker(v => src = v);
  const lang = select([["ru", "Русский"], ["uk", "Українська"], ["en", "English"]], state.user.prefs?.language === "uk" ? "uk" : "ru");
  const focus = h("input.in", { placeholder: "Например: почему так хорошо досматривают?" });
  const out = h("div");
  const run = btn("Анализировать", async () => {
    if (!src) return toast("Вставьте ссылку или загрузите видео", true);
    run.disabled = true;
    try {
      const r = await runTool("/api/tools/analyze", { asset_id: src.asset?.id || null, url: src.url || null, language: lang.value, focus: focus.value }, out, "Анализ видео");
      show(r);
    } catch (e) { out.replaceChildren(h("div.err", {}, e.message)); }
    run.disabled = false;
  }, "pri wide", "scan");

  function spark(vals) {
    if (!vals?.length) return null;
    const W = 600, H = 46, mn = Math.min(...vals), mx = Math.max(...vals), sp = mx - mn || 1;
    const pts = vals.map((v, i) => `${(i / (vals.length - 1 || 1)) * W},${H - ((v - mn) / sp) * (H - 4) - 2}`).join(" ");
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.setAttribute("class", "spark"); svg.setAttribute("preserveAspectRatio", "none");
    svg.innerHTML = `<polyline points="${pts}" fill="none" stroke="#fff" stroke-width="1.5" vector-effect="non-scaling-stroke"/>`;
    return svg;
  }

  function show(r) {
    const rep = r.report || {}, m = r.measured || {};
    const list = (arr, neg) => h("ul.dash-list" + (neg ? ".neg" : ""), {}, ...(arr || []).map(x => h("li", {}, x)));
    const sec = (t, v) => v ? h("div.sec", {}, h("h4", {}, t), typeof v === "string" ? h("p", {}, v) : v) : null;
    const ns = rep.new_script || {};
    const modeTxt = { video: "ИИ просмотрел видео целиком", frames: "ИИ изучил 8 кадров ролика", text: "ИИ не видел картинку — только звук и измерения" }[r.mode] || "";
    out.replaceChildren(h("div.col", {},
      h("div.panel", {}, h("div.row", { style: { alignItems: "flex-start", gap: "24px" } },
        r.thumbnail ? h("img", { src: r.thumbnail.url, style: { width: "120px", aspectRatio: "9/16", objectFit: "cover", border: "1px solid var(--line)" }, alt: "" }) : null,
        h("div", { style: { flex: 1, minWidth: "220px" } }, h("div.mono-up", {}, "1 · Общая оценка"), h("div.score", {}, h("b", {}, rep.overall?.score ?? "—"), h("span.dim", {}, "/ 10")),
          h("p", { style: { marginTop: "6px" } }, rep.overall?.verdict || ""), h("p.dim", { style: { fontSize: "12px", marginTop: "8px" } }, modeTxt + ". Оценка — мнение ИИ, а не статистика TikTok.")))),
      h("div.panel", {}, h("h3", {}, "Измерено программой"),
        h("div.measured", {}, ...[["Длительность", mmss(m.duration)], ["Формат", `${m.width}×${m.height}${m.vertical ? " · верт." : ""}`], ["Склеек", m.cut_count], ["Склеек / 10 с", m.cuts_per_10s],
          ["Средний план", (m.avg_shot ?? "—") + " с"], ["Первая склейка", m.first_cut != null ? m.first_cut + " с" : "нет"], ["Склеек за 3 с", m.cuts_first_3s], ["Темп речи", m.words_per_min ? m.words_per_min + " сл/мин" : "—"]].map(([k, v]) => h("div", {}, h("span.mono-up", {}, k), h("b", {}, v ?? "—")))),
        m.duration ? h("div", { style: { marginTop: "12px" } }, h("div.mono-up", {}, "Склейки на шкале времени"), h("div.cutline", {}, ...(m.cuts || []).map(c => h("i", { style: { left: (c / m.duration * 100) + "%" } })))) : null,
        m.loudness?.length ? h("div", { style: { marginTop: "12px" } }, h("div.mono-up", {}, "Громкость по времени"), spark(m.loudness)) : null,
        r.public_stats && Object.keys(r.public_stats).length ? h("div", { style: { marginTop: "12px" } }, h("div.mono-up", {}, "Публичные данные со страницы ролика"),
          h("dl.kv", { style: { marginTop: "6px" } }, ...[["Автор", r.public_stats.uploader], ["Просмотры", r.public_stats.view_count?.toLocaleString("ru-RU")], ["Лайки", r.public_stats.like_count?.toLocaleString("ru-RU")], ["Комментарии", r.public_stats.comment_count?.toLocaleString("ru-RU")]]
            .filter(x => x[1] != null).flatMap(([k, v]) => [h("dt", {}, k), h("dd", {}, v)]))) : null),
      h("div.panel", {},
        sec("Первые секунды", rep.first_seconds), sec("Хук", rep.hook), sec("Сценарий", rep.script), sec("Монтаж", rep.editing), sec("Визуальный стиль", rep.visual_style),
        sec("Субтитры и текст", rep.subtitles), sec("Озвучка и звук", rep.voiceover), sec("Темп", rep.pace), sec("Удержание внимания (качественно)", rep.retention)),
      h("div.grid2", {}, h("div.panel", {}, h("h3", {}, "2 · Что сделано хорошо"), list(rep.strengths)), h("div.panel", {}, h("h3", {}, "3 · Что можно улучшить"), list(rep.weaknesses, true))),
      h("div.panel", {}, sec("4 · Почему видео может заинтересовать", rep.why_interesting), sec("5 · Как сделать похожее оригинальное видео", list(rep.how_to_make_similar))),
      h("div.panel", {}, h("h3", {}, "6 · Новый сценарий на основе анализа"), ns.title ? h("p", {}, h("b", {}, ns.title)) : null, ns.hook ? h("div.big-hook", { style: { margin: "8px 0" } }, ns.hook) : null,
        ns.scenes?.length ? h("div.scenes", {}, ...ns.scenes.map(s => h("div.sc", {}, h("span.t", {}, s.time), h("div", {}, s.visual), h("div.muted", {}, s.on_screen_text || "")))) : null,
        ns.voiceover ? h("div.copy-block", { style: { marginTop: "10px" } }, ns.voiceover, btn("", () => copy(ns.voiceover), "sm icon ghost", "copy")) : null,
        h("div.row", { style: { marginTop: "12px" } }, btn("Доработать сценарий", () => { handoff.set("script_topic", { topic: ns.title || "Ролик по мотивам анализа", extra: "Опирайся на хук: " + (ns.hook || "") }); go("#/script"); }, "", "script"),
          ns.voiceover ? btn("Озвучить", () => { handoff.set("voice", { text: ns.voiceover }); go("#/voice"); }, "", "mic") : null)),
      rep.generation_prompt ? h("div.panel", {}, h("h3", {}, "7 · Готовый промпт для нового ролика"), h("div.copy-block", {}, rep.generation_prompt, btn("", () => copy(rep.generation_prompt), "sm icon ghost", "copy")),
        h("div.row", { style: { marginTop: "12px" } }, btn("Создать видео", () => { handoff.set("video", { prompt: rep.generation_prompt }); go("#/video"); }, "pri", "film"), btn("Воссоздать стиль", () => go("#/recreate"), "", "layers"))) : null,
      r.transcript?.text ? h("div.panel", {}, h("h3", {}, "Расшифровка речи"), h("p.dim", { style: { fontSize: "12px", marginBottom: "8px" } }, r.transcript.provider), h("div.copy-block", {}, r.transcript.text)) : null));
  }

  async function history() {
    try {
      const js = (await api("/api/jobs?tool=analyze&status=done&limit=10"));
      return js.length ? h("div.panel", {}, h("h3", {}, "Прошлые анализы"), h("div.list", {}, ...js.map(j => h("div.it", { onclick: () => show(j.result) }, h("div.th", { style: { backgroundImage: j.result?.thumbnail ? `url("${j.result.thumbnail.url}")` : "" } }),
        h("div.t", {}, j.result?.video_name || j.title), h("span.dim", {}, (j.result?.report?.overall?.score ?? "—") + "/10 · " + fmtDate(j.created)))))) : null;
    } catch { return null; }
  }
  page.append(
    h("div.ph", {}, h("div", {}, h("h1", {}, "Анализ TikTok"), h("p", {}, "Разбор ролика: хук, сценарий, монтаж, визуал, субтитры, звук и темп. Цифры — только реальные измерения файла; просмотры и удержание не выдумываются.")), h("div.sp"),
      h("div.row", {}, providerBadge("video_understanding"), providerBadge("stt"))),
    h("div.split", {}, h("div.panel.col.sticky", {}, picker, field("Язык отчёта", lang), field("На что обратить внимание", focus), run,
      h("p.dim", { style: { fontSize: "12px" } }, "Ссылки работают только для публичных роликов. Анализируйте видео, которые вам разрешено использовать.")), h("div.col", {}, out)));
  out.append(h("div.empty", {}, "Здесь появится отчёт"));
  const hi = await history(); if (hi) out.after(hi);
}
