"""Isometric voxel renderer for the world, as a self-contained HTML/canvas component.

The world hands over its grid, buildings and citizens as JSON; the canvas draws a
little village: shaded blocks, pitched roofs, trees, a river that shimmers, and
citizens who bob as they go about their day. Wheel to zoom, drag to pan, hover for names.
"""
from __future__ import annotations
import json
import os
from . import terrain

JOB_COLOUR = {"farmer": "#2f9e44", "baker": "#e8a317", "craftsperson": "#e8590c", "merchant": "#3b82f6", "miner": "#7048e8",
              "innkeeper": "#d6336c", "teacher": "#12b886", "doctor": "#e03131", "unemployed": "#868e96", "child": "#f8f9fa", "retired": "#adb5bd"}


def world_payload(world, selected: int | None = None) -> dict:
    bs = [{"x": b.x, "y": b.y, "kind": b.kind, "name": b.name, "staff": len(b.employees), "cash": round(b.cash), "herd": getattr(b, "livestock", 0)}
          for b in world.open_businesses()]
    cs = []
    for c in world.alive():
        cs.append({"id": c.id, "x": c.pos[0], "y": c.pos[1], "job": c.job, "name": c.name, "col": JOB_COLOUR.get(c.job, "#999"),
                   "inf": c.infected, "sel": c.id == selected, "age": c.age_on(world.day)})
    homes = sorted({c.home for c in world.alive()})
    from .eras import era
    return {"w": world.width, "h": world.height, "grid": world.grid.tolist(), "buildings": bs, "citizens": cs,
            "homes": [list(h) for h in homes], "day": world.day, "style": era(world)["style"],
            "codes": {"WATER": terrain.WATER, "GRASS": terrain.GRASS, "FARM": terrain.FARMLAND, "FOREST": terrain.FOREST,
                      "ROCK": terrain.ROCK, "TOWN": terrain.TOWN, "ROAD": terrain.ROAD}}


JS = r"""
let D = __DATA__;
let T = D.codes;
const cv = document.getElementById('iso'); const ctx = cv.getContext('2d');
const tip = document.getElementById('tip');
let TW = 30, TH = 15, HZ = 9;               // tile width/height, height unit
let scale = 1, panX = 0, panY = 0, t0 = performance.now();
const rnd = (x, y, k) => { let s = Math.sin(x * 127.1 + y * 311.7 + k * 74.7) * 43758.5453; return s - Math.floor(s); };

function fit() {
  const W = cv.parentElement.clientWidth, H = cv.parentElement.clientHeight;
  cv.width = W * devicePixelRatio; cv.height = H * devicePixelRatio; cv.style.width = W + 'px'; cv.style.height = H + 'px';
  const worldW = (D.w + D.h) * TW / 2, worldH = (D.w + D.h) * TH / 2 + 6 * HZ;
  scale = Math.min(W / worldW, H / worldH) * 1.35;
  const bx = D.buildings.reduce((a, b) => a + b.x, 0) / Math.max(1, D.buildings.length), by = D.buildings.reduce((a, b) => a + b.y, 0) / Math.max(1, D.buildings.length);
  const cx = (D.w / 2 + bx) / 2, cy = (D.h / 2 + by) / 2;   // between the map centre and the town centre
  panX = W / 2 - sx(cx, cy, 0) * scale; panY = H / 2 - sy(cx, cy, 0) * scale;
}
const shade = (hex, f) => { if (hex[0] !== '#') return hex; const n = parseInt(hex.slice(1), 16); let r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255;
  r = Math.min(255, Math.max(0, r * f)); g = Math.min(255, Math.max(0, g * f)); b = Math.min(255, Math.max(0, b * f)); return `rgb(${r|0},${g|0},${b|0})`; };
const sx = (x, y, z) => (x - y) * TW / 2, sy = (x, y, z) => (x + y) * TH / 2 - z * HZ;

function block(x, y, z, h, col, fx = 0, fy = 0, fw = 1, fd = 1, bright = 1) {
  // a box whose footprint is [fx,fx+fw]x[fy,fy+fd] inside tile (x,y), base z, height h (in HZ units)
  const x0 = x + fx, y0 = y + fy, x1 = x0 + fw, y1 = y0 + fd;
  const p = (px, py, pz) => [sx(px, py, pz), sy(px, py, pz)];
  const a = p(x0, y0, z + h), b = p(x1, y0, z + h), c = p(x1, y1, z + h), d = p(x0, y1, z + h);
  const b2 = p(x1, y0, z), c2 = p(x1, y1, z), d2 = p(x0, y1, z);
  ctx.fillStyle = shade(col, 1.0 * bright); poly([a, b, c, d]);            // top
  ctx.fillStyle = shade(col, 0.72 * bright); poly([d, c, c2, d2]);         // left (front-left)
  ctx.fillStyle = shade(col, 0.55 * bright); poly([c, b, b2, c2]);         // right (front-right)
}
function poly(pts) { ctx.beginPath(); ctx.moveTo(pts[0][0], pts[0][1]); for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]); ctx.closePath(); ctx.fill(); }

function roof(x, y, z, col, fx, fy, fw, fd, rh) {
  const p = (px, py, pz) => [sx(px, py, pz), sy(px, py, pz)];
  const x0 = x + fx, y0 = y + fy, x1 = x0 + fw, y1 = y0 + fd, ym = (y0 + y1) / 2;
  const a = p(x0, y0, z), b = p(x1, y0, z), c = p(x1, y1, z), d = p(x0, y1, z);
  const r0 = p(x0, ym, z + rh), r1 = p(x1, ym, z + rh);
  ctx.fillStyle = shade(col, 0.95); poly([a, b, r1, r0]);        // back slope
  ctx.fillStyle = shade(col, 0.7); poly([d, c, r1, r0]);         // front slope
  ctx.fillStyle = shade('#d9c9a8', 0.6); poly([c, b, r1]);       // right gable
}

const BUILD = { farm: ['#b23a3a', '#7a2a2a'], bakery: ['#e9d8a6', '#b06f2b'], workshop: ['#6b4f2a', '#3c2a14'], market: ['#f1e4c8', '#2b6cb0'],
  mine: ['#6b6b6b', '#3d3d3d'], tavern: ['#8c5a2b', '#4a2c14'], school: ['#f4f4f4', '#2e5aac'], clinic: ['#ffffff', '#c92a2a'] };
const ICON = { farm: '🌾', bakery: '🥖', workshop: '⚒️', market: '🏪', mine: '⛏️', tavern: '🍺', school: '🏫', clinic: '🏥' };

function tree(x, y, z, k) {
  const s = 0.55 + 0.25 * rnd(x, y, k), off = 0.2 * rnd(x, y, k + 1);
  block(x, y, z, 1.2, '#6b4a2a', 0.42 + off, 0.42, 0.16, 0.16);
  block(x, y, z + 1.0, 1.1, '#2f7a3a', 0.5 - s / 2 + off, 0.5 - s / 2, s, s);
  block(x, y, z + 2.0, 0.8, '#3f9a48', 0.5 - s / 3 + off, 0.5 - s / 3, s * 0.66, s * 0.66);
}
function person(c, time) {
  const bob = Math.sin(time / 260 + c.id) * 0.06;
  const ox = 0.3 + 0.4 * rnd(c.id, 1, 1), oy = 0.3 + 0.4 * rnd(c.id, 2, 2);
  ctx.fillStyle = 'rgba(0,0,0,0.25)'; const [cx, cy] = [sx(c.x + ox + 0.1, c.y + oy + 0.1, 0), sy(c.x + ox + 0.1, c.y + oy + 0.1, 0)];
  ctx.beginPath(); ctx.ellipse(cx, cy, 4, 2, 0, 0, Math.PI * 2); ctx.fill();
  const h = c.job === 'child' ? 0.9 : 1.3;
  block(c.x, c.y, 0.05 + bob, h, c.col, ox, oy, 0.2, 0.2);
  block(c.x, c.y, 0.05 + bob + h, 0.45, '#f2c9a0', ox + 0.02, oy + 0.02, 0.16, 0.16);
  if (c.inf) { ctx.strokeStyle = '#ff5252'; ctx.lineWidth = 1.5; ctx.beginPath(); ctx.arc(cx, cy - 12, 7, 0, Math.PI * 2); ctx.stroke(); }
  if (c.sel) { ctx.strokeStyle = '#ffd43b'; ctx.lineWidth = 2; ctx.beginPath(); ctx.ellipse(cx, cy, 9, 4.5, 0, 0, Math.PI * 2); ctx.stroke(); }
}
function label(text, x, y, z, pad = 4) {
  const X = sx(x + 0.5, y + 0.5, z), Y = sy(x + 0.5, y + 0.5, z);
  ctx.font = '600 11px system-ui, sans-serif'; const w = ctx.measureText(text).width + pad * 2;
  ctx.fillStyle = 'rgba(15,20,30,0.82)'; ctx.beginPath(); ctx.roundRect(X - w / 2, Y - 9, w, 18, 5); ctx.fill();
  ctx.fillStyle = '#eef2f7'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(text, X, Y);
}

let bAt = {}, hAt = {}, cAt = {};
function index() {
  bAt = {}; D.buildings.forEach(b => bAt[b.x + ',' + b.y] = b);
  hAt = {}; D.homes.forEach(h => hAt[h[0] + ',' + h[1]] = true);
  cAt = {}; D.citizens.forEach(c => { (cAt[c.x + ',' + c.y] = cAt[c.x + ',' + c.y] || []).push(c); });
}
index();
// live updates: poll the world snapshot the app writes each tick; the iframe itself never re-mounts
const URL = "__URL__";
let lastDay = D.day;
async function poll() {
  try {
    const r = await fetch(URL + '?t=' + Date.now(), { cache: 'no-store' });
    if (r.ok) { const nd = await r.json(); if (nd.day !== lastDay || nd.sel !== D.sel) { const first = !D.grid; D = nd; T = D.codes; lastDay = nd.day; index(); if (first) fit(); } }
  } catch (e) {}
  setTimeout(poll, 400);
}
if (URL) poll();

function draw(time) {
  ctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
  ctx.fillStyle = '#0b1220'; ctx.fillRect(0, 0, cv.width, cv.height);
  ctx.translate(panX, panY); ctx.scale(scale, scale);
  const labels = [];
  for (let d = 0; d < D.w + D.h; d++) {
    for (let x = 0; x < D.w; x++) {
      const y = d - x; if (y < 0 || y >= D.h) continue;
      const t = D.grid[y][x];
      if (t === T.WATER) {
        const sh = 0.9 + 0.1 * Math.sin(time / 700 + x * 0.8 + y * 1.3);
        block(x, y, -0.4, 0.4, '#3b82c4', 0, 0, 1, 1, sh);
      } else if (t === T.GRASS) block(x, y, 0, 0.5, rnd(x, y, 3) > 0.5 ? '#79b25f' : '#6fa857');
      else if (t === T.FARM) { block(x, y, 0, 0.5, '#c9a85a'); ctx.fillStyle = 'rgba(80,60,20,0.35)';
        for (let i = 1; i < 4; i++) { const a = [sx(x + i / 4, y, 0.5), sy(x + i / 4, y, 0.5)], b = [sx(x + i / 4, y + 1, 0.5), sy(x + i / 4, y + 1, 0.5)]; ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.lineWidth = 1.2; ctx.strokeStyle = 'rgba(90,70,30,0.45)'; ctx.stroke(); } }
      else if (t === T.FOREST) { block(x, y, 0, 0.5, '#5f9a4c'); tree(x, y, 0.5, 1); if (rnd(x, y, 9) > 0.6) tree(x, y, 0.5, 5); }
      else if (t === T.ROCK) { const h = 1 + Math.floor(2.5 * rnd(x, y, 4)); block(x, y, 0, h, rnd(x, y, 6) > 0.5 ? '#8f8f8a' : '#7d7d78'); if (h > 2) block(x, y, h, 0.5, '#d9d9d6', 0.2, 0.2, 0.6, 0.6); }
      else if (t === T.TOWN) block(x, y, 0, 0.5, rnd(x, y, 7) > 0.5 ? '#cfc2a8' : '#c4b69b');
      else if (t === T.ROAD) block(x, y, 0, 0.5, '#b8a888');
      const b = bAt[x + ',' + y];
      if (b) {
        const [wall, rf] = BUILD[b.kind];
        if (b.kind === 'farm') { block(x, y, 0.5, 2.2, wall, 0.1, 0.15, 0.8, 0.7); roof(x, y, 2.7, rf, 0.05, 0.1, 0.9, 0.8, 1.2); }
        else if (b.kind === 'mine') { block(x, y, 0.5, 2.5, wall, 0.15, 0.15, 0.7, 0.7); block(x, y, 0.5, 1.2, '#1a1a1a', 0.55, 0.6, 0.3, 0.3); }
        else if (b.kind === 'market') { block(x, y, 0.5, 1.2, wall, 0.15, 0.15, 0.7, 0.7); roof(x, y, 1.7, rf, 0.05, 0.05, 0.9, 0.9, 0.6); }
        else { block(x, y, 0.5, 2.4, wall, 0.15, 0.15, 0.7, 0.7); roof(x, y, 2.9, rf, 0.08, 0.08, 0.84, 0.84, 1.1); }
        labels.push([ICON[b.kind] + ' ' + b.name, x, y, 5.2]);
      } else if (hAt[x + ',' + y] && t !== T.WATER) {
        const wc = ['#d8c8a8', '#c9b9a0', '#e2d2b6'][Math.floor(3 * rnd(x, y, 8))];
        block(x, y, 0.5, 1.6, wc, 0.2, 0.2, 0.6, 0.6); roof(x, y, 2.1, rnd(x, y, 2) > 0.5 ? '#8a4b3b' : '#5d6b7a', 0.12, 0.12, 0.76, 0.76, 0.9);
      }
      const cs = cAt[x + ',' + y]; if (cs) cs.forEach(c => person(c, time));
    }
  }
  labels.forEach(l => label(l[0], l[1], l[2], l[3]));
}

let last = 0;
function loop(t) { if (t - last > 40) { draw(t); last = t; } requestAnimationFrame(loop); }
fit(); requestAnimationFrame(loop);
window.addEventListener('resize', fit);
new ResizeObserver(fit).observe(cv.parentElement);
setTimeout(fit, 50); setTimeout(fit, 300); setTimeout(fit, 1000);

// interaction: wheel zoom, drag pan, hover
let drag = null;
cv.addEventListener('wheel', e => { e.preventDefault(); const f = e.deltaY < 0 ? 1.12 : 1 / 1.12; const r = cv.getBoundingClientRect(); const mx = e.clientX - r.left, my = e.clientY - r.top;
  panX = mx - (mx - panX) * f; panY = my - (my - panY) * f; scale *= f; }, { passive: false });
cv.addEventListener('mousedown', e => { drag = [e.clientX - panX, e.clientY - panY]; });
window.addEventListener('mouseup', () => drag = null);
cv.addEventListener('mousemove', e => {
  const r = cv.getBoundingClientRect(); const mx = e.clientX - r.left, my = e.clientY - r.top;
  if (drag) { panX = e.clientX - drag[0]; panY = e.clientY - drag[1]; return; }
  const wx = (mx - panX) / scale, wy = (my - panY) / scale;
  const gx = (wx / (TW / 2) + wy / (TH / 2)) / 2, gy = (wy / (TH / 2) - wx / (TW / 2)) / 2;
  let best = null, bd = 1.2;
  D.citizens.forEach(c => { const d = Math.hypot(c.x + 0.5 - gx, c.y + 0.5 - gy + 1.2); if (d < bd) { bd = d; best = c; } });
  const b = bAt[Math.floor(gx) + ',' + Math.floor(gy)] || bAt[Math.floor(gx) + ',' + Math.floor(gy + 1)];
  if (best) { tip.style.display = 'block'; tip.style.left = mx + 14 + 'px'; tip.style.top = my + 14 + 'px'; tip.replaceChildren(Object.assign(document.createElement('b'), {textContent: best.name}), document.createElement('br'), document.createTextNode(`${best.job}, ${best.age}${best.inf ? ' · 🦠 sick' : ''}`)); }
  else if (b) { tip.style.display = 'block'; tip.style.left = mx + 14 + 'px'; tip.style.top = my + 14 + 'px'; tip.replaceChildren(Object.assign(document.createElement('b'), {textContent: b.name}), document.createElement('br'), document.createTextNode(`${b.staff} staff · £${b.cash.toLocaleString()} cash`)); }
  else tip.style.display = 'none';
});
cv.addEventListener('mouseleave', () => tip.style.display = 'none');
"""

HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;background:#0b1220;overflow:hidden;font-family:system-ui,sans-serif}
#wrap{position:relative;width:100%;height:__H__px;border-radius:12px;overflow:hidden;background:#0b1220}
canvas{display:block;cursor:grab}
#tip{position:absolute;display:none;pointer-events:none;background:rgba(15,20,30,.92);color:#eef2f7;padding:6px 9px;border-radius:8px;font-size:12px;border:1px solid #2b3a4f;white-space:nowrap}
#hint{position:absolute;right:10px;bottom:8px;color:#8b98a8;font-size:11px}
</style></head><body><div id="wrap"><canvas id="iso"></canvas><div id="tip"></div><div id="hint">scroll to zoom · drag to pan · hover for names</div></div>
<script>__JS__</script></body></html>"""


def render_html(world, selected: int | None = None, height: int = 620, url: str = "") -> str:
    """Embed the world directly, or (with `url`) embed it and keep polling that JSON for live updates."""
    payload = world_payload(world, selected)
    payload["sel"] = selected
    return HTML.replace("__H__", str(height)).replace("__JS__", JS.replace("__DATA__", json.dumps(payload)).replace("__URL__", url))


def write_snapshot(world, path: str, selected: int | None = None):
    payload = world_payload(world, selected)
    payload["sel"] = selected
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f)
    os.replace(tmp, path)
