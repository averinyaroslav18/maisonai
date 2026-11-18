import { state, api, h, icon, btn, fail, toast, runTool, handoff, go, confirmBox, assetCard, previewModal, LANGS } from "./lib.js";

const TOOL_NAMES = { script: "Сценарий", image: "Изображение", video: "Видео", voice: "Озвучка", analyze: "Анализ видео", recreate: "Воссоздание стиля", montage: "Монтаж проекта" };

export async function render(page) {
  const log = h("div.log", { "aria-live": "polite" });
  const ta = h("textarea", { placeholder: "Опишите задачу обычным языком…", rows: 1, "aria-label": "Сообщение ассистенту" });
  const sendBtn = btn("", () => send(), "pri icon", "arrow", { "aria-label": "Отправить" });
  const projLine = h("span.dim");
  const chat = h("div.chat", {},
    h("div.row", { style: { marginBottom: "12px" } }, h("h1", { style: { fontSize: "20px", fontWeight: 600, flex: 1 } }, "Ассистент"), projLine,
      btn("Очистить", clear, "sm ghost", "trash")),
    log, h("div.compose", {}, ta, sendBtn));
  page.append(chat);
  ta.oninput = () => { ta.style.height = "auto"; ta.style.height = Math.min(180, ta.scrollHeight) + "px"; };
  ta.onkeydown = e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } };
  const pid = () => state.project?.id || 0;

  async function load() {
    projLine.textContent = state.project ? "Проект: " + state.project.title : "Без проекта — история общая";
    log.replaceChildren();
    try {
      const hs = await api("/api/assistant/history?project_id=" + pid());
      if (!hs.length) log.append(h("div.empty", {}, "Напишите, что хотите создать. Например: «Хочу вирусный ролик про путешествия» — ассистент предложит идеи, напишет сценарий, подготовит кадры и озвучку, а затем соберёт ролик."));
      for (const m of hs) addMsg(m.role, m.content, m.meta?.actions || [], m.ideas || []);
    } catch (e) { log.append(h("div.err", {}, e.message)); }
    log.scrollTop = log.scrollHeight;
  }

  function addMsg(role, text, actions = [], ideas = []) {
    log.querySelector(".empty")?.remove();
    if (role === "user") log.append(h("div.msg.me", {}, text));
    else {
      const m = h("div.msg.ai", {}, h("div.who", {}, "MaisonAI"), h("div", {}, text));
      if (ideas.length) m.append(h("ul.dash-list", { style: { marginTop: "10px" } }, ...ideas.map(i => h("li", {}, i))));
      if (actions.length) m.append(h("div.actions", {}, ...actions.map(actionCard)));
      log.append(m);
    }
    log.scrollTop = log.scrollHeight;
  }

  function describe(a) {
    const p = a.params || {};
    return p.topic || p.prompt || p.text || p.instructions || "";
  }

  function actionCard(a) {
    const out = h("div");
    const run = btn("Запустить", () => execute(a, out, run), "sm pri", "play");
    return h("div", {}, h("div.action", {}, icon({ script: "script", image: "image", video: "film", voice: "mic", analyze: "scan", recreate: "layers", montage: "cut" }[a.tool]),
      h("div.t", {}, h("b", {}, a.title || TOOL_NAMES[a.tool]), h("span", {}, (TOOL_NAMES[a.tool] + (describe(a) ? " · " + describe(a) : "")).slice(0, 160))), run), out);
  }

  async function execute(a, out, b) {
    const p = a.params || {};
    if (a.tool === "analyze") { go("#/intel/analyze"); return; }
    if (a.tool === "recreate") { go("#/intel/create"); return; }
    b.disabled = true;
    try {
      if (a.tool === "script") {
        const r = await runTool("/api/tools/script", { topic: p.topic || "", duration: +p.duration || 30, language: p.language || "uk", style: p.style || "", audience: p.audience || "", goal: p.goal || "" }, out, "Сценарий");
        const s = r.script;
        out.replaceChildren(h("div.panel", {}, h("div.big-hook", {}, s.hook), h("p.muted", { style: { margin: "8px 0" } }, s.idea),
          h("div.row", {}, btn("Открыть сценарий", () => { handoff.set("script", r); go("#/script"); }, "sm", "script"),
            btn("Озвучить", () => { handoff.set("voice", { text: s.voiceover }); go("#/voice"); }, "sm", "mic"))));
      } else if (a.tool === "image") {
        const r = await runTool("/api/tools/image", { prompt: p.prompt || "", ratio: p.ratio || "9:16" }, out, "Изображение");
        out.replaceChildren(h("div.gallery", {}, ...r.assets.map(x => assetCard(x, { onClick: () => previewModal(x) }))));
      } else if (a.tool === "video") {
        const r = await runTool("/api/tools/video", { prompt: p.prompt || "", ratio: p.ratio || "9:16", duration: Math.max(2, Math.min(60, +p.duration || 6)) }, out, "Видео");
        out.replaceChildren(h("div.gallery", {}, assetCard(r.asset, { onClick: () => previewModal(r.asset) })));
      } else if (a.tool === "voice") {
        const r = await runTool("/api/tools/voice", { text: p.text || "", voice: p.voice || "uk-UA-PolinaNeural" }, out, "Озвучка");
        out.replaceChildren(h("audio", { src: r.asset.url, controls: true, style: { width: "100%" } }));
      } else if (a.tool === "montage") {
        if (!state.project) throw new Error("Сначала выберите проект в верхней панели — монтаж собирается из его материалов.");
        const r = await runTool("/api/tools/automontage", { project_id: state.project.id, ratio: p.ratio || "9:16" }, out, "Монтаж");
        out.replaceChildren(h("div.gallery", {}, assetCard(r.video, { onClick: () => previewModal(r.video) })), btn("Открыть в редакторе", () => { handoff.set("editor", r.spec); go("#/editor"); }, "sm", "cut"));
      }
      b.textContent = "Готово"; b.disabled = true;
    } catch (e) { fail(e); b.disabled = false; }
  }

  async function send(text) {
    const v = (text ?? ta.value).trim(); if (!v) return;
    ta.value = ""; ta.style.height = "auto"; addMsg("user", v);
    const wait = h("div"); log.append(wait); log.scrollTop = log.scrollHeight; sendBtn.disabled = true;
    try {
      const r = await runTool("/api/assistant", { message: v, project_id: state.project?.id ?? null }, wait, "Ассистент");
      wait.remove(); addMsg("assistant", r.reply, r.actions, r.ideas);
    } catch (e) { wait.replaceChildren(h("div.err", {}, e.message)); }
    sendBtn.disabled = false; ta.focus();
  }

  async function clear() {
    if (!await confirmBox("Очистить переписку " + (state.project ? "в этом проекте" : "без проекта") + "?", "Очистить")) return;
    try { await api("/api/assistant/history?project_id=" + pid(), { method: "DELETE" }); load(); } catch (e) { fail(e); }
  }

  const onProj = () => load();
  window.addEventListener("mai:project", onProj);
  await load();
  const pre = handoff.take("ask");
  if (pre) send(pre); else ta.focus();
  return () => window.removeEventListener("mai:project", onProj);
}
