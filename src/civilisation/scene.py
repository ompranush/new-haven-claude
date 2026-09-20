"""3D village renderer: a self-contained three.js scene fed by the same JSON snapshot as iso.py.

Sunlight with shadows, low-poly trees, gabled houses, distinct buildings per business
kind, chimney smoke, drifting clouds, a slow day/night cycle, citizens that walk between
snapshots, orbit camera, hover tooltips. The iframe never re-mounts; it polls the snapshot.
"""
from __future__ import annotations
import json
from .iso import world_payload

JS = r"""
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

let D = __DATA__;
const T = D.codes;
const URL = "__URL__";
const wrap = document.getElementById('wrap'), tip = document.getElementById('tip');

// ---------------------------------------------------------------- renderer, scene, camera
const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.AgXToneMapping; renderer.toneMappingExposure = 1.0;
renderer.outputColorSpace = THREE.SRGBColorSpace;
wrap.appendChild(renderer.domElement);
const scene = new THREE.Scene();
const NIGHT = new THREE.Color('#0e1626'), DAYSKY = new THREE.Color('#223652');
scene.background = DAYSKY.clone();
scene.fog = new THREE.Fog(scene.background, 60, 140);
const camera = new THREE.PerspectiveCamera(40, 1, 0.1, 400);
const W = D.w, H = D.h, CX = W / 2, CZ = H / 2;
const TC = (() => { const bs = D.buildings; if (!bs.length) return [CX, CZ]; return [(CX + bs.reduce((a, b) => a + b.x, 0) / bs.length) / 2, (CZ + bs.reduce((a, b) => a + b.y, 0) / bs.length) / 2]; })();
camera.position.set(TC[0] + 19, 17, TC[1] + 19);
const controls = new OrbitControls(camera, renderer.domElement);
controls.target.set(TC[0], 0.5, TC[1]); controls.enableDamping = true; controls.dampingFactor = 0.08;
controls.maxPolarAngle = Math.PI / 2.25; controls.minDistance = 8; controls.maxDistance = 110;
controls.update();

const hemi = new THREE.HemisphereLight('#dbe9f7', '#4a5a3a', 0.95); scene.add(hemi);
scene.add(new THREE.AmbientLight('#ffffff', 0.22));
const sun = new THREE.DirectionalLight('#fff4e0', 1.35);
sun.castShadow = true; sun.shadow.mapSize.set(2048, 2048); sun.shadow.radius = 6;
sun.shadow.camera.left = -45; sun.shadow.camera.right = 45; sun.shadow.camera.top = 45; sun.shadow.camera.bottom = -45;
sun.shadow.camera.near = 1; sun.shadow.camera.far = 160; sun.shadow.bias = -0.0008; sun.shadow.normalBias = 0.02;
scene.add(sun); scene.add(sun.target); sun.target.position.set(CX, 0, CZ);

// ---------------------------------------------------------------- helpers
const rnd = (x, y, k) => { let s = Math.sin(x * 127.1 + y * 311.7 + k * 74.7) * 43758.5453; return s - Math.floor(s); };
const col = h => new THREE.Color(h);
const vary = (c, amt, x, y, k) => c.clone().offsetHSL(0, 0, (rnd(x, y, k) - 0.5) * amt);
const mat = (c, o = {}) => new THREE.MeshStandardMaterial({ color: c, roughness: 0.9, metalness: 0.0, ...o });
const box = new THREE.BoxGeometry(1, 1, 1);
const dummy = new THREE.Object3D();
function instanced(geom, material, n) { const m = new THREE.InstancedMesh(geom, material, n); m.castShadow = true; m.receiveShadow = true; m.count = 0; scene.add(m); return m; }
function place(mesh, x, y, z, sx, sy, sz, color, ry = 0) {
  dummy.position.set(x, y, z); dummy.rotation.set(0, ry, 0); dummy.scale.set(sx, sy, sz); dummy.updateMatrix();
  mesh.setMatrixAt(mesh.count, dummy.matrix); if (color) mesh.setColorAt(mesh.count, color); mesh.count++;
}
function finish(mesh) { mesh.instanceMatrix.needsUpdate = true; if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true; }

// ---------------------------------------------------------------- terrain
const ground = instanced(box, mat('#ffffff'), W * H + 200);
const water = instanced(box, new THREE.MeshPhysicalMaterial({ color: '#2f7fd0', roughness: 0.25, metalness: 0.1, transparent: true, opacity: 0.88, emissive: '#0b3d7a', emissiveIntensity: 0.25 }), W * H);
water.castShadow = false;
const rows = instanced(new THREE.BoxGeometry(0.08, 0.12, 0.92), mat('#6b4d1e'), W * H * 3);
const wheat = instanced(new THREE.ConeGeometry(0.05, 0.28, 4), mat('#d9b74a'), W * H * 4);
const trunks = instanced(new THREE.CylinderGeometry(0.06, 0.1, 0.7, 6), mat('#5a3d22'), W * H * 2);
const canopy1 = instanced(new THREE.IcosahedronGeometry(0.42, 1), mat('#3f8f3f', { flatShading: true }), W * H * 2);
const canopy2 = instanced(new THREE.IcosahedronGeometry(0.28, 1), mat('#5cb04a', { flatShading: true }), W * H * 2);
const snow = instanced(box, mat('#e8eef2'), W * H);
const pebbles = instanced(new THREE.DodecahedronGeometry(0.12, 0), mat('#a7a7a2', { flatShading: true }), W * H);

const C = { grass: col('#7cae63'), farm: col('#c6a566'), forest: col('#5c9150'), rock: col('#8f918d'), town: col('#c8bda8'), road: col('#b3a48c'), bank: col('#8a7a55') };
function buildTerrain() {
  ground.count = 0; water.count = 0; rows.count = 0; wheat.count = 0; trunks.count = 0; canopy1.count = 0; canopy2.count = 0; snow.count = 0; pebbles.count = 0;
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
    const t = D.grid[y][x], px = x + 0.5, pz = y + 0.5;
    if (t === T.WATER) { place(ground, px, -0.6, pz, 1, 0.8, 1, vary(col('#2a4d6d'), 0.1, x, y, 1)); place(water, px, 0.05, pz, 1, 0.5, 1, null); continue; }
    let h = 0.5, c = C.grass;
    if (t === T.FARM) c = vary(C.farm, 0.12, x, y, 2);
    else if (t === T.FOREST) c = vary(C.forest, 0.12, x, y, 2);
    else if (t === T.ROCK) { h = 1 + Math.floor(2.6 * rnd(x, y, 4)) * 0.8; c = vary(C.rock, 0.15, x, y, 2); }
    else if (t === T.TOWN) c = vary(C.town, 0.08, x, y, 2);
    else if (t === T.ROAD) { h = 0.45; c = vary(C.road, 0.06, x, y, 2); }
    else c = vary(C.grass, 0.14, x, y, 2);
    place(ground, px, h / 2, pz, 1, h, 1, c);
    if (t === T.FARM) {
      for (let i = 0; i < 3; i++) place(rows, x + 0.2 + i * 0.3, h + 0.05, pz, 1, 1, 1, null);
      for (let i = 0; i < 4; i++) place(wheat, x + 0.12 + (i % 2) * 0.55 + rnd(x, y, 30 + i) * 0.25, h + 0.14, y + 0.2 + Math.floor(i / 2) * 0.5, 1, 0.8 + rnd(x, y, 40 + i) * 0.5, 1, vary(col('#d9b74a'), 0.2, x, y, 50 + i));
    } else if (t === T.FOREST) {
      const n = 1 + (rnd(x, y, 9) > 0.55 ? 1 : 0);
      for (let i = 0; i < n; i++) {
        const ox = 0.25 + rnd(x, y, 11 + i) * 0.5, oz = 0.25 + rnd(x, y, 13 + i) * 0.5, s = 0.8 + rnd(x, y, 15 + i) * 0.6;
        place(trunks, x + ox, h + 0.3 * s, y + oz, 1, s, 1, null);
        place(canopy1, x + ox, h + 0.75 * s, y + oz, s, s * 1.1, s, vary(col('#3f8f3f'), 0.25, x, y, 17 + i));
        place(canopy2, x + ox + 0.05, h + 1.15 * s, y + oz - 0.05, s, s, s, vary(col('#5cb04a'), 0.25, x, y, 19 + i));
      }
    } else if (t === T.ROCK) {
      if (h > 2.2) place(snow, px, h + 0.08, pz, 0.7, 0.16, 0.7, null);
      if (rnd(x, y, 21) > 0.5) place(pebbles, x + 0.3 + rnd(x, y, 22) * 0.4, h + 0.08, y + 0.3 + rnd(x, y, 23) * 0.4, 1, 1, 1, vary(C.rock, 0.2, x, y, 24));
    } else if (t === T.GRASS && rnd(x, y, 25) > 0.8) {
      place(pebbles, x + 0.2 + rnd(x, y, 26) * 0.6, h + 0.05, y + 0.2 + rnd(x, y, 27) * 0.6, 0.6, 0.5, 0.6, vary(col('#7c8c6a'), 0.2, x, y, 28));
    }
  }
  [ground, water, rows, wheat, trunks, canopy1, canopy2, snow, pebbles].forEach(finish);
}
buildTerrain();

// ---------------------------------------------------------------- buildings
const STYLE = {
  ancient:    { walls: ['#e3d4b3', '#d8c7a3', '#ecdfc0'], roofs: ['#b7583f', '#a8503a', '#c2664b'], roof: 'flat', smoke: 0.5 },
  medieval:   { walls: ['#e5d6b8', '#d9c7a6', '#eadfc8', '#cdbb9a', '#f0e6d2'], roofs: ['#8b3f34', '#5d6b7a', '#6d4a34', '#4d6a4a', '#b39a4a'], roof: 'pyramid', smoke: 1 },
  industrial: { walls: ['#8d4b3b', '#7e4436', '#9a5646', '#6f3d31'], roofs: ['#4b5563', '#3f4753', '#56606e'], roof: 'pyramid', smoke: 1.6 },
  modern:     { walls: ['#e6e6e6', '#cbd5e1', '#d9dee6', '#bfc7d1'], roofs: ['#3b3f46', '#2f333a'], roof: 'flat', smoke: 0.2 },
  future:     { walls: ['#e8f0f2', '#d3e4ea', '#c9dde6'], roofs: ['#2dd4bf', '#38bdf8', '#a78bfa'], roof: 'dome', smoke: 0 },
};
const ST = STYLE[D.style] || STYLE.medieval;
const walls = instanced(box, mat('#ffffff'), 600);
const roofs = instanced(ST.roof === 'dome' ? new THREE.SphereGeometry(0.42, 12, 8, 0, Math.PI * 2, 0, Math.PI / 2) : (ST.roof === 'flat' ? new THREE.BoxGeometry(1.08, 0.12, 1.08) : new THREE.ConeGeometry(0.72, 0.5, 4)),
                        mat('#ffffff', { flatShading: ST.roof === 'pyramid', emissive: ST.roof === 'dome' ? '#0e7490' : '#000000', emissiveIntensity: ST.roof === 'dome' ? 0.25 : 0 }), 600);
const stacks = instanced(new THREE.CylinderGeometry(0.12, 0.16, 2.2, 8), mat('#5b4a44'), 80);
const chimneys = instanced(box, mat('#5a5651'), 600), doors = instanced(box, mat('#3a2a1a'), 600), windows = instanced(box, new THREE.MeshStandardMaterial({ color: '#ffd98a', emissive: '#ffb347', emissiveIntensity: 0 }), 1200);
const built = new THREE.Group(); scene.add(built);
const labels = new THREE.Group(); scene.add(labels);
const smokeSources = [];
let buildKey = "";

function textSprite(text) {
  const c = document.createElement('canvas'); const ctx = c.getContext('2d');
  ctx.font = '600 28px system-ui, sans-serif'; const w = ctx.measureText(text).width + 28; c.width = w; c.height = 44;
  ctx.font = '600 28px system-ui, sans-serif'; ctx.fillStyle = 'rgba(12,16,24,0.85)'; ctx.beginPath(); ctx.roundRect(0, 0, w, 44, 10); ctx.fill();
  ctx.fillStyle = '#eef2f7'; ctx.textBaseline = 'middle'; ctx.fillText(text, 14, 23);
  const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace;
  const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthTest: false, transparent: true }));
  sp.scale.set(w / 44 * 0.75, 0.75, 1); return sp;
}
const ICON = { farm: '🌾', bakery: '🥖', workshop: '⚒️', market: '🏪', mine: '⛏️', tavern: '🍺', school: '🏫', clinic: '🏥' };
const bmeshes = [];   // for hover
function addBox(g, x, y, z, sx, sy, sz, color, extra = {}) { const m = new THREE.Mesh(box, mat(color, extra)); m.position.set(x, y, z); m.scale.set(sx, sy, sz); m.castShadow = m.receiveShadow = true; g.add(m); return m; }
function gable(g, x, y, z, sx, sy, sz, color, ry = 0) { const m = new THREE.Mesh(new THREE.ConeGeometry(0.71, 1, 4), mat(color, { flatShading: true })); m.position.set(x, y, z); m.rotation.y = Math.PI / 4 + ry; m.scale.set(sx, sy, sz); m.castShadow = true; g.add(m); return m; }
function business(b) {
  const g = new THREE.Group(); const x = b.x + 0.5, z = b.y + 0.5, base = 0.5;
  const k = b.kind;
  if (k === 'farm') { addBox(g, x, base + 0.5, z, 1.3, 1.0, 0.95, '#a23b34'); gable(g, x, base + 1.35, z, 1.05, 0.7, 0.8, '#5c2a25'); addBox(g, x + 0.85, base + 0.7, z - 0.2, 0.35, 1.4, 0.35, '#c9c3b6'); addBox(g, x - 0.3, base + 0.35, z + 0.5, 0.3, 0.7, 0.04, '#3a2a1a'); }
  else if (k === 'mine') { addBox(g, x, base + 0.6, z, 1.1, 1.2, 1.0, '#6e6e6a'); addBox(g, x, base + 0.35, z + 0.52, 0.5, 0.7, 0.08, '#111'); addBox(g, x - 0.35, base + 0.5, z + 0.58, 0.08, 1.0, 0.08, '#7a5230'); addBox(g, x + 0.35, base + 0.5, z + 0.58, 0.08, 1.0, 0.08, '#7a5230'); addBox(g, x, base + 1.0, z + 0.58, 0.85, 0.08, 0.08, '#7a5230'); }
  else if (k === 'market') { addBox(g, x, base + 0.35, z, 1.2, 0.7, 0.9, '#e9dcc0'); for (let i = 0; i < 5; i++) addBox(g, x - 0.5 + i * 0.25, base + 0.78, z + 0.55, 0.25, 0.06, 0.4, i % 2 ? '#e8e2d6' : '#d94545'); addBox(g, x - 0.55, base + 0.4, z + 0.72, 0.06, 0.8, 0.06, '#7a5230'); addBox(g, x + 0.55, base + 0.4, z + 0.72, 0.06, 0.8, 0.06, '#7a5230'); }
  else if (k === 'tavern') { addBox(g, x, base + 0.55, z, 1.0, 1.1, 0.9, '#8a5a2b'); gable(g, x, base + 1.4, z, 0.85, 0.7, 0.75, '#3d2416'); addBox(g, x + 0.62, base + 0.9, z + 0.3, 0.06, 0.06, 0.4, '#3a2a1a'); addBox(g, x + 0.62, base + 0.72, z + 0.5, 0.05, 0.3, 0.3, '#d9a441', { emissive: '#d9a441', emissiveIntensity: 0.35 }); smokeSources.push([x - 0.3, base + 1.9, z - 0.2]); }
  else if (k === 'school') { addBox(g, x, base + 0.55, z, 1.1, 1.1, 0.9, '#f1f1ee'); gable(g, x, base + 1.4, z, 0.9, 0.7, 0.75, '#2f5aa8'); addBox(g, x, base + 1.85, z, 0.3, 0.5, 0.3, '#f1f1ee'); addBox(g, x, base + 2.2, z, 0.36, 0.2, 0.36, '#2f5aa8'); }
  else if (k === 'clinic') { addBox(g, x, base + 0.5, z, 1.1, 1.0, 0.9, '#f7f7f5'); addBox(g, x, base + 1.05, z, 1.15, 0.1, 0.95, '#c94a4a'); addBox(g, x, base + 0.75, z + 0.47, 0.12, 0.4, 0.04, '#c94a4a'); addBox(g, x, base + 0.75, z + 0.47, 0.4, 0.12, 0.04, '#c94a4a'); }
  else if (k === 'workshop') { addBox(g, x, base + 0.55, z, 1.1, 1.1, 0.9, '#5c4028'); gable(g, x, base + 1.4, z, 0.9, 0.6, 0.75, '#2d2118'); addBox(g, x + 0.35, base + 1.5, z - 0.2, 0.2, 0.9, 0.2, '#4a4642'); smokeSources.push([x + 0.35, base + 2.0, z - 0.2]); }
  else { addBox(g, x, base + 0.5, z, 1.0, 1.0, 0.9, '#efdcae'); gable(g, x, base + 1.35, z, 0.85, 0.7, 0.75, '#b06f2b'); addBox(g, x - 0.3, base + 1.45, z - 0.2, 0.2, 0.8, 0.2, '#4a4642'); smokeSources.push([x - 0.3, base + 1.9, z - 0.2]); }
  g.userData = { kind: 'business', b };
  const label = textSprite(`${ICON[k] || ''} ${b.name}`); label.position.set(x, base + 2.9, z); labels.add(label);
  built.add(g); g.traverse(m => { if (m.isMesh) { m.userData.b = b; bmeshes.push(m); } });
}
function buildStructures() {
  const key = D.buildings.map(b => b.x + ',' + b.y + b.kind).join('|') + '#' + D.homes.length;
  if (key === buildKey) return; buildKey = key;
  built.clear(); labels.clear(); bmeshes.length = 0; smokeSources.length = 0;
  walls.count = roofs.count = chimneys.count = doors.count = windows.count = 0;
  const taken = new Set(D.buildings.map(b => b.x + ',' + b.y));
  D.buildings.forEach(business);
  const wallCols = ST.walls, roofCols = ST.roofs;
  stacks.count = 0;
  D.homes.forEach(([x, y]) => {
    if (taken.has(x + ',' + y) || D.grid[y][x] === T.WATER) return;
    const px = x + 0.5, pz = y + 0.5, base = D.grid[y][x] === T.ROCK ? 1 : 0.5, s = 0.55 + rnd(x, y, 31) * 0.15, ry = Math.floor(rnd(x, y, 32) * 4) * Math.PI / 2;
    const tall = D.style === 'modern' || D.style === 'future' ? 0.64 + rnd(x, y, 37) * 0.5 : 0.64;
    place(walls, px, base + tall / 2, pz, s, tall, s, col(wallCols[Math.floor(rnd(x, y, 33) * wallCols.length)]), ry);
    if (ST.roof === 'pyramid') place(roofs, px, base + tall + 0.24, pz, s * 1.05, 0.5, s * 1.05, col(roofCols[Math.floor(rnd(x, y, 34) * roofCols.length)]), Math.PI / 4 + ry);
    else if (ST.roof === 'flat') place(roofs, px, base + tall + 0.05, pz, s, 1, s, col(roofCols[Math.floor(rnd(x, y, 34) * roofCols.length)]), ry);
    else place(roofs, px, base + tall, pz, s * 1.2, s * 1.2, s * 1.2, col(roofCols[Math.floor(rnd(x, y, 34) * roofCols.length)]), ry);
    if (ST.smoke > 0 && rnd(x, y, 35) > 0.4) { place(chimneys, px + 0.18 * s, base + tall + 0.2, pz - 0.12 * s, 0.1, 0.35, 0.1, null); if (rnd(x, y, 36) * 1.6 < ST.smoke) smokeSources.push([px + 0.18 * s, base + tall + 0.4, pz - 0.12 * s]); }
    place(doors, px, base + 0.15, pz + s / 2 + 0.01, 0.14, 0.3, 0.03, null, ry);
    place(windows, px - 0.16 * s, base + 0.4, pz + s / 2 + 0.01, 0.12, 0.12, 0.03, null, ry);
    place(windows, px + 0.16 * s, base + 0.4, pz + s / 2 + 0.01, 0.12, 0.12, 0.03, null, ry);
  });
  if (D.style === 'industrial') D.buildings.filter(b => b.kind === 'workshop' || b.kind === 'mine').forEach(b => { place(stacks, b.x + 1.1, 1.6, b.y + 0.2, 1, 1, 1, null); smokeSources.push([b.x + 1.1, 2.8, b.y + 0.2]); smokeSources.push([b.x + 1.1, 2.8, b.y + 0.2]); });
  [walls, roofs, chimneys, doors, windows, stacks].forEach(finish);
  buildAnimals();
}

// ---------------------------------------------------------------- citizens (instanced, walking between snapshots)
const MAXC = 1200;
const bodies = instanced(new THREE.CapsuleGeometry(0.11, 0.22, 3, 8), mat('#ffffff', { roughness: 0.7 }), MAXC);
const heads = instanced(new THREE.SphereGeometry(0.1, 10, 8), mat('#f2c9a0'), MAXC);
const rings = instanced(new THREE.TorusGeometry(0.28, 0.035, 8, 24), new THREE.MeshBasicMaterial({ color: '#ffffff' }), 64);
rings.castShadow = false;
const people = new Map();   // id -> {from:[x,z], to:[x,z], t0, col, ...}
function tileTop(x, y) { const t = D.grid[Math.max(0, Math.min(H - 1, y))][Math.max(0, Math.min(W - 1, x))]; return t === T.WATER ? 0.3 : (t === T.ROCK ? 1 + Math.floor(2.6 * rnd(x, y, 4)) * 0.8 : 0.5); }
function setCitizens(list, now) {
  const seen = new Set();
  list.forEach(c => {
    seen.add(c.id);
    const ox = 0.3 + 0.4 * rnd(c.id, 1, 1), oz = 0.3 + 0.4 * rnd(c.id, 2, 2);
    const to = [c.x + ox, c.y + oz];
    let p = people.get(c.id);
    if (!p) { p = { from: to, to, t0: now, id: c.id }; people.set(c.id, p); }
    else if (p.to[0] !== to[0] || p.to[1] !== to[1]) { p.from = p.cur || p.to; p.to = to; p.t0 = now; }
    Object.assign(p, { name: c.name, job: c.job, age: c.age, inf: c.inf, sel: c.sel, col: col(c.col), child: c.job === 'child' });
  });
  for (const id of [...people.keys()]) if (!seen.has(id)) people.delete(id);
}
setCitizens(D.citizens, performance.now());
const hoverList = [];
function animatePeople(now) {
  bodies.count = heads.count = rings.count = 0; hoverList.length = 0;
  for (const p of people.values()) {
    const k = Math.min(1, (now - p.t0) / 1400), e = k * k * (3 - 2 * k);
    const x = p.from[0] + (p.to[0] - p.from[0]) * e, z = p.from[1] + (p.to[1] - p.from[1]) * e;
    p.cur = [x, z];
    const walking = k < 1, bob = walking ? Math.abs(Math.sin(now / 90 + p.id)) * 0.06 : 0;
    const y = tileTop(Math.floor(x), Math.floor(z)), s = p.child ? 0.7 : 1;
    const face = walking ? Math.atan2(p.to[0] - p.from[0], p.to[1] - p.from[1]) : p.id;
    place(bodies, x, y + 0.22 * s + bob, z, s, s, s, p.col, face);
    place(heads, x, y + 0.48 * s + bob, z, s, s, s, null, face);
    if (p.sel) { dummy.position.set(x, y + 0.03, z); dummy.rotation.set(Math.PI / 2, 0, 0); dummy.scale.set(1, 1, 1); dummy.updateMatrix(); rings.setMatrixAt(rings.count, dummy.matrix); rings.setColorAt(rings.count, col('#ffd43b')); rings.count++; }
    else if (p.inf) { dummy.position.set(x, y + 0.03, z); dummy.rotation.set(Math.PI / 2, 0, 0); dummy.scale.set(0.8, 0.8, 0.8); dummy.updateMatrix(); rings.setMatrixAt(rings.count, dummy.matrix); rings.setColorAt(rings.count, col('#ff5252')); rings.count++; }
    hoverList.push([x, y + 0.35, z, p]);
  }
  [bodies, heads, rings].forEach(finish);
}

// ---------------------------------------------------------------- animals
const cowBody = instanced(new THREE.BoxGeometry(0.5, 0.3, 0.28), mat('#7a4b2a'), 200), cowHead = instanced(new THREE.BoxGeometry(0.2, 0.2, 0.2), mat('#5c3a20'), 200);
const sheepBody = instanced(new THREE.CapsuleGeometry(0.13, 0.22, 3, 8), mat('#f1efe8'), 200), sheepHead = instanced(new THREE.SphereGeometry(0.08, 8, 6), mat('#2b2b2b'), 200);
const henBody = instanced(new THREE.SphereGeometry(0.09, 8, 6), mat('#f4e4c1'), 200), henComb = instanced(new THREE.BoxGeometry(0.04, 0.06, 0.06), mat('#d43f3f'), 200);
const deerBody = instanced(new THREE.BoxGeometry(0.42, 0.26, 0.2), mat('#9a6b3f'), 60), deerHead = instanced(new THREE.BoxGeometry(0.14, 0.2, 0.14), mat('#8a5f36'), 60);
const birdMesh = instanced(new THREE.ConeGeometry(0.08, 0.22, 3), new THREE.MeshBasicMaterial({ color: '#2a2f3a' }), 60);
birdMesh.castShadow = false;
let animals = [];       // {kind, x, z, tx, tz, anchor:[x,z], r, speed, wait, face}
const flocks = [];
function landOk(x, z) { const gx = Math.floor(x), gz = Math.floor(z); if (gx < 0 || gz < 0 || gx >= W || gz >= H) return false; const t = D.grid[gz][gx]; return t !== T.WATER && t !== T.ROCK; }
function spawn(kind, ax, az, r, speed) {
  for (let tries = 0; tries < 12; tries++) { const x = ax + (Math.random() - 0.5) * 2 * r, z = az + (Math.random() - 0.5) * 2 * r; if (landOk(x, z)) { animals.push({ kind, x, z, tx: x, tz: z, anchor: [ax, az], r, speed, wait: Math.random() * 3, face: 0 }); return; } }
}
function buildAnimals() {
  animals = [];
  D.buildings.filter(b => b.kind === 'farm').forEach(b => { const n = Math.min(12, b.herd || 0); for (let i = 0; i < n; i++) spawn(rnd(b.x, b.y, i) > 0.5 ? 'cow' : 'sheep', b.x + 0.5, b.y + 0.5, 3.2, 0.25); });
  D.homes.forEach(([x, y], i) => { if (i % 4 === 0 && D.style !== 'future') spawn('hen', x + 0.5, y + 0.5, 1.4, 0.5); });
  let forest = []; for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) if (D.grid[y][x] === T.FOREST) forest.push([x, y]);
  for (let i = 0; i < Math.min(10, forest.length / 12); i++) { const [x, y] = forest[Math.floor(rnd(i, 3, 7) * forest.length)]; spawn('deer', x + 0.5, y + 0.5, 4, 0.6); }
  if (!flocks.length) for (let f = 0; f < 3; f++) flocks.push({ cx: Math.random() * W, cz: Math.random() * H, r: 4 + Math.random() * 4, h: 7 + Math.random() * 3, ph: Math.random() * 6, n: 5 + Math.floor(Math.random() * 4), spd: 0.25 + Math.random() * 0.2 });
}
function animateAnimals(dt, now) {
  cowBody.count = cowHead.count = sheepBody.count = sheepHead.count = henBody.count = henComb.count = deerBody.count = deerHead.count = birdMesh.count = 0;
  for (const a of animals) {
    if (a.wait > 0) a.wait -= dt;
    else {
      const dx = a.tx - a.x, dz = a.tz - a.z, d = Math.hypot(dx, dz);
      if (d < 0.05) { a.wait = 1 + Math.random() * 4; for (let t = 0; t < 8; t++) { const nx = a.anchor[0] + (Math.random() - 0.5) * 2 * a.r, nz = a.anchor[1] + (Math.random() - 0.5) * 2 * a.r; if (landOk(nx, nz)) { a.tx = nx; a.tz = nz; break; } } }
      else { const st = Math.min(d, a.speed * dt); a.x += dx / d * st; a.z += dz / d * st; a.face = Math.atan2(dx, dz); }
    }
    const y = tileTop(Math.floor(a.x), Math.floor(a.z)), moving = a.wait <= 0, bob = moving ? Math.abs(Math.sin(now / 120 + a.x * 10)) * 0.03 : 0;
    if (a.kind === 'cow') { place(cowBody, a.x, y + 0.22 + bob, a.z, 1, 1, 1, null, a.face); place(cowHead, a.x + Math.sin(a.face) * 0.3, y + 0.28 + bob, a.z + Math.cos(a.face) * 0.3, 1, 1, 1, null, a.face); }
    else if (a.kind === 'sheep') { place(sheepBody, a.x, y + 0.18 + bob, a.z, 1, 1, 1, null, a.face + Math.PI / 2); place(sheepHead, a.x + Math.sin(a.face) * 0.2, y + 0.2 + bob, a.z + Math.cos(a.face) * 0.2, 1, 1, 1, null, 0); }
    else if (a.kind === 'hen') { place(henBody, a.x, y + 0.09 + bob * 2, a.z, 1, 1, 1, null, a.face); place(henComb, a.x, y + 0.19 + bob * 2, a.z, 1, 1, 1, null, a.face); }
    else if (a.kind === 'deer') { place(deerBody, a.x, y + 0.3 + bob, a.z, 1, 1, 1, null, a.face); place(deerHead, a.x + Math.sin(a.face) * 0.28, y + 0.45 + bob, a.z + Math.cos(a.face) * 0.28, 1, 1, 1, null, a.face); }
  }
  for (const f of flocks) {
    f.ph += dt * f.spd;
    for (let i = 0; i < f.n; i++) { const ang = f.ph - i * 0.18, x = f.cx + Math.cos(ang) * f.r + (i % 2 ? 0.3 : -0.3) * i * 0.3, z = f.cz + Math.sin(ang) * f.r, yy = f.h + Math.sin(now / 400 + i) * 0.25;
      dummy.position.set(x, yy, z); dummy.rotation.set(Math.PI / 2, 0, -ang); dummy.scale.set(1, 1, 1); dummy.updateMatrix(); birdMesh.setMatrixAt(birdMesh.count++, dummy.matrix); }
  }
  [cowBody, cowHead, sheepBody, sheepHead, henBody, henComb, deerBody, deerHead, birdMesh].forEach(finish);
}

// ---------------------------------------------------------------- smoke & clouds
const smokeGeo = new THREE.BufferGeometry(); const NS = 240; const sp = new Float32Array(NS * 3); const sage = new Float32Array(NS);
for (let i = 0; i < NS; i++) sage[i] = Math.random();
smokeGeo.setAttribute('position', new THREE.BufferAttribute(sp, 3));
const smoke = new THREE.Points(smokeGeo, new THREE.PointsMaterial({ color: '#cfd6dd', size: 0.22, transparent: true, opacity: 0.45, depthWrite: false })); scene.add(smoke);
function animateSmoke(dt) {
  if (!smokeSources.length) return;
  for (let i = 0; i < NS; i++) {
    sage[i] += dt * 0.25; if (sage[i] > 1) sage[i] -= 1;
    const src = smokeSources[i % smokeSources.length], a = sage[i];
    sp[i * 3] = src[0] + Math.sin(a * 9 + i) * 0.12 * a + a * 0.3; sp[i * 3 + 1] = src[1] + a * 1.6; sp[i * 3 + 2] = src[2] + Math.cos(a * 7 + i) * 0.12 * a;
  }
  smokeGeo.attributes.position.needsUpdate = true;
}
const clouds = [];
for (let i = 0; i < 7; i++) {
  const g = new THREE.Group();
  for (let j = 0; j < 4; j++) { const m = new THREE.Mesh(new THREE.SphereGeometry(1.2 + Math.random() * 1.2, 10, 8), new THREE.MeshStandardMaterial({ color: '#ffffff', transparent: true, opacity: 0.55, roughness: 1 })); m.position.set(j * 1.4 - 2, Math.random() * 0.4, (Math.random() - 0.5) * 1.5); m.scale.y = 0.45; m.castShadow = true; g.add(m); }
  g.position.set(Math.random() * (W + 20) - 10, 20 + Math.random() * 5, Math.random() * H); g.scale.setScalar(0.8); g.userData.v = 0.4 + Math.random() * 0.5; clouds.push(g); scene.add(g);
}

// ---------------------------------------------------------------- day / night
const CYCLE = 240; // seconds per full day
function daylight(t) {
  const ph = (t / CYCLE + 0.25) % 1, a = ph * Math.PI * 2, elev = Math.sin(a);
  sun.position.set(CX + Math.cos(a) * 50, 12 + elev * 50, CZ + 25); sun.intensity = Math.max(0.05, elev) * 1.3 + 0.15;
  sun.color.setHSL(0.09, 0.5, 0.5 + Math.max(0, elev) * 0.45);
  const day = Math.max(0, Math.min(1, (elev + 0.15) / 0.5));
  hemi.intensity = 0.3 + day * 0.7;
  scene.background.copy(NIGHT).lerp(DAYSKY, day); scene.fog.color.copy(scene.background);
  windows.material.emissiveIntensity = (1 - day) * 1.4;
}

// ---------------------------------------------------------------- hover
const ray = new THREE.Raycaster(); const mouse = new THREE.Vector2(-9, -9);
renderer.domElement.addEventListener('mousemove', e => { const r = renderer.domElement.getBoundingClientRect(); mouse.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1); tip.style.left = (e.clientX - r.left + 14) + 'px'; tip.style.top = (e.clientY - r.top + 14) + 'px'; });
renderer.domElement.addEventListener('mouseleave', () => { tip.style.display = 'none'; mouse.set(-9, -9); });
const v3 = new THREE.Vector3();
function hover() {
  if (mouse.x < -2) return;
  ray.setFromCamera(mouse, camera);
  let best = null, bd = 0.45;
  for (const [x, y, z, p] of hoverList) { v3.set(x, y, z); const d = ray.ray.distanceToPoint(v3); if (d < bd) { bd = d; best = p; } }
  if (best) { tip.style.display = 'block'; tip.replaceChildren(Object.assign(document.createElement('b'), {textContent: best.name}), document.createElement('br'), document.createTextNode(`${best.job}, ${best.age}${best.inf ? ' · 🦠 sick' : ''}`)); return; }
  const hit = ray.intersectObjects(bmeshes, false)[0];
  if (hit) { const b = hit.object.userData.b; tip.style.display = 'block'; tip.replaceChildren(Object.assign(document.createElement('b'), {textContent: b.name}), document.createElement('br'), document.createTextNode(`${b.staff} staff · £${b.cash.toLocaleString()} cash`)); }
  else tip.style.display = 'none';
}

// ---------------------------------------------------------------- loop, resize, polling
function fit() { const w = wrap.clientWidth, h = wrap.clientHeight; renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix(); }
new ResizeObserver(fit).observe(wrap); fit();
buildStructures();
let last = performance.now();
function loop(now) {
  const dt = Math.min(0.1, (now - last) / 1000); last = now;
  daylight(now / 1000); animatePeople(now); animateSmoke(dt); animateAnimals(dt, now);
  clouds.forEach(c => { c.position.x += c.userData.v * dt; if (c.position.x > W + 12) c.position.x = -12; });
  water.material.emissiveIntensity = 0.2 + 0.08 * Math.sin(now / 900);
  controls.update(); hover(); renderer.render(scene, camera); requestAnimationFrame(loop);
}
requestAnimationFrame(loop);
let lastDay = D.day, lastSel = D.sel;
async function poll() {
  try {
    const r = await fetch(URL + '?t=' + Date.now(), { cache: 'no-store' });
    if (r.ok) { const nd = await r.json(); if (nd.day !== lastDay || nd.sel !== lastSel || nd.citizens.length !== D.citizens.length) { D = nd; lastDay = nd.day; lastSel = nd.sel; buildStructures(); setCitizens(D.citizens, performance.now()); } }
  } catch (e) {}
  setTimeout(poll, 500);
}
if (URL) poll();
"""

HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;background:#0b1220;overflow:hidden;font-family:system-ui,sans-serif}
#wrap{position:relative;width:100%;height:__H__px;border-radius:12px;overflow:hidden;background:#0b1220}
canvas{display:block;width:100%;height:100%}
#tip{position:absolute;display:none;pointer-events:none;background:rgba(15,20,30,.92);color:#eef2f7;padding:6px 9px;border-radius:8px;font-size:12px;border:1px solid #2b3a4f;white-space:nowrap;z-index:2}
#hint{position:absolute;right:10px;bottom:8px;color:#8b98a8;font-size:11px;z-index:2}
</style>
<script type="importmap">{"imports":{"three":"https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js","three/addons/":"https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/"}}</script>
</head><body><div id="wrap"><div id="tip"></div><div id="hint">drag to orbit · scroll to zoom · right-drag to pan · hover for names</div></div>
<script type="module">__JS__</script></body></html>"""


def render_html(world, selected=None, height: int = 620, url: str = "") -> str:
    payload = world_payload(world, selected)
    payload["sel"] = selected
    return HTML.replace("__H__", str(height)).replace("__JS__", JS.replace("__DATA__", json.dumps(payload)).replace("__URL__", url))
