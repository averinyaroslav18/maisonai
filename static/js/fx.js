// Эффекты интерфейса: свет за курсором, наклон плиток, «волна» от нажатия, магнитные кнопки, счётчики, каскадное появление.
const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
const fine = matchMedia("(hover: hover) and (pointer: fine)").matches;
const GLOW = ".panel,.prov,.tile,.card,.prompt-box,.action,.plan-scene,.jobcard,.counters";

export function init() {
  const spot = document.createElement("div"); spot.id = "spot"; document.body.prepend(spot);
  let sx = innerWidth / 2, sy = innerHeight / 3, tx = sx, ty = sy;
  if (fine && !reduce) {
    addEventListener("pointermove", e => {
      tx = e.clientX; ty = e.clientY;
      const card = e.target.closest?.(GLOW);
      if (card) {
        card.classList.add("glow-card");
        const r = card.getBoundingClientRect();
        card.style.setProperty("--mx", (e.clientX - r.left) + "px"); card.style.setProperty("--my", (e.clientY - r.top) + "px");
        if (card.classList.contains("tile")) {
          const px = (e.clientX - r.left) / r.width - 0.5, py = (e.clientY - r.top) / r.height - 0.5;
          card.style.transform = `rotateX(${(-py * 9).toFixed(2)}deg) rotateY(${(px * 11).toFixed(2)}deg) translateZ(6px)`;
        }
      }
      const mag = e.target.closest?.(".btn.pri");
      if (mag) { const r = mag.getBoundingClientRect(); mag.style.translate = `${((e.clientX - r.left) / r.width - 0.5) * 6}px ${((e.clientY - r.top) / r.height - 0.5) * 5}px`; }
    }, { passive: true });
    document.addEventListener("pointerout", e => {
      const t = e.target.closest?.(".tile"); if (t && !t.contains(e.relatedTarget)) t.style.transform = "";
      const m = e.target.closest?.(".btn.pri"); if (m && !m.contains(e.relatedTarget)) m.style.translate = "";
    });
    const loop = () => { sx += (tx - sx) * 0.12; sy += (ty - sy) * 0.12; spot.style.transform = `translate3d(${sx}px,${sy}px,0)`; requestAnimationFrame(loop); };
    loop();
  } else spot.remove();
  // «волна» от нажатия на кнопки
  document.addEventListener("pointerdown", e => {
    const b = e.target.closest?.(".btn"); if (!b || reduce) return;
    const r = b.getBoundingClientRect(), d = Math.max(r.width, r.height);
    const s = document.createElement("span"); s.className = "ripple";
    Object.assign(s.style, { width: d + "px", height: d + "px", left: (e.clientX - r.left - d / 2) + "px", top: (e.clientY - r.top - d / 2) + "px" });
    b.append(s); setTimeout(() => s.remove(), 650);
  });
  // появление при прокрутке: только для элементов ниже экрана (видимое не прячем)
  const io = "IntersectionObserver" in window && !reduce ? new IntersectionObserver(es => { for (const e of es) if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); } }, { threshold: 0.06 }) : null;
  const SR = ".panel,.prov,.plan-scene,.charcard,.trendcard,.stylecard,.memstat,.sec";
  const watch = root => { if (!io) return; for (const el of root.querySelectorAll ? root.querySelectorAll(SR) : []) { if (el.classList.contains("sr") || el.closest(".modal,.drawer")) continue; const r = el.getBoundingClientRect(); if (r.top > innerHeight + 10) { el.classList.add("sr"); io.observe(el); } } };
  // каскадное появление новых карточек
  new MutationObserver(ms => {
    for (const m of ms) for (const n of m.addedNodes) {
      if (n.nodeType !== 1) continue;
      requestAnimationFrame(() => watch(n));
      if (n.classList.contains("gallery") || n.classList.contains("list") || n.classList.contains("tiles")) stagger(n);
      else if (n.parentElement?.matches(".gallery,.list")) stagger(n.parentElement);
    }
  }).observe(document.body, { childList: true, subtree: true });
}

function stagger(box) {
  if (reduce) return;
  [...box.children].forEach((c, i) => { if (!c.classList.contains("reveal")) { c.style.setProperty("--i", Math.min(i, 14)); c.classList.add("reveal"); } });
}

// Плавный счёт чисел
export function countUp(el, to) {
  to = +to || 0;
  if (reduce || to === 0) { el.textContent = to; return; }
  const t0 = performance.now(), dur = 900 + Math.min(600, to * 20);
  const step = now => { const k = Math.min(1, (now - t0) / dur), e = 1 - Math.pow(1 - k, 4); el.textContent = Math.round(to * e); if (k < 1) requestAnimationFrame(step); };
  requestAnimationFrame(step);
}
