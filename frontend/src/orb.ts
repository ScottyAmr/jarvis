/**
 * JARVIS — Neural sphere orb.
 *
 * A cohesive, breathing sphere of particles with a glowing core, subtle
 * neighbour connections, heartbeat "ping" rings, and per-state colour/motion.
 *
 * Particles are anchored to a spherical shell and positioned parametrically
 * each frame (base direction * animated radius + bounded wobble) rather than by
 * integrating velocity — so the orb stays a coherent sphere and never scatters.
 */

import * as THREE from "three";

export type OrbState = "idle" | "listening" | "thinking" | "speaking";

export interface Orb {
  setState(s: OrbState): void;
  setAnalyser(a: AnalyserNode | null): void;
  destroy(): void;
}

interface StateCfg {
  color: THREE.Color;   // particle / accent colour
  core: THREE.Color;    // hot core tint
  radius: number;       // shell radius
  spin: number;         // rotation speed
  breathe: number;      // breathing amplitude
  bright: number;       // particle opacity
  lines: number;        // connection-line strength
}

export function createOrb(canvas: HTMLCanvasElement): Orb {
  let destroyed = false;
  const N = 1600;

  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setSize(window.innerWidth, window.innerHeight);
  renderer.setClearColor(0x04060d, 1);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(45, window.innerWidth / window.innerHeight, 1, 1000);
  camera.position.z = 78;

  const group = new THREE.Group();
  scene.add(group);

  // ── Per-particle base directions (fibonacci sphere) + shell factor ──
  const dir = new Float32Array(N * 3);
  const shell = new Float32Array(N);   // 0.72–1.0 : how far out on the shell
  const phase = new Float32Array(N);
  const gold = Math.PI * (3 - Math.sqrt(5));
  for (let i = 0; i < N; i++) {
    const y = 1 - (i / (N - 1)) * 2;
    const r = Math.sqrt(Math.max(0, 1 - y * y));
    const th = i * gold;
    dir[i * 3] = Math.cos(th) * r;
    dir[i * 3 + 1] = y;
    dir[i * 3 + 2] = Math.sin(th) * r;
    shell[i] = 0.72 + Math.random() * 0.28;
    phase[i] = Math.random() * Math.PI * 2;
  }

  const geo = new THREE.BufferGeometry();
  const pos = new Float32Array(N * 3);
  geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  const mat = new THREE.PointsMaterial({
    color: 0x35d6ff, size: 0.5, transparent: true, opacity: 0.7,
    sizeAttenuation: true, blending: THREE.AdditiveBlending, depthWrite: false,
  });
  const points = new THREE.Points(geo, mat);
  group.add(points);

  // ── Neighbour connection lines ──
  const MAX_LINES = 2600;
  const linePos = new Float32Array(MAX_LINES * 6);
  const lineGeo = new THREE.BufferGeometry();
  lineGeo.setAttribute("position", new THREE.BufferAttribute(linePos, 3));
  lineGeo.setDrawRange(0, 0);
  const lineMat = new THREE.LineBasicMaterial({
    color: 0x35d6ff, transparent: true, opacity: 0.0,
    blending: THREE.AdditiveBlending, depthWrite: false,
  });
  const lines = new THREE.LineSegments(lineGeo, lineMat);
  group.add(lines);

  // ── Glowing core (additive sprite from a canvas radial gradient) ──
  function glowTexture(): THREE.Texture {
    const s = 128;
    const cv = document.createElement("canvas");
    cv.width = cv.height = s;
    const g = cv.getContext("2d")!;
    const rg = g.createRadialGradient(s / 2, s / 2, 0, s / 2, s / 2, s / 2);
    rg.addColorStop(0, "rgba(255,255,255,1)");
    rg.addColorStop(0.25, "rgba(255,255,255,0.75)");
    rg.addColorStop(0.55, "rgba(255,255,255,0.22)");
    rg.addColorStop(1, "rgba(255,255,255,0)");
    g.fillStyle = rg; g.fillRect(0, 0, s, s);
    const tex = new THREE.Texture(cv);
    tex.needsUpdate = true;
    return tex;
  }
  const coreMat = new THREE.SpriteMaterial({
    map: glowTexture(), color: 0xbfefff, transparent: true,
    blending: THREE.AdditiveBlending, depthWrite: false, opacity: 0.9,
  });
  const core = new THREE.Sprite(coreMat);
  core.scale.set(26, 26, 1);
  scene.add(core); // in scene (not group) so it doesn't spin with particles

  const haloMat = new THREE.SpriteMaterial({
    map: coreMat.map, color: 0x35d6ff, transparent: true,
    blending: THREE.AdditiveBlending, depthWrite: false, opacity: 0.35,
  });
  const halo = new THREE.Sprite(haloMat);
  halo.scale.set(64, 64, 1);
  scene.add(halo);

  // ── Heartbeat ping rings ──
  interface Ping { mesh: THREE.Mesh; t: number; }
  const pings: Ping[] = [];
  const ringMat = new THREE.MeshBasicMaterial({
    color: 0x35d6ff, transparent: true, opacity: 0, side: THREE.DoubleSide,
    blending: THREE.AdditiveBlending, depthWrite: false,
  });
  for (let i = 0; i < 3; i++) {
    const m = new THREE.Mesh(new THREE.RingGeometry(0.92, 1.0, 96), ringMat.clone());
    m.visible = false;
    scene.add(m);
    pings.push({ mesh: m, t: 1 });
  }
  let lastPing = 0;

  // ── State configs ──
  const STATES: Record<OrbState, StateCfg> = {
    idle:      { color: new THREE.Color(0x35d6ff), core: new THREE.Color(0xbfefff), radius: 26, spin: 0.06, breathe: 1.3, bright: 0.6, lines: 0.15 },
    listening: { color: new THREE.Color(0x5ae0ff), core: new THREE.Color(0xd8f7ff), radius: 23, spin: 0.14, breathe: 1.0, bright: 0.8, lines: 0.4 },
    thinking:  { color: new THREE.Color(0x9d7bff), core: new THREE.Color(0xe0d4ff), radius: 20, spin: 0.30, breathe: 1.8, bright: 0.85, lines: 1.0 },
    speaking:  { color: new THREE.Color(0x7fe8ff), core: new THREE.Color(0xffffff), radius: 24, spin: 0.10, breathe: 1.4, bright: 0.9, lines: 0.7 },
  };

  let state: OrbState = "idle";
  // smoothed live values
  let radius = 26, spin = 0.06, breathe = 1.3, bright = 0.6, lineAmt = 0.15, rot = 0;
  const col = new THREE.Color(0x35d6ff);
  const coreCol = new THREE.Color(0xbfefff);

  // ── Audio ──
  let analyser: AnalyserNode | null = null;
  let freqData = new Uint8Array(64);
  let bass = 0, mid = 0, amp = 0;

  const clock = new THREE.Clock();

  function spawnPing(t: number, color: THREE.Color) {
    const p = pings.find((p) => p.t >= 1);
    if (!p) return;
    p.t = 0;
    p.mesh.visible = true;
    (p.mesh.material as THREE.MeshBasicMaterial).color.copy(color);
    lastPing = t;
  }

  function animate() {
    if (destroyed) return;
    requestAnimationFrame(animate);
    const t = clock.getElapsedTime();
    const cfg = STATES[state];

    // audio
    bass = mid = amp = 0;
    if (analyser) {
      analyser.getByteFrequencyData(freqData);
      let b = 0, m = 0, s = 0;
      for (let i = 0; i < 6; i++) b += freqData[i];
      for (let i = 6; i < 20; i++) m += freqData[i];
      for (let i = 0; i < freqData.length; i++) s += freqData[i];
      bass = b / (6 * 255); mid = m / (14 * 255); amp = s / (freqData.length * 255);
    }

    // smooth toward state targets
    const k = 0.05;
    radius += (cfg.radius - radius) * k;
    spin += (cfg.spin - spin) * k;
    breathe += (cfg.breathe - breathe) * k;
    bright += (cfg.bright - bright) * k;
    lineAmt += (cfg.lines - lineAmt) * k;
    col.lerp(cfg.color, 0.04);
    coreCol.lerp(cfg.core, 0.04);

    rot += spin * 0.016 * 3;
    group.rotation.y = rot;
    group.rotation.x = Math.sin(t * 0.15) * 0.25;

    // breathing radius (+ bass swell)
    const breath = Math.sin(t * (state === "thinking" ? 1.1 : 0.6)) * breathe;
    const liveR = radius + breath + bass * 6;

    // position particles on the shell
    const a = (geo.getAttribute("position") as THREE.BufferAttribute).array as Float32Array;
    for (let i = 0; i < N; i++) {
      const i3 = i * 3;
      const wob = Math.sin(t * 0.9 + phase[i]) * 0.6 + Math.sin(t * 0.37 + phase[i] * 1.7) * 0.4;
      let r = liveR * shell[i] + wob;
      if (state === "speaking" && mid > 0.05) r += Math.sin(t * 9 + phase[i]) * mid * 5;
      a[i3] = dir[i3] * r;
      a[i3 + 1] = dir[i3 + 1] * r;
      a[i3 + 2] = dir[i3 + 2] * r;
    }
    (geo.getAttribute("position") as THREE.BufferAttribute).needsUpdate = true;

    mat.color.copy(col);
    mat.opacity = bright + amp * 0.15;
    mat.size = 0.5 + bass * 0.25;

    // ── neighbour lines (bounded, cheap) ──
    if (lineAmt > 0.02) {
      const la = (lineGeo.getAttribute("position") as THREE.BufferAttribute).array as Float32Array;
      const maxD = 6.5, maxDSq = maxD * maxD;
      const step = 4;
      let lc = 0;
      for (let i = 0; i < N && lc < MAX_LINES; i += step) {
        const i3 = i * 3, x1 = a[i3], y1 = a[i3 + 1], z1 = a[i3 + 2];
        for (let j = i + step; j < N && lc < MAX_LINES; j += step) {
          const j3 = j * 3;
          const dx = a[j3] - x1, dy = a[j3 + 1] - y1, dz = a[j3 + 2] - z1;
          if (dx * dx + dy * dy + dz * dz < maxDSq) {
            const o = lc * 6;
            la[o] = x1; la[o + 1] = y1; la[o + 2] = z1;
            la[o + 3] = a[j3]; la[o + 4] = a[j3 + 1]; la[o + 5] = a[j3 + 2];
            lc++;
          }
        }
      }
      lineGeo.setDrawRange(0, lc * 2);
      (lineGeo.getAttribute("position") as THREE.BufferAttribute).needsUpdate = true;
      lineMat.color.copy(col);
      lineMat.opacity = lineAmt * 0.14;
    } else {
      lineGeo.setDrawRange(0, 0);
    }

    // ── core + halo ──
    const pulse = 1 + Math.sin(t * (state === "speaking" ? 6 : 2.4)) * 0.06 + amp * 0.3;
    core.scale.setScalar((7 + bass * 5) * pulse);
    coreMat.color.copy(coreCol);
    coreMat.opacity = 0.85 + amp * 0.15;
    halo.scale.setScalar((liveR * 2.4) * (1 + amp * 0.1));
    haloMat.color.copy(col);
    haloMat.opacity = 0.18 + bright * 0.12;

    // ── heartbeat pings ──
    const pingGap = state === "thinking" ? 0.9 : state === "speaking" ? 1.0 : 1.6;
    if (t - lastPing > pingGap) spawnPing(t, col);
    for (const p of pings) {
      if (p.t >= 1) { p.mesh.visible = false; continue; }
      p.t += 0.016 / (state === "idle" ? 1.6 : 1.1);
      const scl = liveR * (0.9 + p.t * 1.7);
      p.mesh.scale.setScalar(scl);
      p.mesh.lookAt(camera.position);
      (p.mesh.material as THREE.MeshBasicMaterial).opacity = (1 - p.t) * 0.5;
    }

    camera.position.x = Math.sin(t * 0.05) * 4;
    camera.position.y = Math.cos(t * 0.04) * 2.5;
    camera.lookAt(0, 0, 0);
    core.position.set(0, 0, 0);
    halo.position.set(0, 0, 0);

    renderer.render(scene, camera);
  }

  function onResize() {
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight);
  }

  window.addEventListener("resize", onResize);
  animate();

  return {
    setState(s: OrbState) { state = s; },
    setAnalyser(a: AnalyserNode | null) {
      analyser = a;
      if (a) freqData = new Uint8Array(a.frequencyBinCount);
    },
    destroy() {
      destroyed = true;
      window.removeEventListener("resize", onResize);
      renderer.dispose();
    },
  };
}
