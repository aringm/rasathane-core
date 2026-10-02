#!/usr/bin/env node
/**
 * rasathane.ai — scroll anlatı videosu üretici
 * ---------------------------------------------
 * Bağımlılık yok (saf Node) + ffmpeg boru hattı.
 * Yıldız haritası estetiğinde 10 saniyelik, sessiz, döngüye uygun
 * anlatı videosu üretir: gece → takımyıldız → gözlem taraması →
 * yörünge → ızgara → şafak.
 *
 * Kullanım:  node scripts/gen-narrative.mjs
 * Çıktı:     public/landing/media/narrative.mp4 (+ poster karesi .jpg)
 */

import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const OUT_DIR = join(ROOT, "public", "landing", "media");
const OUT_MP4 = join(OUT_DIR, "narrative.mp4");
const OUT_POSTER = join(OUT_DIR, "narrative-poster.jpg");

const W = 960;
const H = 540;
const FPS = 24;
const DUR = 10; // saniye
const FRAMES = FPS * DUR;

// ---------- yardımcılar ----------
const clamp01 = (v) => (v < 0 ? 0 : v > 1 ? 1 : v);
const smooth = (a, b, t) => {
  const x = clamp01((t - a) / (b - a));
  return x * x * (3 - 2 * x);
};
const easeInOut = (x) => (x < 0.5 ? 2 * x * x : 1 - Math.pow(-2 * x + 2, 2) / 2);
const lerp = (a, b, t) => a + (b - a) * t;
const TAU = Math.PI * 2;

// deterministik RNG (mulberry32) — her üretimde aynı video
function rng(seed) {
  let s = seed >>> 0;
  return () => {
    s |= 0;
    s = (s + 0x6d2b79f5) | 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// ---------- yıldız alanı ----------
const rand = rng(20260830);
const LAYERS = [
  { n: 300, speed: 0.7, r: 0.6, base: 0.55 }, // uzak
  { n: 160, speed: 1.7, r: 0.85, base: 0.85 }, // orta
  { n: 64, speed: 3.4, r: 1.2, base: 1.2 }, // yakın, parlak
];
const stars = LAYERS.map((L) =>
  Array.from({ length: L.n }, () => ({
    x: rand() * W,
    y: rand() * H,
    tw: 0.6 + rand() * 2.6, // twinkle hızı
    ph: rand() * TAU,
    gold: rand() < 0.14, // %14 altın tonlu
    ...L,
  }))
);

// takımyıldız — "gözlem" okuması yapan el yerleşimi
const CONSTELLATION = [
  [0.13, 0.34],
  [0.25, 0.25],
  [0.38, 0.30],
  [0.49, 0.19],
  [0.59, 0.27],
  [0.72, 0.21],
].map(([x, y]) => [x * W, y * H]);

// ---------- çizim ilkeleri (additif, Float32 tampon) ----------
const buf = new Float32Array(W * H * 3);

function skyBase(t) {
  // dikey gradyan: derin indigo gece; şafakla alt kısım ısınır
  const dawn = smooth(8.6, 10.0, t);
  const top = [10 + dawn * 6, 14 + dawn * 4, 30 + dawn * 2];
  const bot = [20 + dawn * 60, 26 + dawn * 34, 48 + dawn * 8];
  for (let y = 0; y < H; y++) {
    const ty = y / H;
    const r = lerp(top[0], bot[0], ty);
    const g = lerp(top[1], bot[1], ty);
    const b = lerp(top[2], bot[2], ty);
    for (let x = 0; x < W; x++) {
      const i = (y * W + x) * 3;
      buf[i] = r;
      buf[i + 1] = g;
      buf[i + 2] = b;
    }
  }
  // iki yumuşak nebula lekesi — gökyüzünü düz gradyan olmaktan çıkarır
  const nebulas = [
    { x: W * 0.26, y: H * 0.3, r: H * 0.75, c: [7, 11, 26] },
    { x: W * 0.74, y: H * 0.66, r: H * 0.85, c: [5, 8, 20] },
  ];
  for (const n of nebulas) {
    const r2max = n.r * n.r;
    const x0 = Math.max(0, Math.floor(n.x - n.r));
    const x1 = Math.min(W - 1, Math.ceil(n.x + n.r));
    const y0 = Math.max(0, Math.floor(n.y - n.r));
    const y1 = Math.min(H - 1, Math.ceil(n.y + n.r));
    for (let y = y0; y <= y1; y++) {
      for (let x = x0; x <= x1; x++) {
        const dx = x - n.x;
        const dy = y - n.y;
        const d2 = dx * dx + dy * dy;
        if (d2 > r2max) continue;
        const a = Math.exp(-d2 / (r2max * 0.34));
        const i = (y * W + x) * 3;
        buf[i] += n.c[0] * a;
        buf[i + 1] += n.c[1] * a;
        buf[i + 2] += n.c[2] * a;
      }
    }
  }
}

function vignetteAndGrain(frame) {
  const cx = W / 2;
  const cy = H / 2;
  const maxR2 = cx * cx + cy * cy;
  for (let y = 0; y < H; y++) {
    const dy = y - cy;
    for (let x = 0; x < W; x++) {
      const dx = x - cx;
      const r2 = (dx * dx + dy * dy) / maxR2;
      const vig = 1 - 0.32 * r2;
      // ucuz hash gürültüsü — ince film dokusu
      const h = Math.sin(x * 12.9898 + y * 78.233 + frame * 0.37) * 43758.5453;
      const n = (h - Math.floor(h) - 0.5) * 3.2;
      const i = (y * W + x) * 3;
      buf[i] = buf[i] * vig + n;
      buf[i + 1] = buf[i + 1] * vig + n;
      buf[i + 2] = buf[i + 2] * vig + n;
    }
  }
}

// yumuşak nokta (yıldız / gezegen) — gauss benzeri splat
function splat(px, py, radius, intensity, color) {
  const r2max = (radius * 2.6) ** 2;
  const x0 = Math.max(0, Math.floor(px - radius * 2.6));
  const x1 = Math.min(W - 1, Math.ceil(px + radius * 2.6));
  const y0 = Math.max(0, Math.floor(py - radius * 2.6));
  const y1 = Math.min(H - 1, Math.ceil(py + radius * 2.6));
  for (let y = y0; y <= y1; y++) {
    for (let x = x0; x <= x1; x++) {
      const dx = x - px;
      const dy = y - py;
      const d2 = dx * dx + dy * dy;
      if (d2 > r2max) continue;
      const a = Math.exp(-d2 / (radius * radius * 0.8)) * intensity;
      const i = (y * W + x) * 3;
      buf[i] += color[0] * a;
      buf[i + 1] += color[1] * a;
      buf[i + 2] += color[2] * a;
    }
  }
}

// AA'lı çizgi parçası (segment)
function seg(x1, y1, x2, y2, hw, alpha, color) {
  const pad = hw + 2;
  const x0 = Math.max(0, Math.floor(Math.min(x1, x2) - pad));
  const x1b = Math.min(W - 1, Math.ceil(Math.max(x1, x2) + pad));
  const y0 = Math.max(0, Math.floor(Math.min(y1, y2) - pad));
  const y1b = Math.min(H - 1, Math.ceil(Math.max(y1, y2) + pad));
  const dx = x2 - x1;
  const dy = y2 - y1;
  const len2 = dx * dx + dy * dy || 1;
  for (let y = y0; y <= y1b; y++) {
    for (let x = x0; x <= x1b; x++) {
      const px = x - x1;
      const py = y - y1;
      let u = (px * dx + py * dy) / len2;
      u = u < 0 ? 0 : u > 1 ? 1 : u;
      const qx = px - u * dx;
      const qy = py - u * dy;
      const d = Math.sqrt(qx * qx + qy * qy);
      const cov = clamp01(hw + 0.5 - d) * alpha;
      if (cov <= 0) continue;
      const i = (y * W + x) * 3;
      buf[i] += color[0] * cov;
      buf[i + 1] += color[1] * cov;
      buf[i + 2] += color[2] * cov;
    }
  }
}

// eliptik yay — kısa segmentler halinde çizilir
function arc(cx, cy, rx, ry, rot, a0, a1, hw, alpha, color) {
  const steps = Math.max(8, Math.ceil(((rx + ry) / 2 * Math.abs(a1 - a0)) / 2));
  let pxa, pya;
  for (let s = 0; s <= steps; s++) {
    const a = lerp(a0, a1, s / steps);
    const ex = Math.cos(a) * rx;
    const ey = Math.sin(a) * ry;
    const x = cx + ex * Math.cos(rot) - ey * Math.sin(rot);
    const y = cy + ex * Math.sin(rot) + ey * Math.cos(rot);
    if (s > 0) seg(pxa, pya, x, y, hw, alpha, color);
    pxa = x;
    pya = y;
  }
}

// ---------- sahneler ----------
const STAR_WHITE = [255, 246, 228];
const STAR_GOLD = [236, 198, 122];
const LINE_GOLD = [214, 188, 132];
const LINE_BLUE = [148, 170, 214];
const DAWN = [238, 158, 84];

function drawStars(t) {
  for (const layer of stars) {
    for (const s of layer) {
      const tw = 0.72 + 0.28 * Math.sin(t * s.tw + s.ph);
      const x = ((s.x + t * s.speed) % (W + 6)) - 3;
      splat(x, s.y, s.r, s.base * tw, s.gold ? STAR_GOLD : STAR_WHITE);
    }
  }
}

function drawConstellation(t) {
  const reveal = smooth(1.5, 4.2, t); // çizgiler sırayla çizilir
  const fade = 1 - smooth(8.8, 10.0, t) * 0.55; // şafakta geri çekilir
  const n = CONSTELLATION.length;
  const total = n - 1;
  const done = reveal * total;
  for (let i = 0; i < total; i++) {
    const segP = clamp01(done - i);
    if (segP <= 0) break;
    const a = CONSTELLATION[i];
    const b = CONSTELLATION[i + 1];
    seg(a[0], a[1], lerp(a[0], b[0], easeInOut(segP)), lerp(a[1], b[1], easeInOut(segP)), 1.2, 0.4 * fade, LINE_GOLD);
  }
  // düğümler
  for (let i = 0; i < n; i++) {
    if (done < i) break;
    const [x, y] = CONSTELLATION[i];
    splat(x, y, 2.0, 1.35 * fade, STAR_WHITE);
  }
  // ana yıldız: sahneler boyunca kalır, yalnız şafakta söner
  const [kx, ky] = CONSTELLATION[4];
  const keyFade = 1 - smooth(8.9, 10.0, t) * 0.7;
  const flare = (0.5 + 0.5 * Math.sin(t * 2.2)) * keyFade;
  seg(kx - 17, ky, kx + 17, ky, 1.0, 0.55 * flare, STAR_GOLD);
  seg(kx, ky - 17, kx, ky + 17, 1.0, 0.55 * flare, STAR_GOLD);
  splat(kx, ky, 2.6, 1.5 * keyFade, STAR_GOLD);
}

function drawObservation(t) {
  // kubbe silüeti + radar taraması (Rasathane sahnesi)
  const on = smooth(4.0, 4.6, t) * (1 - smooth(5.9, 6.5, t));
  if (on <= 0.001) return;
  const cx = W * 0.5;
  const cy = H * 1.28; // ufkun altından yükselen kubbe
  const R = H * 0.78;
  arc(cx, cy, R, R, 0, Math.PI + 0.42, TAU - 0.42, 1.4, 0.4 * on, LINE_BLUE);
  // tarama çizgisi
  const sweep = smooth(4.2, 5.8, t);
  const ang = lerp(Math.PI + 0.5, TAU - 0.5, easeInOut(sweep));
  const ex = cx + Math.cos(ang) * R;
  const ey = cy + Math.sin(ang) * R;
  seg(cx, cy, ex, ey, 1.1, 0.42 * on, STAR_WHITE);
  // iz bırakan yay
  arc(cx, cy, R, R, 0, Math.max(Math.PI + 0.42, ang - 0.7), ang, 2.6, 0.16 * on, LINE_BLUE);
  splat(ex, ey, 2.0, 0.9 * on, STAR_WHITE);
}

function drawOrbits(t) {
  const on = smooth(5.7, 6.3, t) * (1 - smooth(7.5, 8.1, t));
  if (on <= 0.001) return;
  const cx = W * 0.5;
  const cy = H * 0.5;
  const rings = [
    { rx: 150, ry: 128, rot: -0.22, a: 0.3 },
    { rx: 236, ry: 198, rot: 0.16, a: 0.24 },
    { rx: 330, ry: 276, rot: -0.07, a: 0.18 },
  ];
  const draw = smooth(5.8, 7.0, t);
  for (const r of rings) {
    arc(cx, cy, r.rx, r.ry, r.rot, -Math.PI, -Math.PI + TAU * draw, 1.3, r.a * on, LINE_BLUE);
  }
  // gezegen: orta halka üzerinde hareket eder
  const p = t * 1.05 + 2.1;
  const r2 = rings[1];
  const ex = Math.cos(p) * r2.rx;
  const ey = Math.sin(p) * r2.ry;
  const px = cx + ex * Math.cos(r2.rot) - ey * Math.sin(r2.rot);
  const py = cy + ex * Math.sin(r2.rot) + ey * Math.cos(r2.rot);
  splat(px, py, 3.4, 1.15 * on, STAR_GOLD);
  splat(px, py, 8.5, 0.16 * on, STAR_GOLD);
  splat(cx, cy, 2.6, 0.85 * on, STAR_WHITE); // merkez yıldız
}

function drawGrid(t) {
  const on = smooth(7.4, 8.0, t) * (1 - smooth(8.9, 9.5, t));
  if (on <= 0.001) return;
  const step = 96;
  for (let x = step; x < W; x += step) {
    seg(x, 0, x, H, 0.9, 0.17 * on, LINE_BLUE);
  }
  for (let y = step; y < H; y += step) {
    seg(0, y, W, y, 0.9, 0.17 * on, LINE_BLUE);
  }
  // kavşak düğümleri — nabız
  const nodes = [
    [W * 0.28, H * 0.34],
    [W * 0.5, H * 0.62],
    [W * 0.72, H * 0.34],
  ];
  for (const [nx, ny] of nodes) {
    const pulse = 0.5 + 0.5 * Math.sin(t * 3.1 + nx);
    splat(nx, ny, 2.2, (0.9 + 0.6 * pulse) * on, STAR_GOLD);
  }
}

function drawDawn(t) {
  const d = smooth(8.9, 10.0, t);
  if (d <= 0.001) return;
  for (let y = H * 0.6; y < H; y++) {
    const f = Math.pow((y - H * 0.6) / (H * 0.4), 1.4);
    const a = f * d * 0.42;
    for (let x = 0; x < W; x++) {
      const i = (y * W + x) * 3;
      buf[i] += DAWN[0] * a;
      buf[i + 1] += DAWN[1] * a;
      buf[i + 2] += DAWN[2] * a;
    }
  }
  // ufuk çizgisi
  seg(0, H * 0.82, W, H * 0.82, 0.9, 0.24 * d, DAWN);
}

// ---------- kare üretimi + encode ----------
const frameBuf = Buffer.alloc(W * H * 3 + 32);
const header = Buffer.from(`P6\n${W} ${H}\n255\n`);

function renderFrame(f) {
  const t = f / FPS;
  skyBase(t);
  drawStars(t);
  drawConstellation(t);
  drawObservation(t);
  drawOrbits(t);
  drawGrid(t);
  drawDawn(t);
  vignetteAndGrain(f);
}

mkdirSync(OUT_DIR, { recursive: true });

const ff = spawn(
  "ffmpeg",
  [
    "-y", "-loglevel", "error",
    "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", `${W}x${H}`, "-r", String(FPS),
    "-i", "-",
    "-c:v", "libx264", "-preset", "slow", "-crf", "30",
    "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an",
    OUT_MP4,
  ],
  { stdio: ["pipe", "inherit", "inherit"] }
);

let frame = 0;
function writeNext() {
  let ok = true;
  while (ok && frame < FRAMES) {
    renderFrame(frame);
    header.copy(frameBuf, 0);
    const body = frameBuf.subarray(header.length, header.length + W * H * 3);
    for (let i = 0; i < W * H * 3; i++) {
      const v = buf[i];
      body[i] = v <= 0 ? 0 : v >= 255 ? 255 : v | 0;
    }
    ok = ff.stdin.write(frameBuf.subarray(0, header.length + W * H * 3));
    frame++;
    if (frame % 48 === 0) process.stdout.write(`  kare ${frame}/${FRAMES}\n`);
  }
  if (frame >= FRAMES) ff.stdin.end();
}

ff.stdin.on("drain", writeNext);
writeNext();

ff.on("close", (code) => {
  if (code !== 0) {
    console.error(`ffmpeg hata kodu: ${code}`);
    process.exit(code);
  }
  // poster: takımyıldızın net göründüğü an
  const poster = spawn("ffmpeg", [
    "-y", "-loglevel", "error",
    "-ss", "3.4", "-i", OUT_MP4, "-frames:v", "1", "-q:v", "4",
    OUT_POSTER,
  ]);
  poster.on("close", (c) => {
    if (c !== 0) { console.error(`poster hatası: ${c}`); process.exit(c); }
    console.log(`tamam → ${OUT_MP4}`);
    console.log(`poster → ${OUT_POSTER}`);
  });
});
