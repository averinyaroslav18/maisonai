// MaisonAI · «Гироскоп» — хромовая монограмма M в двух кольцах с красной точкой REC.
// Один WebGL-холст на всё приложение: объект перелетает между «якорями» [data-orb] на странице.
import * as THREE from "../vendor/three.module.min.js";
import { RoomEnvironment } from "../vendor/RoomEnvironment.js";

const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
let renderer, scene, camera, root, mono, ring1, ring2, bead, glow, dust, dustMat, halo;
let W = 0, H = 0, visH = 1, last = performance.now(), busyK = 0, busyT = 0, pulseT = 0, introT = 0, ok = false;
const pointer = { x: 0, y: 0, tx: 0, ty: 0 };
const spr = { x: 0, y: 0, s: 0.0001, vx: 0, vy: 0, vs: 0 };   // пружина положения и размера
let target = { x: 0, y: 0, s: 1 }, busy = false, spinV = 0, spin = 0;

function monogramShape() {
  // стилизованная M со скосами
  const s = new THREE.Shape(), P = [[-1, -1], [-0.6, -1], [-0.6, 0.32], [-0.08, -0.38], [0.08, -0.38], [0.6, 0.32], [0.6, -1], [1, -1], [1, 1], [0.64, 1], [0, 0.12], [-0.64, 1], [-1, 1]];
  s.moveTo(...P[0]); for (const p of P.slice(1)) s.lineTo(...p); s.closePath(); return s;
}

export function init() {
  try {
    const cv = document.createElement("canvas"); cv.id = "orb";
    renderer = new THREE.WebGLRenderer({ canvas: cv, alpha: true, antialias: true, powerPreference: "high-performance" });
  } catch { return false; }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75));
  renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.3;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  document.body.prepend(renderer.domElement);
  scene = new THREE.Scene();
  const pm = new THREE.PMREMGenerator(renderer);
  scene.environment = pm.fromScene(new RoomEnvironment(), 0.035).texture;
  camera = new THREE.PerspectiveCamera(35, 1, 0.1, 100); camera.position.set(0, 0, 10);
  root = new THREE.Group(); scene.add(root);

  const chrome = new THREE.MeshPhysicalMaterial({ color: 0xffffff, metalness: 1, roughness: 0.1, clearcoat: 1, clearcoatRoughness: 0.06, envMapIntensity: 1.35 });
  const dark = new THREE.MeshPhysicalMaterial({ color: 0x2b2c33, metalness: 0.9, roughness: 0.28, envMapIntensity: 1.1 });
  const g = new THREE.ExtrudeGeometry(monogramShape(), { depth: 0.34, bevelEnabled: true, bevelThickness: 0.08, bevelSize: 0.065, bevelSegments: 5, curveSegments: 4 });
  g.center(); mono = new THREE.Mesh(g, chrome); mono.scale.setScalar(0.92); root.add(mono);
  ring1 = new THREE.Mesh(new THREE.TorusGeometry(1.72, 0.04, 28, 240), chrome); root.add(ring1);
  ring2 = new THREE.Group();
  const r2 = new THREE.Mesh(new THREE.TorusGeometry(2.06, 0.02, 20, 260), dark); ring2.add(r2);
  bead = new THREE.Mesh(new THREE.SphereGeometry(0.075, 24, 24), new THREE.MeshBasicMaterial({ color: 0xff3b30 }));
  bead.position.set(2.06, 0, 0); ring2.add(bead);
  glow = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTex(), color: 0xff3b30, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false, opacity: 0.85 }));
  glow.scale.setScalar(0.75); glow.position.copy(bead.position); ring2.add(glow);
  root.add(ring2);
  halo = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTex(), color: 0xc9cdd5, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false, opacity: 0.16 }));
  halo.scale.setScalar(6.5); halo.position.z = -1.2; root.add(halo);
  // облако частиц
  const N = 900, pos = new Float32Array(N * 3), seed = new Float32Array(N);
  for (let i = 0; i < N; i++) {
    const u = Math.random() * 2 - 1, t = Math.random() * Math.PI * 2, r = 2.5 + Math.random() * 1.4, q = Math.sqrt(1 - u * u);
    pos.set([r * q * Math.cos(t), r * u * 0.75, r * q * Math.sin(t)], i * 3); seed[i] = Math.random();
  }
  const dg = new THREE.BufferGeometry(); dg.setAttribute("position", new THREE.BufferAttribute(pos, 3)); dg.setAttribute("seed", new THREE.BufferAttribute(seed, 1));
  dustMat = new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    uniforms: { uT: { value: 0 }, uSpread: { value: 1 }, uAlpha: { value: 1 }, uPx: { value: renderer.getPixelRatio() } },
    vertexShader: `attribute float seed; uniform float uT; uniform float uSpread; uniform float uPx; varying float vA;
      void main(){ vec3 p = position * uSpread; float a = uT * (0.15 + seed * 0.25);
        p.xz = mat2(cos(a), -sin(a), sin(a), cos(a)) * p.xz; p.y += sin(uT * 1.3 + seed * 30.0) * 0.08;
        vec4 mv = modelViewMatrix * vec4(p, 1.0); gl_Position = projectionMatrix * mv;
        vA = 0.35 + 0.65 * fract(seed * 7.0 + uT * 0.25); gl_PointSize = (1.2 + seed * 2.4) * uPx * (8.0 / -mv.z); }`,
    fragmentShader: `uniform float uAlpha; varying float vA; void main(){ float d = length(gl_PointCoord - 0.5); if (d > 0.5) discard;
        gl_FragColor = vec4(vec3(0.92, 0.93, 0.96), (1.0 - d * 2.0) * vA * uAlpha * 0.8); }`
  });
  dust = new THREE.Points(dg, dustMat); root.add(dust);

  addEventListener("resize", resize); resize();
  addEventListener("pointermove", e => { pointer.tx = e.clientX / W * 2 - 1; pointer.ty = e.clientY / H * 2 - 1; }, { passive: true });
  document.addEventListener("visibilitychange", () => { if (!document.hidden) { last = performance.now(); requestAnimationFrame(frame); } });
  ok = true; document.body.classList.add("orb-on");
  requestAnimationFrame(frame);
  return true;
}

function glowTex() {
  const c = document.createElement("canvas"); c.width = c.height = 128; const x = c.getContext("2d");
  const gr = x.createRadialGradient(64, 64, 0, 64, 64, 64); gr.addColorStop(0, "rgba(255,255,255,1)"); gr.addColorStop(0.25, "rgba(255,255,255,.45)"); gr.addColorStop(1, "rgba(255,255,255,0)");
  x.fillStyle = gr; x.fillRect(0, 0, 128, 128); const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
}

function resize() {
  W = innerWidth; H = innerHeight; renderer.setSize(W, H, false);
  camera.aspect = W / H; camera.updateProjectionMatrix();
  visH = 2 * camera.position.z * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2));
}

// Выбор якоря: крупный (hero/intro/auth), если он виден, иначе логотип
function pickAnchor() {
  const list = [...document.querySelectorAll("[data-orb]")];
  let best = null, bestPri = -1;
  for (const el of list) {
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) continue;
    const pri = { intro: 4, auth: 3, hero: 2, logo: 1 }[el.dataset.orb] || 0;
    const visible = r.bottom > 40 && r.top < H - 40;
    if (pri >= 2 && !visible) continue;
    if (pri > bestPri) { best = r; bestPri = pri; }
  }
  return best;
}

function frame(now) {
  if (!ok || document.hidden) return;
  const dt = Math.min(0.05, (now - last) / 1000); last = now;
  const t = now / 1000;
  const r = pickAnchor();
  if (r) {
    const cx = r.left + r.width / 2, cy = r.top + r.height / 2, size = Math.min(r.width, r.height);
    target.x = (cx / W - 0.5) * visH * camera.aspect; target.y = -(cy / H - 0.5) * visH;
    target.s = (size / H) * visH / 4.3;
  } else target.s = 0.0001;
  // пружина (с лёгким «перелётом» — объект эффектно перелетает между местами)
  const k = reduce ? 400 : 70, d = reduce ? 40 : 12.5;
  for (const [p, v, tg] of [["x", "vx", target.x], ["y", "vy", target.y], ["s", "vs", target.s]]) {
    spr[v] += (tg - spr[p]) * k * dt; spr[v] *= Math.exp(-d * dt); spr[p] += spr[v] * dt;
  }
  pointer.x += (pointer.tx - pointer.x) * Math.min(1, dt * 4); pointer.y += (pointer.ty - pointer.y) * Math.min(1, dt * 4);
  busyK += ((busy ? 1 : 0) - busyK) * Math.min(1, dt * 3);
  if (busy) busyT += dt;
  pulseT = Math.max(0, pulseT - dt);
  introT = Math.min(1, introT + dt / 1.6);
  const big = Math.min(1, Math.max(0, (spr.s - 0.12) / 0.4));   // крупный режим: частицы и ореол видны
  const pulse = Math.sin((1 - pulseT / 0.9) * Math.PI) * (pulseT > 0 ? 1 : 0);
  root.position.set(spr.x, spr.y, 0);
  root.scale.setScalar(Math.max(0.0001, spr.s * (1 + pulse * 0.12)));
  const m = reduce ? 0 : 1;
  spinV += ((0.35 + busyK * 3.2) - spinV) * Math.min(1, dt * 2); spin += spinV * dt * m;
  mono.rotation.y = Math.sin(t * 0.6) * 0.42 * m + pointer.x * 0.45 + spin * 0.25 * busyK;
  mono.rotation.x = pointer.y * 0.3 + Math.sin(t * 0.8) * 0.06 * m;
  mono.position.y = Math.sin(t * 1.2) * 0.06 * m;
  ring1.rotation.set(1.15 + pointer.y * 0.2, spin * 0.9, 0.35 + Math.sin(t * 0.4) * 0.15 * m);
  ring2.rotation.set(-0.5 + pointer.y * 0.15, -spin * 0.6, -0.6 + pointer.x * 0.2);
  ring2.children[0].rotation.z = 0;
  const bAng = t * (0.9 + busyK * 4) * m; bead.position.set(Math.cos(bAng) * 2.06, Math.sin(bAng) * 2.06, 0); glow.position.copy(bead.position);
  glow.material.opacity = 0.55 + 0.35 * Math.sin(t * (busy ? 9 : 2.4)) ** 2 + pulse * 0.4;
  glow.scale.setScalar(0.6 + busyK * 0.5 + pulse * 0.6);
  const intro = 1 - Math.pow(1 - introT, 3);
  dustMat.uniforms.uT.value = t * (1 + busyK * 3) * (reduce ? 0 : 1);
  dustMat.uniforms.uSpread.value = (2.4 - intro * 1.4) * (1 + busyK * 0.18 + pulse * 0.35);
  dustMat.uniforms.uAlpha.value = big * (0.6 + busyK * 0.4);
  halo.material.opacity = big * (0.1 + busyK * 0.12 + pulse * 0.2);
  renderer.render(scene, camera);
  requestAnimationFrame(frame);
}

export const setBusy = v => { busy = !!v; };
export const pulse = () => { pulseT = 0.9; };
export const ready = () => ok;
