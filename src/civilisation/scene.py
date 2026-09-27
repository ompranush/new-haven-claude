"""3D realm renderer: a self-contained three.js scene fed by the JSON snapshot in iso.world_payload.

The five villages on their river, each with its own land (snow and pine, open plains, deep
forest, ash and lava, beaches and a lake) and building palette. People nearest the camera are
rigged, animated figures (CC0 Quaternius mannequin) that walk, talk, work, fight, dance, mourn,
cast spells and fall; the rest are cheap instanced figures. Animals are animated models (CC0
Quaternius; CC-BY Poly for the big cats, bear, elephant and eagle). The camera can follow one
person. Everything the world does to the land shows: dams, ash, ruins, craters; and every shock a
god or a war produces has an effect — meteors, wildfire, lightning, whirlwinds, earthquakes,
floods, riots, mage spells, and armies fighting on the border. The iframe never re-mounts; it
polls the snapshot and animates between them. Model credits: static/models/CREDITS.md.
"""
from __future__ import annotations
import json
from .iso import world_payload

JS = r"""
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import * as SkeletonUtils from 'three/addons/utils/SkeletonUtils.js';

let D = __DATA__;
const T = D.codes;
const URL = "__URL__";
const MODELS = "__MODELS__";
const HERO = __HERO__;   // backdrop mode: no input, a slow cinematic orbit
const wrap = document.getElementById('wrap'), tip = document.getElementById('tip'), cap = document.getElementById('cap');

// ---------------------------------------------------------------- renderer, scene, camera
const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.AgXToneMapping; renderer.toneMappingExposure = 1.05;
renderer.outputColorSpace = THREE.SRGBColorSpace;
wrap.appendChild(renderer.domElement);
const scene = new THREE.Scene();
const NIGHT = new THREE.Color('#0c1424'), DAYSKY = new THREE.Color('#2a4466');
scene.background = DAYSKY.clone();
scene.fog = new THREE.Fog(scene.background, 55, 150);
const camera = new THREE.PerspectiveCamera(40, 1, 0.05, 500);
const W = D.w, H = D.h, CX = W / 2, CZ = H / 2;
// the same controls as production: left-drag orbits and tilts (top view to side view), right-drag pans, the wheel zooms —
// toward the cursor, so any part of the realm can be zoomed into
const controls = new OrbitControls(camera, renderer.domElement);
controls.zoomToCursor = true; controls.screenSpacePanning = false;     // the pivot stays on the ground as you pan and zoom
controls.enableDamping = true; controls.dampingFactor = 0.08;
controls.maxPolarAngle = Math.PI / 2.25; controls.minDistance = 1; controls.maxDistance = 140;
function villageCentre(i) { const v = D.villages[i] || D.villages[0]; return [v.centre[0] + 0.5, v.centre[1] + 0.5]; }
let focusIdx = D.focus;
{ const [x, z] = villageCentre(focusIdx); controls.target.set(x, 0.5, z); camera.position.set(x + 13, 15, z + 19); }
if (HERO) {
  camera.position.set(CX + 30, 30, CZ + 42); controls.target.set(CX, 0, CZ);
  controls.enabled = false; controls.autoRotate = true; controls.autoRotateSpeed = 0.3;
}
controls.update();
const camGoal = { target: null, pos: null };      // smooth camera moves (village change, follow)

const hemi = new THREE.HemisphereLight('#dbe9f7', '#4a5a3a', 0.95); scene.add(hemi);
scene.add(new THREE.AmbientLight('#ffffff', 0.22));
const sun = new THREE.DirectionalLight('#fff4e0', 1.35);
sun.castShadow = true; sun.shadow.mapSize.set(2048, 2048); sun.shadow.radius = 5;
sun.shadow.camera.left = -40; sun.shadow.camera.right = 40; sun.shadow.camera.top = 40; sun.shadow.camera.bottom = -40;
sun.shadow.camera.near = 1; sun.shadow.camera.far = 200; sun.shadow.bias = -0.0008; sun.shadow.normalBias = 0.02;
scene.add(sun); scene.add(sun.target);

// ---------------------------------------------------------------- helpers
const rnd = (x, y, k) => { let s = Math.sin(x * 127.1 + y * 311.7 + k * 74.7) * 43758.5453; return s - Math.floor(s); };
const col = h => new THREE.Color(h);
const vary = (c, amt, x, y, k) => c.clone().offsetHSL(0, 0, (rnd(x, y, k) - 0.5) * amt);
const mat = (c, o = {}) => new THREE.MeshStandardMaterial({ color: c, roughness: 0.9, metalness: 0.0, ...o });
const box = new THREE.BoxGeometry(1, 1, 1);
const dummy = new THREE.Object3D();
function instanced(geom, material, n) { const m = new THREE.InstancedMesh(geom, material, n); m.castShadow = true; m.receiveShadow = true; m.count = 0; m.frustumCulled = false; scene.add(m); return m; }
function place(mesh, x, y, z, sx, sy, sz, color, ry = 0) {
  if (mesh.count >= mesh.instanceMatrix.count) return;
  dummy.position.set(x, y, z); dummy.rotation.set(0, ry, 0); dummy.scale.set(sx, sy, sz); dummy.updateMatrix();
  mesh.setMatrixAt(mesh.count, dummy.matrix); if (color) mesh.setColorAt(mesh.count, color); mesh.count++;
}
function finish(mesh) { mesh.instanceMatrix.needsUpdate = true; if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true; }
function regionOf(x, y) { for (const v of D.villages) { const r = v.region; if (x >= r[0] && x < r[2] && y >= r[1] && y < r[3]) return v; } return D.villages[0]; }

// ---------------------------------------------------------------- terrain
const ground = instanced(box, mat('#ffffff'), W * H + 50);
const water = instanced(box, new THREE.MeshPhysicalMaterial({ color: '#2f7fd0', roughness: 0.2, metalness: 0.1, transparent: true, opacity: 0.86, emissive: '#0b3d7a', emissiveIntensity: 0.25 }), W * H);
water.castShadow = false;
const lava = instanced(box, new THREE.MeshStandardMaterial({ color: '#ff4a12', emissive: '#ff3300', emissiveIntensity: 1.2, roughness: 0.6 }), W * H);
lava.castShadow = false;
const rows = instanced(new THREE.BoxGeometry(0.08, 0.12, 0.92), mat('#6b4d1e'), W * H * 3);
const wheat = instanced(new THREE.ConeGeometry(0.05, 0.28, 4), mat('#d9b74a'), W * H * 4);
const trunks = instanced(new THREE.CylinderGeometry(0.06, 0.1, 0.7, 6), mat('#5a3d22'), W * H * 2);
const canopy1 = instanced(new THREE.IcosahedronGeometry(0.42, 1), mat('#ffffff', { flatShading: true }), W * H * 2);
const canopy2 = instanced(new THREE.IcosahedronGeometry(0.28, 1), mat('#ffffff', { flatShading: true }), W * H * 2);
const pines = instanced(new THREE.ConeGeometry(0.34, 1.0, 7), mat('#ffffff', { flatShading: true }), W * H * 2);
const snowcap = instanced(box, mat('#eef3f7'), W * H);
const pebbles = instanced(new THREE.DodecahedronGeometry(0.12, 0), mat('#ffffff', { flatShading: true }), W * H);
const rubble = instanced(new THREE.DodecahedronGeometry(0.16, 0), mat('#ffffff', { flatShading: true }), W * H);
const damWall = instanced(box, mat('#6b5a44'), 60);

const C = { grass: col('#7cae63'), farm: col('#c6a566'), forest: col('#5c9150'), rock: col('#8f918d'), town: col('#c8bda8'), road: col('#b3a48c'),
            sand: col('#e2cf98'), snow: col('#dfe7ee'), ash: col('#4a403b'), ruin: col('#5b5550') };
// every element tints its own land
const TINT = { sky: { grass: '#8fb58a', forest: '#3f6f55', rock: '#9aa0a6' }, air: { grass: '#b3c77a', forest: '#6f9a4e', rock: '#b8ad96' },
               earth: { grass: '#6fa857', forest: '#3f7d3e', rock: '#8a7d6a' }, fire: { grass: '#8a8f55', forest: '#5d6b3a', rock: '#3b3431' },
               water: { grass: '#7fbf82', forest: '#4f9a6a', rock: '#9aa7a8' } };
const tintC = {}; for (const [el, t] of Object.entries(TINT)) tintC[el] = { grass: col(t.grass), forest: col(t.forest), rock: col(t.rock) };
const H0 = {};
// hills rise smoothly: height comes from how much high ground surrounds a tile, not a dice roll per tile
const HMAP = [];
function isHigh(x, y) { if (x < 0 || y < 0 || x >= W || y >= H) return 0; const t = D.grid[y][x]; return t === T.SNOW ? 1.6 : (t === T.ROCK ? 1 : 0); }
function buildHeights() {
  for (let y = 0; y < H; y++) { HMAP[y] = []; for (let x = 0; x < W; x++) {
    let s = 0; for (let dy = -2; dy <= 2; dy++) for (let dx = -2; dx <= 2; dx++) s += isHigh(x + dx, y + dy);
    HMAP[y][x] = s / 25; } }
}
buildHeights();
function heightAt(x, y) {
  x = Math.max(0, Math.min(W - 1, x | 0)); y = Math.max(0, Math.min(H - 1, y | 0));
  const t = D.grid[y][x];
  if (t === T.WATER || t === T.DAM) return 0.3;
  if (t === T.ROCK || t === T.SNOW) return 0.7 + HMAP[y][x] * 1.7 + rnd(x, y, 4) * 0.15;
  if (t === T.LAVA) return 0.35;
  return 0.5;
}
function buildTerrain() {
  [ground, water, lava, rows, wheat, trunks, canopy1, canopy2, pines, snowcap, pebbles, rubble, damWall].forEach(m => m.count = 0);
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
    const t = D.grid[y][x], px = x + 0.5, pz = y + 0.5, v = regionOf(x, y), tc = tintC[v.el] || tintC.earth;
    if (t === T.WATER || t === T.DAM) {
      place(ground, px, -0.6, pz, 1, 0.8, 1, vary(col('#2a4d6d'), 0.1, x, y, 1)); place(water, px, 0.05, pz, 1, 0.5, 1, null);
      if (t === T.DAM) { place(damWall, px, 0.55, pz, 1.05, 1.1, 0.5, null); place(damWall, px, 1.15, pz, 1.1, 0.15, 0.6, null); }
      continue;
    }
    if (t === T.LAVA) { place(ground, px, -0.2, pz, 1, 0.6, 1, col('#2a1a14')); place(lava, px, 0.18, pz, 0.92, 0.3, 0.92, null); continue; }
    const h = heightAt(x, y);
    let c;
    if (t === T.FARM) c = vary(C.farm, 0.12, x, y, 2);
    else if (t === T.FOREST) c = vary(tc.forest, 0.12, x, y, 2);
    else if (t === T.ROCK) c = vary(tc.rock, 0.15, x, y, 2);
    else if (t === T.SNOW) c = vary(C.snow, 0.05, x, y, 2);
    else if (t === T.TOWN) c = vary(C.town, 0.08, x, y, 2);
    else if (t === T.ROAD) c = vary(C.road, 0.06, x, y, 2);
    else if (t === T.SAND) c = vary(C.sand, 0.08, x, y, 2);
    else if (t === T.ASH) c = vary(C.ash, 0.12, x, y, 2);
    else if (t === T.RUIN) c = vary(C.ruin, 0.1, x, y, 2);
    else c = vary(tc.grass, 0.14, x, y, 2);
    place(ground, px, h / 2, pz, 1, h, 1, c);
    if (t === T.FARM) {
      for (let i = 0; i < 3; i++) place(rows, x + 0.2 + i * 0.3, h + 0.05, pz, 1, 1, 1, null);
      for (let i = 0; i < 4; i++) place(wheat, x + 0.12 + (i % 2) * 0.55 + rnd(x, y, 30 + i) * 0.25, h + 0.14, y + 0.2 + Math.floor(i / 2) * 0.5, 1, 0.8 + rnd(x, y, 40 + i) * 0.5, 1, vary(col('#d9b74a'), 0.2, x, y, 50 + i));
    } else if (t === T.FOREST) {
      const n = 1 + (rnd(x, y, 9) > 0.55 ? 1 : 0);
      for (let i = 0; i < n; i++) {
        const ox = 0.25 + rnd(x, y, 11 + i) * 0.5, oz = 0.25 + rnd(x, y, 13 + i) * 0.5, s = 0.8 + rnd(x, y, 15 + i) * 0.6;
        if (v.el === 'sky' || (v.el === 'air' && rnd(x, y, 5) > 0.5)) {
          place(trunks, x + ox, h + 0.2 * s, y + oz, 0.8, s * 0.6, 0.8, null);
          place(pines, x + ox, h + 0.75 * s, y + oz, s, s * 1.3, s, vary(tc.forest, 0.2, x, y, 17 + i));
        } else if (v.el === 'fire') {             // charred, thin
          place(trunks, x + ox, h + 0.35 * s, y + oz, 0.7, s * 1.1, 0.7, null);
          place(canopy2, x + ox, h + 0.9 * s, y + oz, s * 0.8, s * 0.7, s * 0.8, vary(col('#6b6b3a'), 0.3, x, y, 19 + i));
        } else {
          place(trunks, x + ox, h + 0.3 * s, y + oz, 1, s, 1, null);
          place(canopy1, x + ox, h + 0.75 * s, y + oz, s, s * 1.1, s, vary(tc.forest, 0.25, x, y, 17 + i));
          place(canopy2, x + ox + 0.05, h + 1.15 * s, y + oz - 0.05, s, s, s, vary(tc.forest.clone().offsetHSL(0, 0, 0.08), 0.25, x, y, 19 + i));
        }
      }
    } else if (t === T.ROCK || t === T.SNOW) {
      if (h > 2.2 || t === T.SNOW) place(snowcap, px, h + 0.08, pz, 0.7 + (t === T.SNOW ? 0.3 : 0), 0.16, 0.7 + (t === T.SNOW ? 0.3 : 0), null);
      if (rnd(x, y, 21) > 0.5) place(pebbles, x + 0.3 + rnd(x, y, 22) * 0.4, h + 0.08, y + 0.3 + rnd(x, y, 23) * 0.4, 1, 1, 1, vary(tc.rock, 0.2, x, y, 24));
    } else if (t === T.RUIN) {
      for (let i = 0; i < 3; i++) place(rubble, x + 0.2 + rnd(x, y, 60 + i) * 0.6, h + 0.1, y + 0.2 + rnd(x, y, 70 + i) * 0.6, 1 + rnd(x, y, 80 + i), 0.8, 1, vary(col('#7a716a'), 0.3, x, y, 90 + i));
    } else if (t === T.ASH && rnd(x, y, 25) > 0.7) {
      place(pebbles, x + 0.2 + rnd(x, y, 26) * 0.6, h + 0.05, y + 0.2 + rnd(x, y, 27) * 0.6, 0.7, 0.6, 0.7, col('#2a2422'));
    } else if (t === T.GRASS && rnd(x, y, 25) > 0.82) {
      place(pebbles, x + 0.2 + rnd(x, y, 26) * 0.6, h + 0.05, y + 0.2 + rnd(x, y, 27) * 0.6, 0.6, 0.5, 0.6, vary(col('#7c8c6a'), 0.2, x, y, 28));
    }
  }
  [ground, water, lava, rows, wheat, trunks, canopy1, canopy2, pines, snowcap, pebbles, rubble, damWall].forEach(finish);
}
let gridVersion = D.gv;
buildTerrain();

// ---------------------------------------------------------------- buildings
const STYLE = {
  ancient:    { roof: 'flat', smoke: 0.5 }, medieval: { roof: 'pyramid', smoke: 1 }, industrial: { roof: 'pyramid', smoke: 1.6 },
  modern:     { roof: 'flat', smoke: 0.2 }, future: { roof: 'dome', smoke: 0 },
};
const ST = STYLE[D.style] || STYLE.medieval;
const PALETTE = {   // walls / roofs per element
  sky:   { walls: ['#d6dbe0', '#c4ccd3', '#e1e5ea'], roofs: ['#4b5f78', '#3e4f63', '#5a6f8a'] },
  air:   { walls: ['#f1ebdd', '#e8e0cc', '#f6f1e6'], roofs: ['#7fb3c9', '#6aa0b8', '#9cc7d8'] },
  earth: { walls: ['#cdb48c', '#bfa47a', '#d7c29e'], roofs: ['#4d6a4a', '#5e7b3f', '#6d4a34'] },
  fire:  { walls: ['#4a3b36', '#5a4640', '#3d302c'], roofs: ['#b8452f', '#9e3a26', '#d0552f'] },
  water: { walls: ['#f2f2ee', '#e6ecef', '#dfe8ea'], roofs: ['#2e6fa8', '#3a86c0', '#28628f'] },
};
const walls = instanced(box, mat('#ffffff'), 900);
const roofs = instanced(ST.roof === 'dome' ? new THREE.SphereGeometry(0.42, 12, 8, 0, Math.PI * 2, 0, Math.PI / 2) : (ST.roof === 'flat' ? new THREE.BoxGeometry(1.08, 0.12, 1.08) : new THREE.ConeGeometry(0.72, 0.5, 4)),
                        mat('#ffffff', { flatShading: ST.roof === 'pyramid' }), 900);
const chimneys = instanced(box, mat('#5a5651'), 900), doors = instanced(box, mat('#3a2a1a'), 900), windows = instanced(box, new THREE.MeshStandardMaterial({ color: '#ffd98a', emissive: '#ffb347', emissiveIntensity: 0 }), 1800);
const built = new THREE.Group(); scene.add(built);
const labels = new THREE.Group(); scene.add(labels);
const bigLabels = new THREE.Group(); scene.add(bigLabels);
const smokeSources = [];
let buildKey = "";

function textSprite(text, size = 28, bg = 'rgba(12,16,24,0.85)', fg = '#eef2f7') {
  const c = document.createElement('canvas'); const ctx = c.getContext('2d');
  ctx.font = `600 ${size}px system-ui, sans-serif`; const w = ctx.measureText(text).width + size; c.width = w; c.height = size * 1.6;
  ctx.font = `600 ${size}px system-ui, sans-serif`; ctx.fillStyle = bg; ctx.beginPath(); ctx.roundRect(0, 0, w, size * 1.6, size * 0.36); ctx.fill();
  ctx.fillStyle = fg; ctx.textBaseline = 'middle'; ctx.fillText(text, size / 2, size * 0.83);
  const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace;
  const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthTest: false, transparent: true }));
  sp.scale.set(w / (size * 1.6) * 0.75, 0.75, 1); return sp;
}
const ICON = { farm: '🌾', bakery: '🥖', workshop: '⚒️', market: '🏪', mine: '⛏️', tavern: '🍺', school: '🏫', clinic: '🏥' };
const bmeshes = [];
function addBox(g, x, y, z, sx, sy, sz, color, extra = {}) { const m = new THREE.Mesh(box, mat(color, extra)); m.position.set(x, y, z); m.scale.set(sx, sy, sz); m.castShadow = m.receiveShadow = true; g.add(m); return m; }
function gable(g, x, y, z, sx, sy, sz, color, ry = 0) { const m = new THREE.Mesh(new THREE.ConeGeometry(0.71, 1, 4), mat(color, { flatShading: true })); m.position.set(x, y, z); m.rotation.y = Math.PI / 4 + ry; m.scale.set(sx, sy, sz); m.castShadow = true; g.add(m); return m; }
function business(b) {
  const g = new THREE.Group(); const x = b.x + 0.5, z = b.y + 0.5, base = heightAt(b.x, b.y);
  const k = b.kind, pal = PALETTE[(D.villages[b.v] || D.villages[0]).el] || PALETTE.earth, roofC = pal.roofs[0];
  if (k === 'farm') { addBox(g, x, base + 0.5, z, 1.3, 1.0, 0.95, '#a23b34'); gable(g, x, base + 1.35, z, 1.05, 0.7, 0.8, '#5c2a25'); addBox(g, x + 0.85, base + 0.7, z - 0.2, 0.35, 1.4, 0.35, '#c9c3b6'); }
  else if (k === 'mine') { addBox(g, x, base + 0.6, z, 1.1, 1.2, 1.0, '#6e6e6a'); addBox(g, x, base + 0.35, z + 0.52, 0.5, 0.7, 0.08, '#111'); addBox(g, x - 0.35, base + 0.5, z + 0.58, 0.08, 1.0, 0.08, '#7a5230'); addBox(g, x + 0.35, base + 0.5, z + 0.58, 0.08, 1.0, 0.08, '#7a5230'); addBox(g, x, base + 1.0, z + 0.58, 0.85, 0.08, 0.08, '#7a5230'); addBox(g, x + 0.7, base + 0.2, z + 0.6, 0.4, 0.25, 0.3, '#3b3b3b'); }
  else if (k === 'market') { addBox(g, x, base + 0.35, z, 1.2, 0.7, 0.9, pal.walls[0]); for (let i = 0; i < 5; i++) addBox(g, x - 0.5 + i * 0.25, base + 0.78, z + 0.55, 0.25, 0.06, 0.4, i % 2 ? '#e8e2d6' : roofC); }
  else if (k === 'tavern') { addBox(g, x, base + 0.55, z, 1.0, 1.1, 0.9, '#8a5a2b'); gable(g, x, base + 1.4, z, 0.85, 0.7, 0.75, '#3d2416'); addBox(g, x + 0.62, base + 0.72, z + 0.5, 0.05, 0.3, 0.3, '#d9a441', { emissive: '#d9a441', emissiveIntensity: 0.35 }); smokeSources.push([x - 0.3, base + 1.9, z - 0.2]); }
  else if (k === 'school') { addBox(g, x, base + 0.55, z, 1.1, 1.1, 0.9, pal.walls[2]); gable(g, x, base + 1.4, z, 0.9, 0.7, 0.75, roofC); addBox(g, x, base + 1.85, z, 0.3, 0.5, 0.3, pal.walls[2]); }
  else if (k === 'clinic') { addBox(g, x, base + 0.5, z, 1.1, 1.0, 0.9, '#f7f7f5'); addBox(g, x, base + 1.05, z, 1.15, 0.1, 0.95, '#c94a4a'); addBox(g, x, base + 0.75, z + 0.47, 0.12, 0.4, 0.04, '#c94a4a'); addBox(g, x, base + 0.75, z + 0.47, 0.4, 0.12, 0.04, '#c94a4a'); }
  else if (k === 'workshop') { addBox(g, x, base + 0.55, z, 1.1, 1.1, 0.9, '#5c4028'); gable(g, x, base + 1.4, z, 0.9, 0.6, 0.75, '#2d2118'); addBox(g, x + 0.35, base + 1.5, z - 0.2, 0.2, 0.9, 0.2, '#4a4642'); smokeSources.push([x + 0.35, base + 2.0, z - 0.2]); }
  else { addBox(g, x, base + 0.5, z, 1.0, 1.0, 0.9, pal.walls[1]); gable(g, x, base + 1.35, z, 0.85, 0.7, 0.75, roofC); smokeSources.push([x - 0.3, base + 1.9, z - 0.2]); }
  g.userData = { kind: 'business', b };
  const label = textSprite(`${ICON[k] || ''} ${b.name}`); label.position.set(x, base + 2.9, z); label.userData.v = b.v; labels.add(label);
  built.add(g); g.traverse(m => { if (m.isMesh) { m.userData.b = b; bmeshes.push(m); } });
}
function villageMarkers() {
  bigLabels.clear();
  for (const v of D.villages) {
    const [x, z] = [v.centre[0] + 0.5, v.centre[1] + 0.5];
    const state = v.fallen ? ' — ruins' : (v.occ !== null && v.occ !== undefined ? ` — held by ${D.villages[v.occ].name}` : '');
    const l = textSprite(`${v.name}${state}`, 44, 'rgba(10,14,22,0.7)', v.col); l.position.set(x, 6.2, z); l.scale.multiplyScalar(2.2); bigLabels.add(l);
    // the banner in the square: the village's colour, or the occupier's
    const flagCol = v.occ !== null && v.occ !== undefined ? D.villages[v.occ].col : v.col;
    const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.04, 0.05, 3, 6), mat('#5a4632')); pole.position.set(x, 2, z); pole.castShadow = true; bigLabels.add(pole);
    const flag = new THREE.Mesh(new THREE.PlaneGeometry(0.9, 0.55), new THREE.MeshStandardMaterial({ color: v.fallen ? '#222' : flagCol, side: THREE.DoubleSide, emissive: flagCol, emissiveIntensity: 0.15 }));
    flag.position.set(x + 0.47, 3.2, z); flag.userData.flag = true; bigLabels.add(flag);
  }
}
function buildStructures() {
  const key = D.buildings.map(b => b.x + ',' + b.y + b.kind).join('|') + '#' + D.homes.length + '#' + D.villages.map(v => `${v.occ}${v.fallen}`).join('');
  if (key === buildKey) return; buildKey = key;
  built.clear(); labels.clear(); bmeshes.length = 0; smokeSources.length = 0;
  walls.count = roofs.count = chimneys.count = doors.count = windows.count = 0;
  const taken = new Set(D.buildings.map(b => b.x + ',' + b.y));
  D.buildings.forEach(business);
  D.homes.forEach(([x, y]) => {
    const t = D.grid[y][x];
    if (taken.has(x + ',' + y) || t === T.WATER || t === T.LAVA || t === T.RUIN) return;
    const pal = PALETTE[regionOf(x, y).el] || PALETTE.earth;
    const px = x + 0.5, pz = y + 0.5, base = heightAt(x, y), s = 0.55 + rnd(x, y, 31) * 0.15, ry = Math.floor(rnd(x, y, 32) * 4) * Math.PI / 2;
    const tall = D.style === 'modern' || D.style === 'future' ? 0.64 + rnd(x, y, 37) * 0.5 : 0.64;
    place(walls, px, base + tall / 2, pz, s, tall, s, col(pal.walls[Math.floor(rnd(x, y, 33) * pal.walls.length)]), ry);
    const rc = col(pal.roofs[Math.floor(rnd(x, y, 34) * pal.roofs.length)]);
    if (ST.roof === 'pyramid') place(roofs, px, base + tall + 0.24, pz, s * 1.05, 0.5, s * 1.05, rc, Math.PI / 4 + ry);
    else if (ST.roof === 'flat') place(roofs, px, base + tall + 0.05, pz, s, 1, s, rc, ry);
    else place(roofs, px, base + tall, pz, s * 1.2, s * 1.2, s * 1.2, rc, ry);
    if (ST.smoke > 0 && rnd(x, y, 35) > 0.4) { place(chimneys, px + 0.18 * s, base + tall + 0.2, pz - 0.12 * s, 0.1, 0.35, 0.1, null); if (rnd(x, y, 36) * 1.6 < ST.smoke) smokeSources.push([px + 0.18 * s, base + tall + 0.4, pz - 0.12 * s]); }
    place(doors, px, base + 0.15, pz + s / 2 + 0.01, 0.14, 0.3, 0.03, null, ry);
    place(windows, px - 0.16 * s, base + 0.4, pz + s / 2 + 0.01, 0.12, 0.12, 0.03, null, ry);
    place(windows, px + 0.16 * s, base + 0.4, pz + s / 2 + 0.01, 0.12, 0.12, 0.03, null, ry);
  });
  [walls, roofs, chimneys, doors, windows].forEach(finish);
  villageMarkers();
  buildHerds();
}

// ---------------------------------------------------------------- models
const loader = new GLTFLoader();
const LIB = {};                   // name -> {scene, clips, height}
const HEIGHT = { human: 0.24, cow: 0.17, horse: 0.22, deer: 0.19, stag: 0.23, wolf: 0.12, husky: 0.1, fox: 0.07, alpaca: 0.16, sheep: 0.11,
                 bear: 0.19, tiger: 0.14, lion: 0.15, elephant: 0.36, eagle: 0.12 };
function loadModel(name) {
  return new Promise(res => loader.load(`${MODELS}${name}.glb`, g => {
    const bb = new THREE.Box3().setFromObject(g.scene), size = bb.getSize(new THREE.Vector3());
    const s = HEIGHT[name] / Math.max(0.001, name === 'eagle' ? size.x : size.y);
    g.scene.traverse(o => { if (o.isMesh) { o.castShadow = true; o.receiveShadow = false; o.frustumCulled = false; } });
    LIB[name] = { scene: g.scene, clips: g.animations, scale: s, lift: -bb.min.y * s };
    res(LIB[name]);
  }, undefined, () => res(null)));
}
if (MODELS) {
  loadModel('human').then(() => { for (const n of ['cow', 'horse', 'deer', 'stag', 'wolf', 'husky', 'fox', 'alpaca', 'sheep', 'bear', 'tiger', 'lion', 'elephant', 'eagle']) loadModel(n); });
}
const tintCache = new Map();
function tinted(m, hex, name) {
  const key = m.uuid + hex + name; if (tintCache.has(key)) return tintCache.get(key);
  const c = m.clone(); c.color = col(hex); tintCache.set(key, c); return c;
}
function makeActor(name, tint) {
  const lib = LIB[name]; if (!lib) return null;
  const root = new THREE.Group();
  const obj = SkeletonUtils.clone(lib.scene); obj.scale.setScalar(lib.scale); obj.position.y = lib.lift; root.add(obj);
  if (tint) obj.traverse(o => { if (o.isMesh && o.material) {
    const ms = Array.isArray(o.material) ? o.material : [o.material];
    const out = ms.map(mm => (mm.name === 'M_Main' || mm.name === 'Main' || ms.length === 1) ? tinted(mm, tint, name) : mm);
    o.material = Array.isArray(o.material) ? out : out[0];
  } });
  const mixer = lib.clips.length ? new THREE.AnimationMixer(obj) : null;
  scene.add(root);
  return { root, obj, mixer, clips: lib.clips, current: null, name };
}
function play(a, names, speed = 1) {
  if (!a || !a.mixer) return;
  const clip = names.map(n => a.clips.find(c => c.name === n)).find(Boolean);
  if (!clip || a.current === clip.name) return;
  const act = a.mixer.clipAction(clip); act.reset(); act.timeScale = speed; act.fadeIn(0.25).play();
  if (a.currentAction) a.currentAction.fadeOut(0.25);
  if (clip.name.startsWith('Death')) { act.setLoop(THREE.LoopOnce, 1); act.clampWhenFinished = true; }
  a.currentAction = act; a.current = clip.name;
}
function drop(a) { if (a) { scene.remove(a.root); a.mixer && a.mixer.stopAllAction(); } }

// ---------------------------------------------------------------- people: rigged figures near the camera, instanced figures far away
const MAXC = 2500, NEAR = 60;
const bodies = instanced(new THREE.CapsuleGeometry(0.045, 0.09, 3, 8), mat('#ffffff', { roughness: 0.7 }), MAXC);
const heads = instanced(new THREE.SphereGeometry(0.04, 10, 8), mat('#f2c9a0'), MAXC);
const rings = instanced(new THREE.TorusGeometry(0.13, 0.016, 8, 24), new THREE.MeshBasicMaterial({ color: '#ffffff' }), 64);
rings.castShadow = false;
const people = new Map();
const EMOJI = { anger: '💢', fear: '😨', grief: '😢', joy: '😊', shame: '😳', pride: '😤', envy: '😒', hope: '✨', love: '❤️' };
const emojiTex = {};
function emojiSprite(e) {
  if (!emojiTex[e]) { const c = document.createElement('canvas'); c.width = c.height = 64; const x = c.getContext('2d'); x.font = '48px serif'; x.textAlign = 'center'; x.textBaseline = 'middle'; x.fillText(e, 32, 36); emojiTex[e] = new THREE.CanvasTexture(c); }
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: emojiTex[e], depthTest: false, transparent: true })); s.scale.set(0.16, 0.16, 1); return s;
}
function tileTop(x, y) { return heightAt(Math.floor(x), Math.floor(y)); }
function setCitizens(list, now) {
  const seen = new Set();
  list.forEach(c => {
    seen.add(c.id);
    const ox = 0.3 + 0.4 * rnd(c.id, 1, 1), oz = 0.3 + 0.4 * rnd(c.id, 2, 2);
    const to = [c.x + ox, c.y + oz];
    let p = people.get(c.id);
    if (!p) { p = { from: to, to, t0: now - 5000, id: c.id, idle: 0, wanderT: now + Math.random() * 4000 }; people.set(c.id, p); }
    else if (Math.hypot(p.to[0] - to[0], p.to[1] - to[1]) > 0.01) { p.from = p.cur || p.to; p.to = to; p.t0 = now; p.home = to; }
    p.home = p.home || to;
    Object.assign(p, { name: c.name, job: c.job, age: c.age, inf: c.inf, sel: c.sel, colHex: c.col, col: col(c.col), child: c.job === 'child',
                       v: c.v, role: c.role, jail: c.jail, emo: c.emo, mage: c.mage, sex: c.sex });
  });
  for (const id of [...people.keys()]) if (!seen.has(id)) { const p = people.get(id); drop(p.actor); if (p.bubble) scene.remove(p.bubble); people.delete(id); }
}
setCitizens(D.citizens, performance.now());
const hoverList = [];
let fightZones = [];         // [x, z, r] battles, riots, brawls: people there fight
function nearFight(x, z) { return fightZones.some(f => Math.hypot(f[0] - x, f[1] - z) < f[2]); }
function animatePeople(now, dt) {
  bodies.count = heads.count = rings.count = 0; hoverList.length = 0;
  const tx = controls.target.x, tz = controls.target.z;
  // who is close enough to deserve a full figure
  const ranked = [];
  for (const p of people.values()) {
    const k = Math.min(1, (now - p.t0) / 2200), e = k * k * (3 - 2 * k);
    let x = p.from[0] + (p.to[0] - p.from[0]) * e, z = p.from[1] + (p.to[1] - p.from[1]) * e;
    // between days nobody stands still: small wanders around where they are
    if (k >= 1 && !p.jail) {
      if (!p.wander || now > p.wanderT) { const a = rnd(p.id, now | 0, 3) * 6.28, r = 0.15 + rnd(p.id, now | 0, 4) * 0.5; p.wander = { fx: p.wx ?? x, fz: p.wz ?? z, tx: p.to[0] + Math.cos(a) * r, tz: p.to[1] + Math.sin(a) * r, t0: now }; p.wanderT = now + 3500 + rnd(p.id, 5, now | 0) * 6000; }
      const w = p.wander, q = Math.min(1, (now - w.t0) / 1800); x = w.fx + (w.tx - w.fx) * q; z = w.fz + (w.tz - w.fz) * q; p.wx = x; p.wz = z;
      p.moving = q < 1; p.dir = Math.atan2(w.tx - w.fx, w.tz - w.fz);
    } else { p.moving = k < 1; p.dir = Math.atan2(p.to[0] - p.from[0], p.to[1] - p.from[1]); p.wx = x; p.wz = z; }
    p.cur = [x, z]; p.d = Math.hypot(x - tx, z - tz);
    ranked.push(p);
  }
  ranked.sort((a, b) => a.d - b.d);
  const figures = LIB.human ? NEAR : 0;
  ranked.forEach((p, i) => {
    const [x, z] = p.cur, y = tileTop(x, z), s = p.child ? 0.7 : 1;
    const near = i < figures && p.d < 30;
    if (near) {
      if (!p.actor) { p.actor = makeActor('human', p.colHex); }
      const a = p.actor; a.root.visible = true;
      a.root.position.set(x, y, z); a.root.scale.setScalar(s); a.root.rotation.y = p.moving ? p.dir : (p.face ?? (p.face = rnd(p.id, 7, 7) * 6.28));
      // what they are doing, in body language
      const fight = nearFight(x, z);
      let clip;
      if (p.jail) clip = ['Sitting_Idle_Loop'];
      else if (fight && (p.role === 'guard' || p.emo === 'anger' || rnd(p.id, 9, 9) > 0.4)) clip = p.mage ? ['Spell_Simple_Shoot'] : (p.role === 'guard' ? ['Sword_Attack'] : ['Punch_Cross', 'Punch_Jab']);
      else if (p.moving) clip = (p.emo === 'fear' || fight) ? ['Sprint_Loop'] : (p.role === 'councillor' ? ['Walk_Formal_Loop'] : ['Walk_Loop']);
      else if (p.emo === 'joy' || p.emo === 'love') clip = ['Dance_Loop'];
      else if (p.emo === 'grief' || p.emo === 'shame') clip = ['Crouch_Idle_Loop'];
      else if (p.emo === 'anger') clip = ['Punch_Jab'];
      else if (p.mage && rnd(p.id, now / 20000 | 0, 1) > 0.8) clip = ['Spell_Simple_Idle_Loop'];
      else if (p.job === 'farmer' || p.job === 'miner') clip = ['Fixing_Kneeling', 'PickUp_Table'];
      else if (p.job === 'merchant' || p.job === 'innkeeper' || p.role === 'councillor') clip = ['Idle_Talking_Loop'];
      else if (p.job === 'craftsperson' || p.job === 'baker') clip = ['Interact', 'PickUp_Table'];
      else if (p.role === 'guard' || p.role === 'police') clip = ['Sword_Idle', 'Idle_Torch_Loop'];
      else clip = rnd(p.id, now / 15000 | 0, 2) > 0.5 ? ['Idle_Talking_Loop'] : ['Idle_Loop'];
      play(a, clip, p.moving ? 1.0 : 0.9 + rnd(p.id, 1, 3) * 0.2);
      a.mixer && a.mixer.update(dt);
      // a feeling floats over their head
      if (p.emo && EMOJI[p.emo] && p.d < 16) { if (!p.bubble || p.bubbleE !== p.emo) { if (p.bubble) scene.remove(p.bubble); p.bubble = emojiSprite(EMOJI[p.emo]); p.bubbleE = p.emo; scene.add(p.bubble); } p.bubble.visible = true; p.bubble.position.set(x, y + 0.38 * s + Math.sin(now / 300 + p.id) * 0.015, z); }
      else if (p.bubble) p.bubble.visible = false;
    } else {
      if (p.actor) { p.actor.root.visible = false; }
      if (p.bubble) p.bubble.visible = false;
      const bob = p.moving ? Math.abs(Math.sin(now / 90 + p.id)) * 0.025 : 0;
      place(bodies, x, y + 0.09 * s + bob, z, s, s, s, p.col, p.dir || 0);
      place(heads, x, y + 0.2 * s + bob, z, s, s, s, null, p.dir || 0);
    }
    if (p.sel) { dummy.position.set(x, y + 0.03, z); dummy.rotation.set(Math.PI / 2, 0, 0); dummy.scale.set(1, 1, 1); dummy.updateMatrix(); rings.setMatrixAt(rings.count, dummy.matrix); rings.setColorAt(rings.count, col('#ffd43b')); rings.count++; }
    else if (p.inf) { dummy.position.set(x, y + 0.03, z); dummy.rotation.set(Math.PI / 2, 0, 0); dummy.scale.set(0.8, 0.8, 0.8); dummy.updateMatrix(); rings.setMatrixAt(rings.count, dummy.matrix); rings.setColorAt(rings.count, col('#ff5252')); rings.count++; }
    hoverList.push([x, y + 0.14, z, p]);
  });
  // free figures of people who wandered far off (keep memory bounded)
  for (const p of ranked.slice(figures + 30)) if (p.actor) { drop(p.actor); p.actor = null; }
  [bodies, heads, rings].forEach(finish);
}

// ---------------------------------------------------------------- animals: the realm's (animated models) and the farms' herds (cheap)
const SPECIES_MODEL = { dog: ['husky', null], cat: ['fox', '#8a8a8a'], horse: ['horse', null], cow: ['cow', null], sheep: ['sheep', null],
                        goat: ['alpaca', '#8b6b4a'], elephant: ['elephant', null], deer: ['deer', null], bird: ['eagle', null], wolf: ['wolf', null],
                        bear: ['bear', null], tiger: ['tiger', null], lion: ['lion', null] };
const beasts = new Map();
function setAnimals(list, now) {
  const seen = new Set();
  (list || []).forEach(a => {
    seen.add(a.id);
    const to = [a.x + 0.5 + (rnd(a.id, 1, 2) - 0.5) * 0.6, a.y + 0.5 + (rnd(a.id, 2, 1) - 0.5) * 0.6];
    let b = beasts.get(a.id);
    if (!b) { b = { from: to, to, t0: now - 5000, id: a.id }; beasts.set(a.id, b); }
    else if (Math.hypot(b.to[0] - to[0], b.to[1] - to[1]) > 0.01) { b.from = b.cur || b.to; b.to = to; b.t0 = now; }
    Object.assign(b, { sp: a.sp, name: a.name, doing: a.doing, wild: a.wild, sel: a.sel });
  });
  for (const id of [...beasts.keys()]) if (!seen.has(id)) { const b = beasts.get(id); if (b.actor) { play(b.actor, ['Death']); const r = b.actor; setTimeout(() => drop(r), 2500); } beasts.delete(id); }
}
setAnimals(D.animals, performance.now());
const fallbackBeast = instanced(new THREE.BoxGeometry(0.16, 0.1, 0.08), mat('#7a5a3a'), 400);
function animateBeasts(now, dt) {
  fallbackBeast.count = 0;
  for (const b of beasts.values()) {
    const k = Math.min(1, (now - b.t0) / 3000), e = k * k * (3 - 2 * k);
    let x = b.from[0] + (b.to[0] - b.from[0]) * e, z = b.from[1] + (b.to[1] - b.from[1]) * e;
    const moving = k < 1, dir = Math.atan2(b.to[0] - b.from[0], b.to[1] - b.from[1]);
    if (!moving) { x += Math.sin(now / 2400 + b.id) * 0.25; z += Math.cos(now / 2900 + b.id) * 0.25; }
    b.cur = [x, z];
    const [model, tint] = SPECIES_MODEL[b.sp] || ['deer', null];
    const fly = model === 'eagle';
    const y = fly ? 5 + Math.sin(now / 900 + b.id) * 0.6 : tileTop(x, z);
    if (LIB[model]) {
      if (!b.actor) b.actor = makeActor(model, tint);
      const a = b.actor;
      if (fly) { const ang = now / 4000 + b.id; a.root.position.set(x + Math.cos(ang) * 3, y, z + Math.sin(ang) * 3); a.root.rotation.set(0, -ang, 0.3); }
      else {
        a.root.position.set(x, y + (a.mixer ? 0 : (moving ? Math.abs(Math.sin(now / 120)) * 0.04 : 0)), z);
        a.root.rotation.y = moving ? dir : (b.face ?? (b.face = rnd(b.id, 3, 3) * 6.28));
        const doing = b.doing || '';
        play(a, doing.includes('prowl') ? ['Walk'] : (moving ? (b.wild && doing.includes('flee') ? ['Gallop', 'Run'] : ['Walk']) :
             (doing.includes('graz') ? ['Eating', 'Idle_Eating', 'Idle'] : (doing.includes('fight') || doing.includes('growl') ? ['Attack', 'Attack_Headbutt', 'Headbutt'] : ['Idle', 'Idle_2']))));
      }
      a.mixer && a.mixer.update(dt);
    } else if (!fly) place(fallbackBeast, x, y + 0.06, z, 1, 1, 1, null, dir);
    if (b.sel) { dummy.position.set(x, y + 0.03, z); dummy.rotation.set(Math.PI / 2, 0, 0); dummy.scale.set(1, 1, 1); dummy.updateMatrix(); rings.setMatrixAt(rings.count, dummy.matrix); rings.setColorAt(rings.count, col('#ffd43b')); rings.count++; }
    hoverList.push([x, y + 0.1, z, { name: b.name, job: b.sp, age: '', inf: false, animal: true, doing: b.doing }]);
  }
  finish(fallbackBeast); finish(rings);
}
// farm herds: decoration, cheap instanced shapes
const cowBody = instanced(new THREE.BoxGeometry(0.2, 0.12, 0.11), mat('#7a4b2a'), 300), cowHead = instanced(new THREE.BoxGeometry(0.08, 0.08, 0.08), mat('#5c3a20'), 300);
let herds = [];
function landOk(x, z) { const gx = Math.floor(x), gz = Math.floor(z); if (gx < 0 || gz < 0 || gx >= W || gz >= H) return false; const t = D.grid[gz][gx]; return t !== T.WATER && t !== T.ROCK && t !== T.LAVA && t !== T.SNOW; }
function buildHerds() {
  herds = [];
  D.buildings.filter(b => b.kind === 'farm').forEach(b => { for (let i = 0; i < Math.min(8, b.herd || 0); i++) {
    for (let tries = 0; tries < 10; tries++) { const x = b.x + 0.5 + (Math.random() - 0.5) * 5, z = b.y + 0.5 + (Math.random() - 0.5) * 5; if (landOk(x, z)) { herds.push({ x, z, tx: x, tz: z, ax: b.x + 0.5, az: b.y + 0.5, wait: Math.random() * 3, face: 0 }); break; } } } });
}
function animateHerds(dt, now) {
  cowBody.count = cowHead.count = 0;
  for (const a of herds) {
    if (a.wait > 0) a.wait -= dt;
    else { const dx = a.tx - a.x, dz = a.tz - a.z, d = Math.hypot(dx, dz);
      if (d < 0.05) { a.wait = 1 + Math.random() * 4; for (let t = 0; t < 8; t++) { const nx = a.ax + (Math.random() - 0.5) * 5, nz = a.az + (Math.random() - 0.5) * 5; if (landOk(nx, nz)) { a.tx = nx; a.tz = nz; break; } } }
      else { const st = Math.min(d, 0.25 * dt); a.x += dx / d * st; a.z += dz / d * st; a.face = Math.atan2(dx, dz); } }
    const y = tileTop(a.x, a.z);
    place(cowBody, a.x, y + 0.09, a.z, 1, 1, 1, null, a.face); place(cowHead, a.x + Math.sin(a.face) * 0.12, y + 0.12, a.z + Math.cos(a.face) * 0.12, 1, 1, 1, null, a.face);
  }
  finish(cowBody); finish(cowHead);
}

// ---------------------------------------------------------------- effects: what gods, wars and mages do to the world
const fxLayer = new THREE.Group(); scene.add(fxLayer);
const live = new Map();       // fx key -> effect object
const particles = [];         // {mesh, vel, life, age, grav, fade}
const sparkGeo = new THREE.SphereGeometry(0.06, 6, 4);
function burst(x, y, z, n, color, speed = 2, life = 1.2, size = 1, grav = -3) {
  const m = new THREE.MeshBasicMaterial({ color, transparent: true });
  for (let i = 0; i < n; i++) {
    const s = new THREE.Mesh(sparkGeo, m.clone()); s.position.set(x, y, z); s.scale.setScalar(size * (0.5 + Math.random()));
    const a = Math.random() * 6.28, u = Math.random();
    particles.push({ mesh: s, vel: new THREE.Vector3(Math.cos(a) * speed * u, speed * (0.5 + Math.random()), Math.sin(a) * speed * u), life, age: 0, grav });
    fxLayer.add(s);
  }
}
function smokePuff(x, y, z, n = 6, color = '#555', size = 3) {
  for (let i = 0; i < n; i++) {
    const s = new THREE.Mesh(new THREE.SphereGeometry(0.2, 8, 6), new THREE.MeshStandardMaterial({ color, transparent: true, opacity: 0.55, depthWrite: false }));
    s.position.set(x + (Math.random() - 0.5) * 0.6, y, z + (Math.random() - 0.5) * 0.6);
    particles.push({ mesh: s, vel: new THREE.Vector3((Math.random() - 0.5) * 0.3, 0.6 + Math.random() * 0.4, (Math.random() - 0.5) * 0.3), life: 3 + Math.random() * 2, age: 0, grav: 0, grow: size });
    fxLayer.add(s);
  }
}
function tickParticles(dt) {
  for (let i = particles.length - 1; i >= 0; i--) {
    const p = particles[i]; p.age += dt;
    p.vel.y += p.grav * dt; p.mesh.position.addScaledVector(p.vel, dt);
    const k = p.age / p.life;
    if (p.grow) p.mesh.scale.setScalar(1 + k * p.grow);
    if (p.mesh.material) p.mesh.material.opacity = Math.max(0, (p.grow ? 0.55 : 1) * (1 - k));
    if (p.light) p.mesh.intensity = p.light * Math.max(0, 1 - k);
    if (k >= 1) { fxLayer.remove(p.mesh); particles.splice(i, 1); }
  }
}
function flash(x, y, z, color, intensity = 30, dist = 12, life = 0.5) {
  const l = new THREE.PointLight(color, intensity, dist); l.position.set(x, y, z); fxLayer.add(l);
  particles.push({ mesh: l, vel: new THREE.Vector3(), life, age: 0, grav: 0, light: intensity });
}
let shake = 0;
const FX = {
  meteor(f, t) {         // a burning stone falls out of the sky and hits
    const o = { t0: t + (f.delay || 0) * 1000, x: f.x + 0.5, z: f.y + 0.5, hit: false };
    o.rock = new THREE.Mesh(new THREE.DodecahedronGeometry(0.35, 0), new THREE.MeshStandardMaterial({ color: '#3a2a20', emissive: '#ff6a1a', emissiveIntensity: 1.5 }));
    o.trail = new THREE.PointLight('#ff7a2a', 25, 14); o.rock.add(o.trail); fxLayer.add(o.rock); o.rock.visible = false;
    o.update = (now) => {
      const k = (now - o.t0) / 1600; if (k < 0) return true;
      if (k < 1) { o.rock.visible = true; o.rock.position.set(o.x - 18 * (1 - k), 0.5 + 30 * (1 - k), o.z - 8 * (1 - k)); o.rock.rotation.x += 0.2;
                   if (Math.random() < 0.8) burst(o.rock.position.x, o.rock.position.y, o.rock.position.z, 2, '#ffb347', 0.4, 0.6, 1.2, 0); return true; }
      if (!o.hit) { o.hit = true; fxLayer.remove(o.rock); burst(o.x, 0.8, o.z, 40, '#ff8a3a', 5, 1.4, 1.6); smokePuff(o.x, 0.8, o.z, 10, '#3d3530', 4); flash(o.x, 2, o.z, '#ffae42', 80, 20, 0.8); shake = 0.6; }
      return k < 6;
    };
    return o;
  },
  fire(f) {
    const o = { x: f.x + 0.5, z: f.y + 0.5 }; o.light = new THREE.PointLight('#ff6a1a', 12, 7); o.light.position.set(o.x, 1.4, o.z); fxLayer.add(o.light);
    o.update = (now) => { o.light.intensity = 10 + Math.sin(now / 60) * 4 + Math.random() * 3;
      if (Math.random() < 0.6) burst(o.x + (Math.random() - 0.5) * 0.8, 0.7, o.z + (Math.random() - 0.5) * 0.8, 2, Math.random() < 0.5 ? '#ff6a1a' : '#ffd24a', 0.8, 0.9, 1.3, 1.5);
      if (Math.random() < 0.08) smokePuff(o.x, 1.6, o.z, 1, '#2b2522', 3); return true; };
    o.remove = () => fxLayer.remove(o.light);
    return o;
  },
  lightning(f, t) {
    const o = { t0: t + (f.delay || 0) * 1000, x: f.x + 0.5, z: f.y + 0.5, done: false };
    o.update = (now) => {
      if (now < o.t0) return true;
      if (!o.done) { o.done = true;
        const pts = []; let px = o.x, py = 25, pz = o.z; while (py > 0.5) { pts.push(new THREE.Vector3(px, py, pz)); py -= 2 + Math.random() * 2; px += (Math.random() - 0.5) * 1.5; pz += (Math.random() - 0.5) * 1.5; } pts.push(new THREE.Vector3(o.x, 0.5, o.z));
        o.bolt = new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineBasicMaterial({ color: '#d8e8ff' })); fxLayer.add(o.bolt);
        flash(o.x, 6, o.z, '#cfe3ff', 200, 40, 0.35); burst(o.x, 0.7, o.z, 16, '#e8f0ff', 3, 0.7, 1, -2); }
      if (now - o.t0 > 350 && o.bolt) { fxLayer.remove(o.bolt); o.bolt = null; }
      return now - o.t0 < 4000;
    };
    return o;
  },
  tornado(f, t) {
    const o = { t0: t, x: f.x + 0.5, z: f.y + 0.5, dx: f.dx || 10 };
    o.cone = new THREE.Mesh(new THREE.ConeGeometry(1.6, 7, 18, 6, true), new THREE.MeshStandardMaterial({ color: '#bfc4c9', transparent: true, opacity: 0.45, side: THREE.DoubleSide, depthWrite: false }));
    o.cone.rotation.x = Math.PI; fxLayer.add(o.cone);
    o.update = (now) => { const k = ((now - o.t0) / 12000) % 1; o.cone.position.set(o.x + o.dx * k, 3.6, o.z + Math.sin(k * 6) * 1.5); o.cone.rotation.y += 0.3;
      if (Math.random() < 0.5) burst(o.cone.position.x, 0.6, o.cone.position.z, 2, '#8b7d6b', 2.5, 1, 1, 0.5); return true; };
    o.remove = () => fxLayer.remove(o.cone);
    return o;
  },
  quake(f, t) {
    const o = { t0: t, x: f.x + 0.5, z: f.y + 0.5 };
    o.update = (now) => { const k = (now - o.t0) / 5000; if (k < 1) { shake = Math.max(shake, 0.35 * (1 - k)); if (Math.random() < 0.3) smokePuff(o.x + (Math.random() - 0.5) * 16, 0.6, o.z + (Math.random() - 0.5) * 12, 1, '#8a7a66', 3); } return k < 1.5; };
    return o;
  },
  flood(f, t) {
    const o = { t0: t, x: f.x + 0.5, z: f.y + 0.5, r: f.radius || 8 };
    o.disc = new THREE.Mesh(new THREE.CircleGeometry(o.r, 40), new THREE.MeshPhysicalMaterial({ color: '#3a86c0', transparent: true, opacity: 0.6, roughness: 0.15 }));
    o.disc.rotation.x = -Math.PI / 2; o.disc.position.set(o.x, 0.2, o.z); fxLayer.add(o.disc);
    o.update = (now) => { const k = Math.min(1, (now - o.t0) / 4000); o.disc.position.y = 0.2 + 0.55 * k + Math.sin(now / 500) * 0.03; return true; };
    o.remove = () => fxLayer.remove(o.disc);
    return o;
  },
  riot(f) { const o = { x: f.x + 0.5, z: f.y + 0.5 }; fightZones.push([o.x, o.z, 4]);
    o.update = () => { if (Math.random() < 0.1) smokePuff(o.x + (Math.random() - 0.5) * 5, 0.8, o.z + (Math.random() - 0.5) * 5, 1, '#3b3431', 2.5);
      if (Math.random() < 0.15) burst(o.x + (Math.random() - 0.5) * 4, 0.8, o.z + (Math.random() - 0.5) * 4, 3, '#ff7a2a', 1.2, 0.8, 1.2, 1); return true; };
    return o; },
  raid(f) { return FX.riot(f); },
  construction(f) { const o = { x: f.x + 0.5, z: f.y + 0.5 }; o.update = () => { if (Math.random() < 0.05) smokePuff(o.x, 0.8, o.z, 1, '#c9b89a', 1.5); return true; }; return o; },
  attack(f) { const o = { x: f.x + 0.5, z: f.y + 0.5, n: 0 }; o.update = () => { if (o.n++ < 3) burst(o.x, 0.6, o.z, 8, '#a33', 1.5, 0.8, 1, -3); return o.n < 200; }; return o; },
  blood(f) { return FX.attack(f); },
  aurora(f, t) {
    const o = { t0: t }; o.band = new THREE.Mesh(new THREE.PlaneGeometry(90, 12, 40, 1), new THREE.MeshBasicMaterial({ color: '#4ff0b0', transparent: true, opacity: 0.25, side: THREE.DoubleSide, depthWrite: false, blending: THREE.AdditiveBlending }));
    o.band.position.set(CX, 24, CZ - 20); o.band.rotation.x = -0.35; fxLayer.add(o.band);
    o.update = (now) => { const p = o.band.geometry.attributes.position; for (let i = 0; i < p.count; i++) p.setZ(i, Math.sin(p.getX(i) / 6 + now / 1200) * 2.5); p.needsUpdate = true; o.band.material.color.setHSL(0.4 + Math.sin(now / 3000) * 0.1, 0.9, 0.6); return true; };
    o.remove = () => fxLayer.remove(o.band);
    return o;
  },
  eclipse(f) { const o = {}; o.update = () => { eclipse = 1; return true; }; o.remove = () => { eclipse = 0; }; return o; },
  battle(f) {          // two armies at the border: banners, campfires, soldiers fighting
    const o = { x: f.x + 0.5, z: f.y + 0.5, soldiers: [], sides: f.sides || [0, 1] };
    fightZones.push([o.x, o.z, 3.5]);
    o.camp = new THREE.Group(); fxLayer.add(o.camp);
    o.sides.forEach((vi, s) => {
      const v = D.villages[vi] || D.villages[0], off = s ? 1 : -1;
      for (let i = 0; i < 2; i++) { const tent = new THREE.Mesh(new THREE.ConeGeometry(0.5, 0.7, 4), mat(v.col)); tent.position.set(o.x + off * (3 + i), 0.85, o.z + (i - 0.5) * 2); tent.castShadow = true; o.camp.add(tent); }
      const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.03, 2, 5), mat('#4a3a2a')); pole.position.set(o.x + off * 2.5, 1.5, o.z); o.camp.add(pole);
      const fl = new THREE.Mesh(new THREE.PlaneGeometry(0.7, 0.4), new THREE.MeshStandardMaterial({ color: v.col, side: THREE.DoubleSide })); fl.position.set(o.x + off * 2.5 + 0.36, 2.3, o.z); o.camp.add(fl);
    });
    o.update = (now, dt) => {
      if (!o.soldiers.length && LIB.human) {
        o.sides.forEach((vi, s) => { const v = D.villages[vi] || D.villages[0];
          for (let i = 0; i < 8; i++) { const a = makeActor('human', v.col); a.root.position.set(o.x + (s ? 0.25 : -0.25) + (Math.random() - 0.5) * 0.3, heightAt(Math.floor(o.x), Math.floor(o.z)), o.z + (i - 3.5) * 0.22);
            a.root.rotation.y = s ? -Math.PI / 2 : Math.PI / 2; play(a, i % 3 ? ['Sword_Attack'] : ['Punch_Cross'], 0.8 + Math.random() * 0.4); a.mixer.setTime(Math.random() * 2); o.soldiers.push(a); } });
      }
      o.soldiers.forEach(a => a.mixer && a.mixer.update(dt));
      if (Math.random() < 0.25) burst(o.x + (Math.random() - 0.5) * 1.6, 1, o.z + (Math.random() - 0.5) * 3, 3, '#ffe9a8', 2, 0.35, 0.6, -4);
      if (Math.random() < 0.06) smokePuff(o.x + (Math.random() - 0.5) * 4, 0.7, o.z + (Math.random() - 0.5) * 4, 1, '#6b6259', 3);
      return true;
    };
    o.remove = () => { fxLayer.remove(o.camp); o.soldiers.forEach(drop); };
    return o;
  },
};
// mage spells by element
FX.fireball = (f, t) => { const o = FX.meteor({ ...f, delay: 0 }, t); return o; };
FX.clash = (f, t) => { const o = { x: f.x + 0.5, z: f.y + 0.5, n: 0 }; o.update = () => { if (o.n++ < 40) { burst(o.x, 1, o.z, 4, '#ffe9a8', 2.5, 0.4, 0.7, -4); if (o.n % 10 === 0) smokePuff(o.x, 0.8, o.z, 2, '#6b6259', 3); } return o.n < 400; }; return o; };
FX.wave = (f, t) => FX.flood({ ...f, radius: 4 }, t);
FX.lightning_spell = FX.lightning;
FX.spell = FX.fire;
let eclipse = 0;
function syncFx(list, now) {
  const want = new Set();
  fightZones = [];
  for (const f of list || []) {
    const key = f.type === 'battle' && f.war ? `battle:${f.war}` : `${f.type}:${f.x.toFixed(1)}:${f.y.toFixed(1)}:${f.day}`;
    want.add(key);
    if (!live.has(key)) { const make = FX[f.type] || FX.construction; const o = make(f, now); if (o) { o.key = key; o.src = f; live.set(key, o); } }
    else { const o = live.get(key); if (o.src.type === 'battle') fightZones.push([o.x, o.z, 3.5]); if (o.src.type === 'riot' || o.src.type === 'raid') fightZones.push([o.x, o.z, 4]); }
  }
  for (const [k, o] of [...live]) if (!want.has(k)) { o.remove && o.remove(); live.delete(k); }
}
syncFx(D.fx, performance.now());
function tickFx(now, dt) { for (const [k, o] of [...live]) { const keep = o.update(now, dt); if (keep === false) { o.remove && o.remove(); live.delete(k); } } tickParticles(dt); }

// ---------------------------------------------------------------- smoke & clouds
const smokeGeo = new THREE.BufferGeometry(); const NS = 320; const sp = new Float32Array(NS * 3); const sage = new Float32Array(NS);
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
for (let i = 0; i < 12; i++) {
  const g = new THREE.Group();
  for (let j = 0; j < 4; j++) { const m = new THREE.Mesh(new THREE.SphereGeometry(1.2 + Math.random() * 1.2, 10, 8), new THREE.MeshStandardMaterial({ color: '#ffffff', transparent: true, opacity: 0.55, roughness: 1 })); m.position.set(j * 1.4 - 2, Math.random() * 0.4, (Math.random() - 0.5) * 1.5); m.scale.y = 0.45; m.castShadow = true; g.add(m); }
  g.position.set(Math.random() * (W + 20) - 10, 20 + Math.random() * 5, Math.random() * H); g.scale.setScalar(0.8); g.userData.v = 0.4 + Math.random() * 0.5; clouds.push(g); scene.add(g);
}

// ---------------------------------------------------------------- day / night
const CYCLE = 240;
function daylight(t) {
  const ph = (t / CYCLE + 0.25) % 1, a = ph * Math.PI * 2, elev = Math.sin(a);
  const tx = controls.target.x, tz = controls.target.z;
  sun.position.set(tx + Math.cos(a) * 50, 12 + elev * 50, tz + 25); sun.target.position.set(tx, 0, tz);
  sun.intensity = (Math.max(0.05, elev) * 1.3 + 0.15) * (1 - 0.85 * eclipse);
  sun.color.setHSL(0.09, 0.5, 0.5 + Math.max(0, elev) * 0.45);
  const day = Math.max(0, Math.min(1, (elev + 0.15) / 0.5)) * (1 - 0.8 * eclipse);
  hemi.intensity = 0.3 + day * 0.7;
  scene.background.copy(NIGHT).lerp(DAYSKY, day); scene.fog.color.copy(scene.background);
  windows.material.emissiveIntensity = (1 - day) * 1.4;
}

// ---------------------------------------------------------------- hover, click-to-follow
const ray = new THREE.Raycaster(); const mouse = new THREE.Vector2(-9, -9);
renderer.domElement.addEventListener('mousemove', e => { const r = renderer.domElement.getBoundingClientRect(); mouse.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1); tip.style.left = (e.clientX - r.left + 14) + 'px'; tip.style.top = (e.clientY - r.top + 14) + 'px'; });
renderer.domElement.addEventListener('mouseleave', () => { tip.style.display = 'none'; mouse.set(-9, -9); });
const v3 = new THREE.Vector3();
function hover() {
  if (mouse.x < -2) return;
  ray.setFromCamera(mouse, camera);
  let best = null, bd = 0.45;
  for (const [x, y, z, p] of hoverList) { v3.set(x, y, z); const d = ray.ray.distanceToPoint(v3); if (d < bd) { bd = d; best = p; } }
  if (best) { tip.style.display = 'block'; tip.replaceChildren(Object.assign(document.createElement('b'), { textContent: best.name }), document.createElement('br'),
      document.createTextNode(best.animal ? `${best.job} · ${best.doing || ''}` : `${best.job}, ${best.age}${best.role ? ' · ' + best.role : ''}${best.jail ? ' · in the cells' : ''}${best.inf ? ' · 🦠 sick' : ''}`)); return; }
  const hit = ray.intersectObjects(bmeshes, false)[0];
  if (hit) { const b = hit.object.userData.b; tip.style.display = 'block'; tip.replaceChildren(Object.assign(document.createElement('b'), { textContent: b.name }), document.createElement('br'), document.createTextNode(`${b.staff} staff · £${b.cash.toLocaleString()} cash`)); }
  else tip.style.display = 'none';
}

// ---------------------------------------------------------------- camera: follow the selected person, glide to the chosen village
function selectedPos() {
  for (const p of people.values()) if (p.sel && p.cur) return p.cur;
  for (const b of beasts.values()) if (b.sel && b.cur) return b.cur;
  return null;
}
const off = new THREE.Vector3();
let lastLook = '';
// when the viewer grabs the map, stop steering and pivot around whatever is in the middle of the view — not a fixed village
const groundPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), -0.5), centreRay = new THREE.Raycaster(), hitPt = new THREE.Vector3();
controls.addEventListener('start', () => { camGoal.pt = null; });

// ---- orbit around the spot under the mouse (not a fixed village): left-drag turns and tilts the view about the point
// you grabbed, and that point stays under the cursor. Right-drag pans and the wheel zooms as before (OrbitControls).
const ndc = new THREE.Vector2();
function groundUnder(clientX, clientY) {
  const r = renderer.domElement.getBoundingClientRect();
  ndc.set(((clientX - r.left) / r.width) * 2 - 1, -((clientY - r.top) / r.height) * 2 + 1);
  camera.updateMatrixWorld();
  centreRay.setFromCamera(ndc, camera);
  const hit = centreRay.intersectObjects([ground, water], false)[0];
  if (hit) return hit.point.clone();
  return centreRay.ray.intersectPlane(groundPlane, hitPt) ? hitPt.clone() : null;
}
function recentre() {        // keep OrbitControls' target on the ground straight ahead, so its own update never moves the view
  camera.updateMatrixWorld();
  centreRay.setFromCamera(new THREE.Vector2(0, 0), camera);
  if (centreRay.ray.intersectPlane(groundPlane, hitPt)) controls.target.copy(hitPt);
}
const orbit = { on: false, pivot: new THREE.Vector3(), x: 0, y: 0, id: null };
const UP = new THREE.Vector3(0, 1, 0), qTmp = new THREE.Quaternion(), rightV = new THREE.Vector3(), fwd = new THREE.Vector3();
function turnAbout(axis, angle) {
  qTmp.setFromAxisAngle(axis, angle);
  camera.position.sub(orbit.pivot).applyQuaternion(qTmp).add(orbit.pivot);
  camera.quaternion.premultiply(qTmp);
  camera.updateMatrixWorld();
}
function polarOf() { fwd.set(0, 0, -1).applyQuaternion(camera.quaternion); return Math.acos(Math.max(-1, Math.min(1, -fwd.y))); }
if (!HERO) {
  controls.enableRotate = false;
  const el = renderer.domElement;
  el.addEventListener('pointerdown', e => {
    if (e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey) return;
    const p = groundUnder(e.clientX, e.clientY);
    if (!p) return;
    orbit.on = true; orbit.pivot.copy(p); orbit.x = e.clientX; orbit.y = e.clientY; orbit.id = e.pointerId; camGoal.pt = null;
    try { el.setPointerCapture(e.pointerId); } catch (err) {}
  });
  el.addEventListener('pointermove', e => {
    if (!orbit.on || e.pointerId !== orbit.id) return;
    const k = 2 * Math.PI / Math.max(1, el.clientHeight);
    const dx = e.clientX - orbit.x, dy = e.clientY - orbit.y; orbit.x = e.clientX; orbit.y = e.clientY;
    turnAbout(UP, -dx * k);                                              // round the grabbed point
    rightV.setFromMatrixColumn(camera.matrixWorld, 0).normalize();
    const before = { p: camera.position.clone(), q: camera.quaternion.clone() };
    turnAbout(rightV, -dy * k);                                          // tilt: down → toward the top view, up → toward the side view
    const pol = polarOf();
    if (pol < 0.02 || pol > controls.maxPolarAngle || camera.position.y < heightAt(camera.position.x | 0, camera.position.z | 0) + 0.3) {
      camera.position.copy(before.p); camera.quaternion.copy(before.q); camera.updateMatrixWorld();
    }
    recentre();
  });
  const release = e => { if (orbit.on && e.pointerId === orbit.id) { orbit.on = false; recentre(); } };
  el.addEventListener('pointerup', release);
  el.addEventListener('pointercancel', release);
  // double-click anywhere: fly there
  el.addEventListener('dblclick', e => { const p = groundUnder(e.clientX, e.clientY); if (p) camGoal.pt = [p.x, p.z]; });
}
function steer(dt) {
  if (HERO) { labels.visible = false; return; }
  let goal = null;
  if (D.follow) { const s = selectedPos(); if (s) goal = [s[0], s[1]]; }
  if (!goal && D.focus !== focusIdx) { focusIdx = D.focus; goal = villageCentre(focusIdx); camGoal.until = performance.now() + 2500; camGoal.pt = goal; }
  const lk = D.look ? D.look.join(',') : '';
  if (!goal && lk && lk !== lastLook) { lastLook = lk; goal = [D.look[0] + 0.5, D.look[1] + 0.5]; camGoal.until = performance.now() + 2500; camGoal.pt = goal; }
  if (!lk) lastLook = '';
  if (!goal && camGoal.pt) {                // keep gliding until we arrive (or the viewer takes over)
    if (Math.hypot(camGoal.pt[0] - controls.target.x, camGoal.pt[1] - controls.target.z) < 0.15) camGoal.pt = null; else goal = camGoal.pt;
  }
  if (goal) {
    const k = Math.min(1, dt * (D.follow ? 4 : 2.5));
    off.copy(camera.position).sub(controls.target);
    if (D.follow && off.length() > 4) off.setLength(off.length() + (4 - off.length()) * k);
    controls.target.x += (goal[0] - controls.target.x) * k; controls.target.z += (goal[1] - controls.target.z) * k;
    controls.target.y += (tileTop(goal[0], goal[1]) + 0.15 - controls.target.y) * k;
    camera.position.copy(controls.target).add(off);
  }
  if (cap) { const p = [...people.values()].find(p => p.sel); cap.textContent = D.follow && p ? `following ${p.name}` : ''; }
  // only label the businesses of the village in view
  labels.children.forEach(l => { l.visible = l.userData.v === D.focus; });
}

// ---------------------------------------------------------------- loop, resize, polling
function fit() { const w = wrap.clientWidth, h = wrap.clientHeight; renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix(); }
new ResizeObserver(fit).observe(wrap); fit();
buildStructures();
let last = performance.now();
let loopErrors = 0;
function guard(name, fn) { try { fn(); } catch (e) { if (loopErrors++ < 5) console.error('[scene] ' + name + ': ' + e.message, e.stack); } }
function loop(now) { frame(now); requestAnimationFrame(loop); }
function frame(now) {
  const dt = Math.min(0.1, (now - last) / 1000); last = now;
  guard('daylight', () => daylight(now / 1000)); guard('people', () => animatePeople(now, dt)); guard('animals', () => animateBeasts(now, dt));
  guard('smoke', () => animateSmoke(dt)); guard('herds', () => animateHerds(dt, now)); guard('fx', () => tickFx(now, dt));
  clouds.forEach(c => { c.position.x += c.userData.v * dt; if (c.position.x > W + 12) c.position.x = -12; });
  water.material.emissiveIntensity = 0.2 + 0.08 * Math.sin(now / 900);
  lava.material.emissiveIntensity = 1.0 + 0.4 * Math.sin(now / 400);
  bigLabels.children.forEach(o => { if (o.userData.flag) o.rotation.y = Math.sin(now / 700 + o.position.x) * 0.3; });
  guard('camera', () => steer(dt));
  const cx = Math.max(-20, Math.min(W + 20, controls.target.x)) - controls.target.x, cz = Math.max(-20, Math.min(H + 20, controls.target.z)) - controls.target.z;
  if (cx || cz) { controls.target.x += cx; controls.target.z += cz; camera.position.x += cx; camera.position.z += cz; }
  controls.update();
  if (shake > 0) { camera.position.x += (Math.random() - 0.5) * shake; camera.position.y += (Math.random() - 0.5) * shake; shake = Math.max(0, shake - dt * 0.8); }
  if (!HERO) hover();
  renderer.render(scene, camera);
}
requestAnimationFrame(loop);
window.__nh = { people, beasts, LIB, live, camera, controls, renderer, frame, groundUnder };      // for debugging from the console
let lastDay = D.day, lastSel = D.sel;
async function poll() {
  try {
    const r = await fetch(URL + '?t=' + Date.now(), { cache: 'no-store' });
    if (r.ok) {
      const nd = await r.json();
      const now = performance.now();
      const changed = nd.day !== lastDay || nd.sel !== lastSel || nd.citizens.length !== D.citizens.length || nd.focus !== D.focus || nd.follow !== D.follow
                      || nd.fx.length !== D.fx.length || String(nd.look) !== String(D.look);
      if (changed) {
        const regrid = nd.gv !== gridVersion; D = nd; lastDay = nd.day; lastSel = nd.sel;
        if (regrid) { gridVersion = nd.gv; buildHeights(); buildTerrain(); buildKey = ""; }
        buildStructures(); setCitizens(D.citizens, now); setAnimals(D.animals, now); syncFx(D.fx, now);
      }
    }
  } catch (e) {}
  setTimeout(poll, 700);
}
if (URL) poll();
"""

HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;background:#0b1220;overflow:hidden;font-family:system-ui,sans-serif}
#wrap{position:relative;width:100%;height:__H__px;border-radius:12px;overflow:hidden;background:#0b1220}
canvas{display:block;width:100%;height:100%}
#tip{position:absolute;display:none;pointer-events:none;background:rgba(15,20,30,.92);color:#eef2f7;padding:6px 9px;border-radius:8px;font-size:12px;border:1px solid #2b3a4f;white-space:nowrap;z-index:2}
#hint{position:absolute;right:10px;bottom:8px;color:#8b98a8;font-size:11px;z-index:2}
#cap{position:absolute;left:12px;top:10px;color:#ffd43b;font-size:12px;font-weight:600;z-index:2;text-shadow:0 1px 3px #000}
</style>
<script type="importmap">{"imports":{"three":"https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js","three/addons/":"https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/"}}</script>
</head><body><div id="wrap"><div id="tip"></div><div id="cap"></div><div id="hint">drag to orbit round the spot you grab · scroll to zoom · right-drag to pan · double-click to fly there</div>__OVERLAY__</div>
<script type="module">__JS__</script></body></html>"""


def render_html(world, selected=None, height: int = 620, url: str = "", overlay: str = "", models: str = "/app/static/models/") -> str:
    """The realm scene. With `overlay` (trusted, pre-escaped HTML) it becomes a non-interactive
    backdrop that slowly orbits the realm, with the overlay laid over it."""
    payload = world_payload(world, selected)
    html = HTML.replace("__H__", str(height)).replace("__OVERLAY__", overlay)
    if overlay:
        html = html.replace('<div id="hint">drag to orbit round the spot you grab · scroll to zoom · right-drag to pan · double-click to fly there</div>', "")
    js = (JS.replace("__DATA__", json.dumps(payload)).replace("__URL__", url).replace("__MODELS__", models)
          .replace("__HERO__", "true" if overlay else "false"))
    return html.replace("__JS__", js)
