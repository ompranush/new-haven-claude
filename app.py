import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

import networkx as nx
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

from civilisation import World, chronicle_text, terrain
from civilisation.iso import render_html as render_iso, write_snapshot, JOB_COLOUR
from civilisation.scene import render_html as render_3d
from civilisation.personality import describe, thought, archetype
from civilisation.systems.politics import LAW_TEXT
import uuid, glob

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
os.makedirs(STATIC, exist_ok=True)
from civilisation.experiments import SCENARIOS, compare, summary
from civilisation.systems import economy
from civilisation.systems.disasters import all_injectable
from civilisation.providers import PROVIDERS, make_backend
from civilisation.persistence import get_store, Recorder, restore_world, encrypt_key, decrypt_key, token_hash
from civilisation.person import apply_person_plan, interpret_person, rules_interpret_person, PERSON_OPS
from civilisation.security import esc, clean_text, scrub, Limiter, allow_custom_providers


@st.cache_resource(show_spinner=False)
def limiters():
    return {"god": Limiter(5, 900), "claim": Limiter(10, 900), "instruct": Limiter(1000, 60)}


IN_PRODUCTION = bool(os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("PRODUCTION"))
from civilisation.systems.lifecycle import ADULT_GOALS
import secrets, hmac
from civilisation.eras import ERAS, display_year, job_label
import threading
VILLAGE = os.environ.get("VILLAGE_NAME", "commons")
INJECTABLE_ALL = all_injectable()

st.set_page_config(page_title="New Haven — AI Civilisation", page_icon="🌲", layout="wide", initial_sidebar_state="collapsed")

SERIES = ["#3b82f6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#22c55e", "#8b5cf6", "#ef4444"]
PLOT = dict(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", margin=dict(l=8, r=8, t=8, b=8), font=dict(size=12, color="#c9d3df"),
            legend=dict(orientation="h", y=-0.2), hovermode="x unified", xaxis=dict(gridcolor="#1f2a3a", zerolinecolor="#1f2a3a"),
            yaxis=dict(gridcolor="#1f2a3a", zerolinecolor="#1f2a3a"))

st.markdown("""
<style>
  .block-container{padding:0.6rem 1rem 1rem 1rem;max-width:100%}
  header[data-testid="stHeader"]{display:none}
  div[data-testid="stToolbar"],div[data-testid="stDecoration"],div[data-testid="stStatusWidget"]{display:none}
  div[data-testid="stTabs"] button{font-weight:600;padding:6px 14px;border-radius:10px}
  div[data-testid="stTabs"] button[aria-selected="true"]{background:#1e3a8a44}
  .panel{background:#141d2b;border:1px solid #1f2a3a;border-radius:14px;padding:14px 16px;margin-bottom:12px}
  .panel h4{margin:0 0 10px 0;font-size:15px;color:#e6edf3}
  .stat{display:flex;align-items:center;gap:10px;padding:7px 0;border-bottom:1px solid #1a2433}
  .stat:last-child{border-bottom:none}
  .stat .ic{width:30px;height:30px;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:16px;background:#1b2636}
  .stat .lb{font-size:11px;color:#8b98a8;white-space:nowrap}
  .stat .vl{font-size:17px;font-weight:700;color:#e6edf3;line-height:1.1;white-space:nowrap}
  .stat .dl{margin-left:auto;font-size:11px;font-weight:600;white-space:nowrap;padding-left:6px}
  .up{color:#4ade80}.dn{color:#f87171}.nt{color:#8b98a8}
  .bar{height:8px;border-radius:6px;background:#1b2636;overflow:hidden;margin:4px 0 8px 0}
  .bar>div{height:100%;border-radius:6px}
  .ev{font-size:13px;padding:5px 0;border-bottom:1px solid #1a2433;color:#d6dee8}
  .ev b{color:#7aa2f7;font-weight:600;margin-right:8px;font-family:ui-monospace,monospace;font-size:12px}
  .ev.big{color:#fff}
  .brand{display:flex;align-items:center;gap:12px}
  .brand .t{font-size:24px;font-weight:800;color:#fff;line-height:1}
  .brand .s{font-size:12px;color:#8b98a8}
  .clock{font-size:13px;color:#c9d3df;text-align:right;line-height:1.3}
  .clock b{font-size:16px;color:#fff}
  .avatar{width:64px;height:64px;border-radius:12px;display:flex;align-items:center;justify-content:center;font-size:26px;font-weight:800;color:#fff}
  .mem{font-size:12.5px;color:#c9d3df;padding:3px 0}
  .mem b{color:#7aa2f7;font-family:ui-monospace,monospace;font-weight:600;font-size:11.5px;margin-right:6px}
  .quote{color:#8b98a8;font-style:italic;font-size:13px;text-align:center;padding:10px}
  div[data-testid="stVerticalBlockBorderWrapper"]{background:#141d2b;border:1px solid #1f2a3a !important;border-radius:14px;padding:4px 6px}
  div[data-testid="stVerticalBlockBorderWrapper"] h4{margin:0 0 6px 0;font-size:15px;color:#e6edf3}
  div[data-testid="stSegmentedControl"] button{border-radius:10px}
</style>
""", unsafe_allow_html=True)

# ------------------------------------------------------------------ state
def host_cfg():
    """The host's LLM configuration: session settings, falling back to environment keys."""
    ss = st.session_state
    provider = ss.get("provider", "anthropic")
    env = PROVIDERS[provider][2]
    key = ss.get("api_key") or (os.environ.get(env) if env else "") or ""
    return {"provider": provider, "model": ss.get("llm_model") or PROVIDERS[provider][1], "api_key": key or None,
            "base_url": ss.get("base_url") or None, "has_key": bool(key) or provider in ("ollama", "custom")}


def host_backend():
    cfg = host_cfg()
    return make_backend(cfg["provider"], cfg["model"], api_key=cfg["api_key"], base_url=cfg["base_url"])


def make_brain(threshold=None, max_calls=None, owner=""):
    from civilisation.llm import LLMBrain
    ss = st.session_state
    return LLMBrain(threshold=threshold if threshold is not None else ss.get("llm_threshold", 0.6),
                    max_calls=max_calls if max_calls is not None else ss.get("llm_max", 300), backend=host_backend(), owner=owner)


def new_world(seed, pop, llm, era="medieval"):
    brain = None
    if llm:
        try:
            brain = make_brain()
        except Exception as e:
            st.toast(f"LLM brain unavailable: {e}", icon="⚠️")
    return World(seed=seed, population=pop, width=52, height=34, brain=brain, config={"era": era})


@st.cache_resource(show_spinner=False)
def shared_village():
    """One village for everyone on this server. It ticks on its own thread, persists to the store,
    and restores itself (people, history, sponsored minds) after a restart."""
    from civilisation.llm import LLMBrain
    store = get_store(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "newhaven.db"))
    state = {"running": True, "tick_seconds": float(os.environ.get("TICK_SECONDS", 4)), "days_per_tick": 1, "error": "", "residents": {},
             "store": store, "restored": False, "notes": []}
    w = None
    try:
        w = restore_world(store, VILLAGE)
    except Exception as e:
        state["notes"].append(f"could not restore snapshot: {e}")
    if w is None:
        w = World(seed=int(os.environ.get("VILLAGE_SEED", 2026)), population=int(os.environ.get("VILLAGE_POP", 120)), width=52, height=34, name="New Haven Commons",
              config={"era": os.environ.get("VILLAGE_ERA", "medieval")})
    else:
        state["restored"] = True
    state["world"] = w
    try:                                                 # host brain from the first provider key in the environment
        for prov, (_, model, env, _) in PROVIDERS.items():
            if env and os.environ.get(env):
                w.brain = LLMBrain(threshold=float(os.environ.get("LLM_THRESHOLD", 0.7)), max_calls=int(os.environ.get("LLM_MAX_CALLS", 5000)),
                                   backend=make_backend(prov, os.environ.get("LLM_MODEL") or model, api_key=os.environ[env]))
                break
    except Exception as e:
        state["notes"].append(f"host brain unavailable: {e}")
    try:                                                 # sponsored minds come back with their (decrypted) keys
        for r in store.read_residents(VILLAGE):
            cid = int(r["citizen_id"])
            state["residents"][cid] = r.get("sponsor") or "anonymous"
            key = decrypt_key(r.get("enc_key"))
            if cid in w.citizens and w.citizens[cid].alive and (key or r["provider"] in ("ollama", "custom")):
                try:
                    w.brains[cid] = LLMBrain(threshold=0.45, max_calls=int(r.get("max_calls") or 200), owner=r.get("sponsor") or "",
                                             backend=make_backend(r["provider"], r["model"], api_key=key, base_url=r.get("base_url") or None))
                except Exception as e:
                    state["notes"].append(f"resident {r['name']}: {e}")
    except Exception as e:
        state["notes"].append(f"residents: {e}")
    if w.brain is None:
        from civilisation.brains import RulesBrain
        w.brain = RulesBrain()
    rec = Recorder(store, VILLAGE, snapshot_every=int(os.environ.get("SNAPSHOT_EVERY_DAYS", 30)))
    rec.prime(w)
    state["recorder"] = rec

    def loop():
        while True:
            time.sleep(state["tick_seconds"])
            if state["running"]:
                try:
                    state["world"].step(state["days_per_tick"])
                    rec.flush(state["world"])
                except Exception as e:
                    state["error"] = f"{type(e).__name__}: {e}"
    threading.Thread(target=loop, daemon=True, name="village-ticker").start()
    return state


SPEEDS = {"1 day / sec": (1, 1.0), "1 week / sec": (7, 1.0), "1 month / sec": (30, 1.0), "As fast as possible": (30, 0.0)}


ss = st.session_state
if "sid" not in ss:
    ss.sid = uuid.uuid4().hex[:10]
    for f in glob.glob(os.path.join(STATIC, "world_*.json")):      # tidy snapshots from dead sessions
        if time.time() - os.path.getmtime(f) > 3600:
            os.remove(f)
if "world" not in ss:
    ss.world = new_world(42, 100, False)
    ss.playing = False
    ss.speed = "1 day / sec"
    ss.selected = None
    ss.last_tick = 0.0
    ss.mode = "private"
PUBLIC = ss.get("mode") == "public"
shared = shared_village() if PUBLIC else None
w: World = shared["world"] if PUBLIC else ss.world
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
# no password: open god mode for local play, but *nobody* is god on a production server
IS_GOD = (not PUBLIC) or bool(ss.get("is_god")) or (not ADMIN_PASSWORD and not IN_PRODUCTION)
# claim link: ?claim=TOKEN re-attaches a steward to their person
if PUBLIC and st.query_params.get("claim") and not ss.get("resident_id"):
    tok = clean_text(st.query_params["claim"], 100)
    if limiters()["claim"].allow(ss.sid):
        limiters()["claim"].hit(ss.sid)
        th = token_hash(tok)
        for r in shared["store"].read_residents(VILLAGE):
            if r.get("token_hash") == th and int(r["citizen_id"]) in w.citizens:
                ss.resident_id = int(r["citizen_id"]); ss.steward_token = tok; ss.selected = ss.resident_id
                break
    st.query_params.clear()
w.lock.acquire()          # the public village ticks on another thread; hold it still while we draw
try:
  alive = w.alive()
  if not alive:
      ss.playing = False
      st.error(f"💀 {w.name} is empty. The civilisation ended on day {w.day:,}. Read the Events page for the story, or create a new world in Settings.")
  last = w.history[-1]
  prev = w.history[-53] if len(w.history) > 53 else w.history[0]


  def delta(key, fmt="{:+.0f}", invert=False, pct=False):
      d = last[key] - prev[key]
      cls = "nt" if abs(d) < 1e-9 else ("up" if (d > 0) != invert else "dn")
      arrow = "" if abs(d) < 1e-9 else ("↑" if d > 0 else "↓")
      return f'<span class="dl {cls}">{arrow} {fmt.format(d)}{"%" if pct else ""}</span>'


  def stat(icon, label, value, dl=""):
      return f'<div class="stat"><div class="ic">{icon}</div><div><div class="lb">{label}</div><div class="vl">{value}</div></div>{dl}</div>'


  def bar(label, v, colour):
      return f'<div style="display:flex;justify-content:space-between;font-size:12px;color:#8b98a8"><span>{label}</span><span>{v*100:.0f}%</span></div><div class="bar"><div style="width:{v*100:.0f}%;background:{colour}"></div></div>'


  # ------------------------------------------------------------------ header
  h1, h2, h3, h4 = st.columns([1.5, 5.0, 0.8, 1.3])
  with h1:
      st.markdown('<div class="brand"><span style="font-size:34px">🌲</span><div><div class="t">New Haven</div><div class="s">An AI Civilisation Simulator</div></div></div>', unsafe_allow_html=True)
  def brain_badge(w):
      b = w.brain
      mode = ('<span style="color:#8b5cf6">🏘️ Public village · </span>' + ('<span style="color:#eda100">⚡ you are god · </span>' if ss.get("is_god") else '<span style="color:#8b98a8">👁 visitor · </span>')) if PUBLIC else ""
      if PUBLIC and shared.get("error"):
          mode += f'<span style="color:#f87171">ticker error: {esc(shared["error"][:80])} · </span>'
      residents = f' · {len(w.brains)} sponsored minds' if w.brains else ""
      if getattr(b, "name", "") == "llm":
          stt = b.stats()
          if stt["failures"] and stt["failures"] >= max(1, stt["calls"]):
              return f'{mode}<span style="color:#f87171">🧠 {esc(b.provider)} failing — {esc(stt["last_error"][:60])}</span>'
          return (f'{mode}<span style="color:#4ade80">🧠 {esc(b.provider)}/{esc(b.model)} thinking</span> <span style="color:#8b98a8">· '
                  f'{stt["calls"]} calls{" (" + str(stt["pending"]) + " pending)" if stt["pending"] else ""} · ${stt["est_cost_usd"]:.2f}{residents}</span>')
      return f'{mode}<span style="color:#8b98a8">⚙️ Rules brain — add a key in Settings{residents}</span>'


  def tick_interval():
      if PUBLIC:
          return max(1.0, float(shared["tick_seconds"]))
      return SPEEDS.get(ss.speed, (1, 1.0))[1] or 0.3 if ss.playing else None

  def clock():
      st.markdown(f'<div class="clock"><b>{display_year(w)}</b> · {ERAS[w.config.get("era", "medieval")]["label"]}<br>Day {w.day:,} · year {w.year}</div>', unsafe_allow_html=True)

  with h3:
      st.fragment(run_every=tick_interval())(clock)()
  st.markdown(f'<div style="font-size:12px;margin:-6px 0 6px 0;text-align:right">{brain_badge(w)}</div>', unsafe_allow_html=True)
  with h4:
      b1, b2, b3 = st.columns(3)
      running = shared["running"] if PUBLIC else ss.playing
      lock_help = "" if IS_GOD else " (only the god of this village can do this — Settings → God login)"
      if b1.button("⏸" if running else "▶", use_container_width=True, help="Play / pause the live simulation" + lock_help, disabled=not IS_GOD):
          if PUBLIC:
              shared["running"] = not shared["running"]
          else:
              ss.playing = not ss.playing
          st.rerun()
      if b2.button("⏭", use_container_width=True, help="Step one week" + lock_help, disabled=not IS_GOD):
          w.step(7); st.rerun()
      if b3.button("⏩", use_container_width=True, help="Run one year" + lock_help, disabled=not IS_GOD):
          with st.spinner("A year passes…"):
              w.step(365)
          st.rerun()
  with h2:
      PAGES = ["🌍 World", "👥 Citizens", "📊 Economy", "🏛️ Politics", "⚡ Events", "🏡 Move in", "🧪 Research", "⚙️ Settings"]
      page = st.segmented_control("nav", PAGES, default=PAGES[0], key="nav", label_visibility="collapsed") or PAGES[0]

  # ------------------------------------------------------------------ WORLD
  def world_page():
      global alive, last, prev
      with w.lock:
          if not PUBLIC and ss.playing:
              w.step(SPEEDS.get(ss.speed, (1, 1.0))[0])
          alive = w.alive()
          if not alive:
              st.error(f"💀 {w.name} is empty. The civilisation ended on day {w.day:,}.")
              return
          last = w.history[-1]
          prev = w.history[-53] if len(w.history) > 53 else w.history[0]
      left, mid, right = st.columns([1.0, 3.9, 1.15])
      with left:
          households = len({c.home for c in alive})
          dead = [c for c in w.citizens.values() if not c.alive]
          life_exp = np.mean([c.age_on(c.died_day) for c in dead[-40:]]) if dead else 70.0
          food_days = w.food / max(1, len(alive))
          security = max(0, 100 - last["grievance"] - (20 if w.pandemic else 0) - (10 if w.strike else 0))
          st.markdown('<div class="panel"><h4>World Overview</h4>' +
                      stat("👥", "Population", f"{last['population']:,}", delta("population")) +
                      stat("🏠", "Households", households) +
                      stat("🏪", "Businesses", last["businesses"], delta("businesses")) +
                      stat("💰", "Median wealth", f"£{last['median_wealth']:,.0f}", delta("median_wealth", "{:+.0f}")) +
                      stat("😊", "Happiness", f"{last['happiness']:.0f}%", delta("happiness", "{:+.0f}", pct=True)) +
                      stat("💗", "Life expectancy", f"{life_exp:.1f}") +
                      stat("📉", "Unemployment", f"{last['unemployment']:.1f}%", delta("unemployment", "{:+.1f}", invert=True, pct=True)) +
                      stat("🌾", "Food supply", f"{food_days:.0f} days", delta("food", "{:+.0f}")) +
                      stat("🛡️", "Security", f"{security:.0f}%") + "</div>", unsafe_allow_html=True)
          # minimap
          cols = {terrain.WATER: "#3b82c4", terrain.GRASS: "#6fa857", terrain.FARMLAND: "#c9a85a", terrain.FOREST: "#3f7d4e", terrain.ROCK: "#8f8f8a", terrain.TOWN: "#cfc2a8", terrain.ROAD: "#b8a888"}
          fig = go.Figure()
          cs = []
          n = 7
          for k, c in cols.items():
              cs += [[k / n, c], [(k + 1) / n, c]]
          fig.add_trace(go.Heatmap(z=w.grid, colorscale=cs, zmin=0, zmax=n, showscale=False, hoverinfo="skip"))
          bs = w.open_businesses()
          fig.add_trace(go.Scatter(x=[b.x for b in bs], y=[b.y for b in bs], mode="markers", marker=dict(size=6, color="#ffd43b", symbol="square"), hoverinfo="skip"))
          homes = list({c.home for c in alive})
          fig.add_trace(go.Scatter(x=[h[0] for h in homes], y=[h[1] for h in homes], mode="markers", marker=dict(size=3, color="#f97316", symbol="square"), hoverinfo="skip"))
          fig.update_layout(height=170, margin=dict(l=0, r=0, t=0, b=0), paper_bgcolor="rgba(0,0,0,0)", showlegend=False,
                            xaxis=dict(visible=False), yaxis=dict(visible=False, scaleanchor="x"))
          with st.container(border=True):
              st.markdown("<h4>Map</h4>", unsafe_allow_html=True)
              st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
              st.markdown('<div style="font-size:11px;color:#8b98a8;display:flex;gap:10px;flex-wrap:wrap"><span>🟨 business</span><span>🟧 home</span><span style="color:#c9a85a">■ fields</span><span style="color:#3f7d4e">■ forest</span><span style="color:#8f8f8a">■ hills</span></div>', unsafe_allow_html=True)

      with mid:
          snap = os.path.join(STATIC, f"world_{ss.sid}.json")
          if "iso_html" not in ss:
              render = render_iso if ss.get("renderer") == "classic" else render_3d
              ss.iso_html = render(w, ss.selected, height=600, url=f"/app/static/world_{ss.sid}.json")
          write_snapshot(w, snap, ss.selected)
          components.html(ss.iso_html, height=604)
          if w.pandemic:
              st.error(f"🦠 {w.pandemic['name']} is spreading — {last['infected']} sick, {w.pandemic['deaths']} dead.")
          if w.strike:
              sm = w.movements.get(w.strike["movement"])
              st.warning(f"✊ {len(w.strike['members'])} members of the {sm.name if sm else 'movement'} are on strike until day {w.strike['until']:,} "
                         f"({w.strike['until'] - w.day} days to go — strikes end as days pass, or decree an end).")
          if w.recession_days:
              st.warning(f"📉 Recession — {w.recession_days} days to go.")

      with right:
          options = {c.id: f"{c.name} ({c.age_on(w.day)})" for c in sorted(alive, key=lambda c: c.id)}
          if not options:
              options = {c.id: f"{c.name} († day {c.died_day})" for c in list(w.citizens.values())[:50]}
          if ss.selected not in options:
              ss.selected = max(alive, key=lambda c: len(c.memories)).id if alive else next(iter(options))
          ss.selected = st.selectbox("Selected citizen", list(options), index=list(options).index(ss.selected) if ss.selected in options else 0,
                                     format_func=lambda i: options[i], label_visibility="collapsed")
          write_snapshot(w, os.path.join(STATIC, f"world_{ss.sid}.json"), ss.selected)
          c = w.citizens[ss.selected]
          emp = w.businesses.get(c.employer_id) if c.employer_id else None
          mood = "😊 Happy" if c.happiness > 0.65 else ("😐 Fine" if c.happiness > 0.45 else "😟 Struggling")
          near = min(w.open_businesses(), key=lambda b: abs(b.x - c.pos[0]) + abs(b.y - c.pos[1]), default=None)
          where = "Home" if c.pos == c.home or (abs(c.pos[0] - c.home[0]) + abs(c.pos[1] - c.home[1]) <= 2) else (near.name if near and abs(near.x - c.pos[0]) + abs(near.y - c.pos[1]) <= 2 else "Out and about")
          hue = (c.id * 47) % 360
          social = min(1.0, sum(1 for r in c.relationships.values() if r.score >= 40) / 8)
          mems = sorted(c.memories, key=lambda m: -m.day)[:4]
          st.markdown('<div class="panel"><h4>Selected Citizen</h4>'
                      f'<div style="display:flex;gap:12px;align-items:flex-start"><div class="avatar" style="background:linear-gradient(135deg,hsl({hue},60%,45%),hsl({hue+40},60%,30%))">{c.name[0]}</div>'
                      f'<div style="font-size:13px;color:#c9d3df;line-height:1.5"><div style="font-size:16px;font-weight:700;color:#fff">{esc(c.name)}</div>'
                      f'<span style="color:#eda100">{", ".join(describe(c)).capitalize()}</span><br>Age: {c.age_on(w.day)} · {job_label(w, c.job).title()}{" at " + esc(emp.name) if emp else ""}<br>Mood: {mood}<br>Location: {esc(where)}</div></div>'
                      f'<div style="margin:10px 0 6px 0;padding:8px 10px;border-left:3px solid #eda100;background:#1b2636;border-radius:6px;font-size:13px;color:#e6edf3;font-style:italic">“{esc(thought(w, c))}”</div>'
                      + bar("Health", c.health, "#4ade80") + bar("Happiness", c.happiness, "#3b82f6") + bar("Energy", 1 - c.hunger, "#eda100") + bar("Social", social, "#8b5cf6")
                      + f'<div style="font-size:13px;color:#8b98a8;margin-top:6px">Current goal</div><div style="font-size:14px;color:#fff">🎯 {c.goal.capitalize()} <span style="color:#8b98a8">({c.goal_progress*100:.0f}%)</span></div>'
                      + '<div style="font-size:13px;color:#8b98a8;margin-top:8px">Recent memories</div>'
                      + "".join(f'<div class="mem"><b>Day {m.day}</b>{esc(m.text)}</div>' for m in mems) + (f'<div class="mem" style="color:#8b98a8">Nothing memorable yet.</div>' if not mems else "")
                      + f'<div style="font-size:12px;color:#8b98a8;margin-top:8px">£{c.money:,.0f} · {sum(1 for r in c.relationships.values() if r.score>=40)} friends · {sum(1 for r in c.relationships.values() if r.score<=-40)} enemies'
                      + (f" · married to {esc(w.citizens[c.spouse_id].name)}" if c.spouse_id else "") + (f" · {esc(w.movements[c.movement_id].name)}" if c.movement_id else "") + '</div></div>', unsafe_allow_html=True)
          with st.container(border=True):
              st.markdown("<h4>Simulation Controls</h4>" + ("" if IS_GOD else "<div style='font-size:12px;color:#eda100'>🔒 Only the god of this village controls the civilisation. You control your own person on the Move in page.</div>"), unsafe_allow_html=True)
              if not IS_GOD:
                  st.markdown(f"<div style='font-size:12px;color:#8b98a8'>Pace: 1 day every {shared['tick_seconds']:.0f}s · {'running' if shared['running'] else 'paused'}</div>", unsafe_allow_html=True)
              if not PUBLIC:
                  ss.speed = st.select_slider("Speed while playing", options=list(SPEEDS), value=ss.speed if ss.speed in SPEEDS else "1 day / sec")
              INJECTABLE = all_injectable(w)
              shock = st.selectbox("God mode", list(INJECTABLE), format_func=lambda k: f"⚡ {k.replace('_', ' ')} — {INJECTABLE[k]}", label_visibility="collapsed", disabled=not IS_GOD)
              if st.button("Smite the town", use_container_width=True, type="primary", disabled=not IS_GOD):
                  w.inject(shock); st.toast(INJECTABLE[shock], icon="⚡"); st.rerun()
              has_key = host_cfg()["has_key"]
              st.markdown('<div style="font-size:13px;color:#8b98a8;margin-top:6px">✍️ Or decree anything' + ("" if has_key else " <span style='color:#eda100'>(needs an API key — Settings)</span>") + "</div>", unsafe_allow_html=True)
              with st.form("decree_form", clear_on_submit=True, border=False):
                  decree = st.text_area("Decree", placeholder="e.g. A travelling circus arrives · Gold is found in the hills · A preacher declares the council cursed · The bakery owner is caught cheating customers · Bread is free for a month",
                                        label_visibility="collapsed", height=80)
                  submitted = st.form_submit_button("Make it so ✨", use_container_width=True, disabled=not IS_GOD)
              decree = clean_text(decree, 1500)
              if submitted and decree.strip() and IS_GOD:
                  from civilisation.commands import apply_plan, fallback_plan
                  plan, source = None, "llm"
                  if has_key:
                      try:
                          from civilisation.llm import interpret
                          with st.spinner("Fate is deciding…"):
                              plan = interpret(w, decree.strip(), backend=host_backend())
                      except Exception as e:
                          st.error(f"The model could not interpret that: {e}")
                  if plan is None and not has_key:
                      plan, source = fallback_plan(decree), "rules"
                      if plan is None:
                          st.warning("Without an API key only a couple of stock phrases work (try 'circus' or 'gold'). Add a key in Settings for anything you can type.")
                  if plan:
                      done = apply_plan(w, plan, source)
                      ss.decrees = (ss.get("decrees") or []) + [{"day": w.day, "text": decree.strip(), "narration": plan["narration"], "done": done}]
                      if PUBLIC:
                          try:
                              shared["store"].write_decree(VILLAGE, {**ss.decrees[-1], "session": ss.sid, "sponsor": ss.get("sponsor_name", "")})
                          except Exception as e:
                              st.toast(f"decree not logged: {e}", icon="⚠️")
                      st.toast(plan["narration"], icon="✨")
                      st.rerun()
              if ss.get("decrees"):
                  last_d = ss.decrees[-1]
                  st.markdown(f'<div style="font-size:12px;color:#c9d3df;border-left:3px solid #8b5cf6;padding:6px 8px;background:#1b2636;border-radius:6px">'
                              f'<b>Day {last_d["day"]}</b> — {esc(last_d["narration"])}<br><span style="color:#8b98a8">{esc(" · ".join(last_d["done"])) or "no effects"}</span></div>', unsafe_allow_html=True)
          pol = w.policy
          laws = "".join(f'<div style="font-size:12px;color:#c9d3df;padding:2px 0">⚖️ {LAW_TEXT[l].split(" — ")[0].capitalize()}</div>' for l in pol.laws) or '<div style="font-size:12px;color:#8b98a8">No emergency laws in force.</div>'
          appr_col = "#4ade80" if pol.approval > 0.5 else ("#eda100" if pol.approval > 0.3 else "#f87171")
          st.markdown(f'<div class="panel"><h4>Government</h4><div style="font-size:14px;color:#fff;font-weight:600">{esc(pol.ruling_party)}</div>'
                      f'<div style="font-size:12px;color:#8b98a8">in office since day {pol.took_office:,} · next election day {w.next_election_day:,}</div>'
                      + bar("Approval", pol.approval, appr_col)
                      + f'<div style="font-size:12px;color:#c9d3df">Tax {pol.tax_rate*100:.0f}% · welfare £{pol.welfare:.0f}/day · pension £{pol.pension:.0f}/day · min wage £{pol.min_wage:.0f}<br>'
                      f'{"Public" if pol.public_education else "Private"} schools · {"public" if pol.public_health else "private"} clinic · treasury £{w.treasury:,.0f}</div><div style="height:6px"></div>{laws}</div>', unsafe_allow_html=True)
          brain_line = f"Brain: <b>{'Claude ✨' if w.brain.name == 'llm' else 'rules'}</b> · {w.brain_calls:,} reactions"
          if hasattr(w.brain, "stats"):
              stt = w.brain.stats()
              brain_line += f" · {stt['calls']} Claude calls ({stt['pending']} thinking) · ~${stt['est_cost_usd']:.2f}"
              if stt["last_error"]:
                  brain_line += f'<br><span style="color:#f87171">{esc(stt["last_error"])}</span>'
          st.markdown(f'<div class="panel" style="font-size:12px;color:#c9d3df">{brain_line}</div>', unsafe_allow_html=True)

      bl, bm, br = st.columns([1, 1, 1.1])
      with bm:
          rows = ""
          for t in w.thoughts[-9:][::-1]:
              spark = "✨ " if t["source"] == "llm" else ""
              rows += f'<div class="ev"><b>Day {t["day"]}</b><span style="color:#eda100">{spark}{esc(t["name"])}</span>: <i>{esc(t["text"])}</i></div>'
          title = "Inner voices" + (" <span style='font-size:11px;color:#4ade80'>✨ = written by Claude</span>" if w.brain.name == "llm" else "")
          st.markdown(f'<div class="panel"><h4>{title}</h4>{rows or "<div class=ev>Nothing on anyone\'s mind yet.</div>"}</div>', unsafe_allow_html=True)
      with bl:
          icons = {"disaster": "🌪️", "politics": "🗳️", "economy": "💰", "life": "🌱", "society": "💍", "social": "💬", "work": "🔧", "discovery": "💡", "founding": "🏛️", "year": "📅", "collapse": "💀", "decree": "✨", "environment": "🌦️"}
          rows = "".join(f'<div class="ev{" big" if e.importance >= 0.55 else ""}"><b>Day {e.day}</b>{esc(e.text)} {icons.get(e.category, "")}</div>' for e in [e for e in w.events if e.importance >= 0.4][-12:][::-1])
          st.markdown(f'<div class="panel"><h4>Recent Events</h4>{rows}</div>', unsafe_allow_html=True)
      with br:
          with st.container(border=True):
              st.markdown("<h4>Key Metrics</h4>", unsafe_allow_html=True)
              metric = st.segmented_control("metric", ["Population", "Wealth", "Happiness", "Food", "Jobs", "Inequality"], default="Population", key="metric_pick", label_visibility="collapsed")
              h = w.metrics_df()
              series = {"Population": [("population", "Population")], "Wealth": [("median_wealth", "Median £"), ("avg_wealth", "Mean £")],
                        "Happiness": [("happiness", "Happiness %"), ("grievance", "Grievance %")], "Food": [("food_price", "Bread £")],
                        "Jobs": [("unemployment", "Unemployment %"), ("businesses", "Businesses")], "Inequality": [("gini", "Gini")]}[metric or "Population"]
              fig = go.Figure()
              for i, (k, name) in enumerate(series):
                  fig.add_trace(go.Scatter(x=h.day, y=h[k], mode="lines", name=name, line=dict(width=2, color=SERIES[i])))
              fig.update_layout(height=230, showlegend=len(series) > 1, **PLOT)
              st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


  if page == PAGES[0]:
      st.fragment(run_every=tick_interval())(world_page)()

  # ------------------------------------------------------------------ CITIZENS
  if page == PAGES[1]:
      df = w.citizens_df()
      c1, c2 = st.columns([1.4, 1])
      with c1:
          st.dataframe(df.drop(columns=["x", "y"]).sort_values("id"), use_container_width=True, height=560, hide_index=True)
      with c2:
          opts = {f"{c.name} (#{c.id}, {c.age_on(w.day)}{'' if c.alive else ', dead'})": c.id for c in sorted(w.citizens.values(), key=lambda c: (not c.alive, c.id))}
          pick = st.selectbox("Full biography", list(opts))
          st.markdown(w.biography(opts[pick]))

  # ------------------------------------------------------------------ ECONOMY
  if page == PAGES[2]:
      e1, e2 = st.columns(2)
      with e1:
          st.markdown("#### Businesses")
          st.dataframe(pd.DataFrame([{"name": b.name, "kind": b.kind, "owner": w.citizens[b.owner_id].name if b.owner_id else "—", "staff": len(b.employees),
                                      "wage": round(b.wage), "cash": round(b.cash), "revenue/day": round(float(np.mean(b.revenue_history[-30:])) if b.revenue_history else 0),
                                      "founded": b.founded_day, "open": b.alive} for b in w.businesses.values()]).sort_values(["open", "cash"], ascending=False),
                       hide_index=True, use_container_width=True, height=380)
          money = np.array([c.money for c in alive])
          if len(money):
              fig = go.Figure(go.Histogram(x=money, nbinsx=30, marker=dict(color=SERIES[0])))
              fig.update_layout(height=220, xaxis_title="£", yaxis_title="people", **{**PLOT, "hovermode": "x"})
              st.markdown("#### Wealth distribution")
              st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
              top10 = np.sort(money)[-max(1, len(money) // 10):].sum() / max(1, money.sum())
              st.caption(f"Top 10% hold {top10*100:.0f}% of wealth · Gini {w.gini:.2f} · treasury £{w.treasury:,.0f}")
      with e2:
          h = w.metrics_df()
          for title, series in [("Wealth", [("median_wealth", "Median £"), ("avg_wealth", "Mean £")]), ("Prices & technology", [("food_price", "Bread £"), ("tech", "Tech ×")]),
                                ("Labour", [("unemployment", "Unemployment %"), ("businesses", "Businesses")]), ("State", [("treasury", "Treasury £")])]:
              fig = go.Figure()
              for i, (k, name) in enumerate(series):
                  fig.add_trace(go.Scatter(x=h.day / 365, y=h[k], mode="lines", name=name, line=dict(width=2, color=SERIES[i])))
              fig.update_layout(height=190, title=dict(text=title, font=dict(size=13)), showlegend=len(series) > 1, **{**PLOT, "margin": dict(l=8, r=8, t=30, b=8)})
              st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

  # ------------------------------------------------------------------ POLITICS
  if page == PAGES[3]:
      a, b = st.columns(2)
      with a:
          st.markdown("#### Political landscape")
          adults = w.adults()
          if adults:
              movs = {m.id: m for m in w.movements.values() if m.alive}
              fig = go.Figure()
              groups = {"Unaffiliated": [c for c in adults if not c.movement_id]}
              for m in movs.values():
                  groups[m.name] = [c for c in adults if c.movement_id == m.id]
              for i, (name, cs) in enumerate(groups.items()):
                  if cs:
                      fig.add_trace(go.Scatter(x=[c.beliefs["economic"] for c in cs], y=[c.beliefs["authority"] for c in cs], mode="markers", name=name,
                                               marker=dict(size=8, color=SERIES[i % len(SERIES)] if i else "#6b7785", opacity=0.85),
                                               text=[f"{c.name}<br>grievance {c.grievance*100:.0f}%" for c in cs], hoverinfo="text"))
              for i, m in enumerate(movs.values(), start=1):
                  fig.add_trace(go.Scatter(x=[m.platform["economic"]], y=[m.platform["authority"]], mode="markers+text", text=[m.name], textposition="top center",
                                           marker=dict(symbol="star", size=18, color=SERIES[i % len(SERIES)], line=dict(width=1, color="#111")), showlegend=False, hoverinfo="skip"))
              fig.update_layout(height=400, **{**PLOT, "hovermode": "closest", "xaxis": dict(title="← redistribution · markets →", range=[-1.05, 1.05], gridcolor="#1f2a3a"),
                                               "yaxis": dict(title="← liberty · order →", range=[-1.05, 1.05], gridcolor="#1f2a3a")})
              st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
          pol = w.policy
          st.markdown(f"**{pol.ruling_party}** — tax {pol.tax_rate*100:.0f}% · welfare £{pol.welfare:.0f}/day · pension £{pol.pension:.0f}/day · min wage £{pol.min_wage:.0f} · "
                      f"{'public' if pol.public_education else 'private'} schools · {'public' if pol.public_health else 'private'} clinic · next election day {w.next_election_day:,}")
          if w.movements:
              st.dataframe(pd.DataFrame([{"name": m.name, "founder": w.citizens[m.founder_id].name, "founded": m.founded_day, "against": m.grievance_theme,
                                          "members": len(m.members), "party": m.is_party, "active": m.alive, "economic": round(m.platform["economic"], 2),
                                          "last votes": m.seats_won} for m in w.movements.values()]), hide_index=True, use_container_width=True)
      with b:
          st.markdown("#### Social graph")
          g = w.social_graph()
          if g.number_of_nodes() > 1:
              pos = nx.spring_layout(g, seed=1, k=0.6, weight=None)
              fig = go.Figure()
              for sign, colour, name in [(1, "rgba(59,130,246,0.35)", "friendship"), (-1, "rgba(239,68,68,0.6)", "enmity")]:
                  xs, ys = [], []
                  for u, v, d in g.edges(data=True):
                      if (d["weight"] > 0) == (sign > 0):
                          xs += [pos[u][0], pos[v][0], None]; ys += [pos[u][1], pos[v][1], None]
                  fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", line=dict(width=1.2, color=colour), hoverinfo="skip", name=name))
              nodes = list(g.nodes)
              fig.add_trace(go.Scatter(x=[pos[n][0] for n in nodes], y=[pos[n][1] for n in nodes], mode="markers",
                                       marker=dict(size=[6 + 2 * min(8, g.degree(n)) for n in nodes],
                                                   color=[SERIES[(w.citizens[n].movement_id or 0) % len(SERIES)] if w.citizens[n].movement_id else "#6b7785" for n in nodes],
                                                   line=dict(width=0.5, color="#111")),
                                       text=[f"{w.citizens[n].name}<br>{g.degree(n)} ties" for n in nodes], hoverinfo="text", name="citizens"))
              fig.update_layout(height=400, **{**PLOT, "hovermode": "closest", "xaxis": dict(visible=False), "yaxis": dict(visible=False)})
              st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
              st.caption(f"{g.number_of_nodes()} people · {sum(1 for _,_,d in g.edges(data=True) if d['weight']>0)} friendships · {sum(1 for _,_,d in g.edges(data=True) if d['weight']<0)} feuds · node colour = movement")
          h = w.metrics_df()
          fig = go.Figure()
          for i, (k, name) in enumerate([("grievance", "Grievance %"), ("movements", "Movements"), ("tax_rate", "Tax rate")]):
              fig.add_trace(go.Scatter(x=h.day / 365, y=h[k] * (100 if k == "tax_rate" else 1), mode="lines", name=name if k != "tax_rate" else "Tax %", line=dict(width=2, color=SERIES[i])))
          fig.update_layout(height=200, **PLOT)
          st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

  # ------------------------------------------------------------------ EVENTS
  if page == PAGES[4]:
      e1, e2 = st.columns([1.2, 1])
      with e1:
          text = chronicle_text(w)
          st.markdown(text)
          st.download_button("Download chronicle.md", text, "chronicle.md")
          if st.button("🎬 Narrate the documentary (one API call)"):
              try:
                  from civilisation.llm import narrate
                  with st.spinner("Writing the documentary…"):
                      ss.narration = narrate(w, backend=host_backend())
              except Exception as e:
                  st.error(f"Could not narrate: {e}")
          if ss.get("narration"):
              st.markdown("---"); st.markdown(ss.narration)
      with e2:
          st.markdown("#### Session log")
          with st.expander(f"Decrees this session ({len(ss.get('decrees') or [])})", expanded=bool(ss.get("decrees"))):
              for d in (ss.get("decrees") or [])[::-1]:
                  st.markdown(f"**Day {d['day']}** · *you:* {d['text']}  \n*fate:* {d['narration']}  \n`{' · '.join(d['done']) or 'no effects'}`")
          if hasattr(w.brain, "stats"):
              st.json(w.brain.stats())
          st.caption(f"Session {ss.sid} · world seed {w.seed} · day {w.day:,} · brain {w.brain.name} · {w.brain_calls:,} reactions · "
                     f"{'strike on' if w.strike else 'no strike'} · {'pandemic on' if w.pandemic else 'no pandemic'} · drought {w.drought_days}d · recession {w.recession_days}d")
          if PUBLIC:
              store = shared["store"]
              rec = shared.get("recorder")
              st.markdown(f"#### Persistent log — {store.status()}" + (" · restored from snapshot" if shared.get("restored") else "") +
                          (f" · <span style='color:#f87171'>{esc(rec.last_error)}</span>" if rec and rec.last_error else ""), unsafe_allow_html=True)
              try:
                  min_imp = st.slider("Minimum importance", 0.0, 1.0, 0.5, 0.05, key="log_min_imp")
                  ev = store.read_events(VILLAGE, limit=400, min_importance=min_imp)
                  if ev:
                      st.dataframe(pd.DataFrame(ev), hide_index=True, use_container_width=True, height=320)
                  hist = store.read_metrics(VILLAGE, limit=5000)
                  if hist:
                      hd = pd.DataFrame(hist)
                      fig = go.Figure()
                      for i, (k, name) in enumerate([("population", "Population"), ("gini", "Gini ×100"), ("grievance", "Grievance %")]):
                          fig.add_trace(go.Scatter(x=hd.day / 365, y=hd[k] * (100 if k == "gini" else 1), mode="lines", name=name, line=dict(width=2, color=SERIES[i])))
                      fig.update_layout(height=220, title=dict(text="Whole recorded history", font=dict(size=13)), **{**PLOT, "margin": dict(l=8, r=8, t=30, b=8)})
                      st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
                  dec = store.read_decrees(VILLAGE, limit=50)
                  if dec:
                      with st.expander(f"All decrees ever ({len(dec)} shown)"):
                          st.dataframe(pd.DataFrame(dec), hide_index=True, use_container_width=True)
              except Exception as e:
                  st.error(f"store read failed: {e}")
          st.markdown("#### Full event log")
          st.dataframe(w.events_df(400)[["day", "category", "importance", "text", "brain"]], hide_index=True, use_container_width=True, height=700)

  # ------------------------------------------------------------------ RESEARCH

  if page == PAGES[5]:
      rid = ss.get("resident_id")
      if rid and rid not in w.citizens:
          rid = ss.resident_id = None
      m1, m2 = st.columns([1, 1.1])
      with m1:
          if not rid:
              st.markdown("#### Move your own person into the village")
              st.caption("Give them a name, a temperament and a story. Bring your own key (any provider) and *they* think with your model — "
                         "their reactions cost you, not the host. Keys stay in server memory for this run only (encrypted at rest if the host set a secret). "
                         + ("You're in the **public village**, so everyone here will meet them." if PUBLIC else "You're in a private world — switch to the public village in Settings if you want others to meet them."))
              with st.form("move_in", border=True):
                  name = st.text_input("Name", placeholder="Ada Okonkwo")
                  c1, c2, c3 = st.columns(3)
                  sex = c1.selectbox("Sex", ["F", "M"])
                  age = c2.number_input("Age", 18, 70, 28)
                  sponsor = c3.text_input("Your name (shown as sponsor)", placeholder="om")
                  backstory = st.text_area("Who are they?", placeholder="A blacksmith's daughter who left the city after a scandal. Quick to laugh, quicker to argue, secretly wants to run the tavern.", height=90)
                  st.markdown("<div style='font-size:12px;color:#8b98a8'>Temperament</div>", unsafe_allow_html=True)
                  t1, t2 = st.columns(2)
                  openness = t1.slider("Curious ↔ traditional", 0.0, 1.0, 0.6)
                  consc = t2.slider("Impulsive ↔ diligent", 0.0, 1.0, 0.5)
                  extra = t1.slider("Quiet ↔ gregarious", 0.0, 1.0, 0.6)
                  agree = t2.slider("Abrasive ↔ kind", 0.0, 1.0, 0.5)
                  neuro = t1.slider("Steady ↔ anxious", 0.0, 1.0, 0.4)
                  st.markdown("<div style='font-size:12px;color:#8b98a8;margin-top:6px'>Their mind (optional — leave blank for the rules brain)</div>", unsafe_allow_html=True)
                  p1, p2 = st.columns(2)
                  prov_opts = [k for k in PROVIDERS if allow_custom_providers() or k not in ("custom", "ollama")]
                  r_prov = p1.selectbox("Provider", prov_opts, format_func=lambda k: k)
                  r_model = p2.text_input("Model", value="", placeholder="default for provider", max_chars=60)
                  r_key = st.text_input("Your API key", type="password", help="Use a separate, spend-capped key for this.")
                  r_base = st.text_input("Base URL (custom provider only: https, public hosts; the server must set ALLOW_CUSTOM_PROVIDERS)", value="", max_chars=200)
                  r_max = st.number_input("Max calls you'll pay for", 10, 5000, 200)
                  st.markdown("<div style='font-size:12px;color:#8b98a8;margin-top:6px'>Your key</div>", unsafe_allow_html=True)
                  r_ttl = st.select_slider("Keep it in server memory for", options=[1, 6, 24, 72], value=24, format_func=lambda h: f"{h} h")
                  r_remember = st.checkbox("Remember my key on this server (encrypted with the host's secret) so my person keeps thinking after restarts and after the timer",
                                           value=False, disabled=not bool(os.environ.get("APP_SECRET")))
                  st.caption("By default the key is held in memory only — never written anywhere — and forgotten after the timer or a restart; "
                             "your person then carries on with the rules brain until you come back and enter it again. Use a separate, spend-capped key.")
                  go_in = st.form_submit_button("Move in 🏡", type="primary", use_container_width=True)
              if go_in:
                  if not name.strip():
                      st.error("They need a name.")
                  elif PUBLIC and sum(1 for c in w.citizens.values() if c.sponsor and c.alive) >= int(os.environ.get("MAX_RESIDENTS", 60)):
                      st.error("The village is full for now.")
                  else:
                      brain = None
                      if r_key.strip() or r_prov in ("ollama", "custom"):
                          try:
                              from civilisation.llm import LLMBrain
                              be = make_backend(r_prov, r_model.strip() or PROVIDERS[r_prov][1], api_key=r_key.strip() or None, base_url=r_base.strip() or None)
                              be.ping()
                              brain = LLMBrain(threshold=0.45, max_calls=int(r_max), backend=be, owner=sponsor.strip() or name.strip())
                              brain.expires_at = None if r_remember else time.time() + int(r_ttl) * 3600
                              brain.remembered = bool(r_remember)
                          except Exception as e:
                              st.error(f"That key/model didn't answer ({scrub(e)}). They'll move in with the rules brain instead.")
                      c = w.adopt(name, sex, int(age), {"openness": openness, "conscientiousness": consc, "extraversion": extra, "agreeableness": agree, "neuroticism": neuro},
                                  backstory=backstory, sponsor=sponsor, brain=brain)
                      token = secrets.token_urlsafe(18)
                      ss.resident_id = c.id; ss.selected = c.id; ss.steward_token = token; ss.sponsor_name = sponsor.strip()
                      if PUBLIC:
                          shared["residents"][c.id] = sponsor.strip() or "anonymous"
                          try:
                              shared["store"].write_resident(VILLAGE, {"citizen_id": c.id, "name": c.name, "sponsor": sponsor.strip(), "provider": r_prov,
                                                                       "model": (r_model.strip() or PROVIDERS[r_prov][1]), "base_url": r_base.strip() or None,
                                                                       "enc_key": encrypt_key(r_key.strip()) if (brain and r_remember) else None, "max_calls": int(r_max), "token_hash": token_hash(token)})
                              shared["recorder"].flush(w, force_snapshot=True)
                          except Exception as e:
                              st.warning(f"Saved in memory but not to the store: {e}")
                      st.rerun()
              st.markdown("#### Already have a person here?")
              claim = st.text_input("Paste your claim token", type="password", key="claim_box", max_chars=100)
              if st.button("Claim") and claim.strip() and PUBLIC:
                  if not limiters()["claim"].allow(ss.sid):
                      st.error("Too many attempts. Try again later."); st.stop()
                  limiters()["claim"].hit(ss.sid)
                  th = token_hash(claim.strip())
                  hit = next((r for r in shared["store"].read_residents(VILLAGE) if r.get("token_hash") == th), None)
                  if hit and int(hit["citizen_id"]) in w.citizens:
                      ss.resident_id = int(hit["citizen_id"]); ss.steward_token = claim.strip(); ss.selected = ss.resident_id; st.rerun()
                  else:
                      st.error("No person matches that token.")
          else:
              c = w.citizens[rid]
              brain = w.brains.get(rid)
              st.markdown(f"#### You are the steward of {c.name}")
              if ss.get("steward_token"):
                  st.info(f"Your claim token — keep it, it is the only way back to {c.name.split()[0]} from another device:\n\n`{ss.steward_token}`\n\nPaste it into the claim box when you return (avoid putting it in a URL you might share).")
              if not c.alive:
                  st.error(f"{c.name} died on day {c.died_day} of {c.cause_of_death}. You can move a new person in.")
                  if st.button("Let them go"):
                      ss.resident_id = None; ss.steward_token = None; st.rerun()
              else:
                  emp = w.businesses.get(c.employer_id) if c.employer_id else None
                  st.markdown(f"<div style='font-size:13px;color:#c9d3df'>{', '.join(describe(c)).capitalize()} · {job_label(w, c.job)}{' at ' + esc(emp.name) if emp else ''} · £{c.money:,.0f} · "
                              f"happiness {c.happiness*100:.0f}% · goal: {esc(c.goal)} ({c.goal_progress*100:.0f}%)"
                              + (f" · married to {esc(w.citizens[c.spouse_id].name)}" if c.spouse_id else "") + (f" · {esc(w.movements[c.movement_id].name)}" if c.movement_id else "") + "</div>", unsafe_allow_html=True)
                  st.markdown(f"<div style='margin:8px 0;padding:8px 10px;border-left:3px solid #eda100;background:#1b2636;border-radius:6px;font-size:13px;font-style:italic'>“{esc(thought(w, c))}”</div>", unsafe_allow_html=True)

                  def run_plan(plan, label):
                      done = apply_person_plan(w, c, plan)
                      ss.steward_log = (ss.get("steward_log") or [])[-30:] + [{"day": w.day, "what": label, "done": done}]
                      if PUBLIC:
                          try:
                              shared["store"].write_decree(VILLAGE, {"day": w.day, "text": f"[{c.name}] {label}", "narration": "; ".join(done), "done": done, "session": ss.sid, "sponsor": c.sponsor})
                          except Exception:
                              pass
                      st.toast(" · ".join(done) or "nothing happened", icon="🏡")

                  if brain is not None:
                      stt = brain.stats()
                      if stt.get("remembered"):
                          key_line = "🔐 key stored encrypted on this server"
                      elif stt.get("expires_at"):
                          key_line = f"🕒 key in memory only — forgotten in {max(0, (stt['expires_at'] - time.time()) / 3600):.1f} h or at the next restart"
                      else:
                          key_line = "key in memory only"
                      kc1, kc2 = st.columns([3, 1])
                      kc1.caption(f"Mind: {stt['provider']}/{clean_text(stt['model'], 60)} · {key_line}")
                      if kc2.button("Forget my key", use_container_width=True):
                          brain.forget_key(); w.brains.pop(rid, None)
                          if PUBLIC:
                              try:
                                  shared["store"].update_resident(VILLAGE, rid, enc_key=None)
                              except Exception:
                                  pass
                          st.rerun()
                  else:
                      with st.expander("Give them a mind again (enter your key — memory only)"):
                          with st.form("rekey", clear_on_submit=True, border=False):
                              rk1, rk2 = st.columns(2)
                              k_prov = rk1.selectbox("Provider", [k for k in PROVIDERS if allow_custom_providers() or k not in ("custom", "ollama")], format_func=lambda k: k)
                              k_model = rk2.text_input("Model", value="", placeholder="default for provider")
                              k_key = st.text_input("API key", type="password")
                              k_ttl = st.select_slider("Keep in memory for", options=[1, 6, 24, 72], value=24, format_func=lambda h: f"{h} h")
                              rekey = st.form_submit_button("Wake them up")
                          if rekey and (k_key.strip() or k_prov in ("ollama", "custom")):
                              try:
                                  from civilisation.llm import LLMBrain
                                  be = make_backend(k_prov, k_model.strip() or PROVIDERS[k_prov][1], api_key=k_key.strip() or None)
                                  be.ping()
                                  nb = LLMBrain(threshold=0.45, max_calls=300, backend=be, owner=c.sponsor)
                                  nb.expires_at = time.time() + int(k_ttl) * 3600
                                  w.brains[rid] = nb
                                  st.rerun()
                              except Exception as e:
                                  st.error(f"Didn't answer: {scrub(e)}")
                  st.markdown("**Tell them what to do**")
                  with st.form("instruct", clear_on_submit=True, border=False):
                      instr = st.text_area("Instruction", placeholder="Get a better-paid job · Court Otto Petrov · Save up and open a tavern · Join the Workers' Circle · Make peace with your brother", label_visibility="collapsed", height=70)
                      sent = st.form_submit_button("Send", use_container_width=True, type="primary")
                  instr = clean_text(instr, 1000)
                  wait_s = limiters()["instruct"].cooldown(f"instr:{ss.sid}", 8.0)
                  if sent and instr.strip() and wait_s > 0:
                      st.warning(f"Give {c.name.split()[0]} a moment — try again in {wait_s:.0f}s.")
                  elif sent and instr.strip():
                      limiters()["instruct"].hit(f"instr:{ss.sid}")
                      plan = None
                      if brain is not None:
                          try:
                              with st.spinner(f"{c.name.split()[0]} is thinking…"):
                                  plan = interpret_person(w, c, instr.strip(), brain.backend)
                          except Exception as e:
                              st.error(f"Their mind didn't answer ({scrub(e)}); trying the simple parser.")
                      if plan is None:
                          plan = rules_interpret_person(w, c, instr.strip())
                          if plan is None:
                              st.warning("Without a model of their own, only simple verbs work: get a job, quit, open a tavern, move, join, or a goal name.")
                      if plan:
                          if plan.get("reply"):
                              w.think(c, plan["reply"], "llm" if brain is not None else "rules", "neutral")
                              st.markdown(f"<div style='font-size:13px;color:#e6edf3;font-style:italic'>“{esc(plan['reply'][:600])}”</div>", unsafe_allow_html=True)
                          run_plan(plan, instr.strip())

                  with st.expander("Standing instructions (how they should carry themselves)"):
                      notes = st.text_area("Notes", value=c.backstory, height=80, label_visibility="collapsed",
                                           help="This is part of who they are; their model reads it before every reaction.")
                      if st.button("Save notes"):
                          c.backstory = notes.strip()[:600]
                          if PUBLIC:
                              try:
                                  shared["store"].update_resident(VILLAGE, c.id, notes=c.backstory)
                              except Exception:
                                  pass
                          st.success("Saved.")

                  with st.expander("Direct actions", expanded=True):
                      g1, g2 = st.columns([2, 1])
                      goal = g1.selectbox("Goal", ADULT_GOALS, index=ADULT_GOALS.index(c.goal) if c.goal in ADULT_GOALS else 0)
                      if g2.button("Set goal", use_container_width=True):
                          run_plan({"effects": [{"op": "goal", "params": {"goal": goal}}]}, f"goal → {goal}")
                      st.markdown("<div style='font-size:12px;color:#8b98a8'>Work</div>", unsafe_allow_html=True)
                      bs = [b for b in w.open_businesses() if b.id != c.employer_id]
                      w1, w2, w3 = st.columns([2, 1, 1])
                      target = w1.selectbox("Business", bs, format_func=lambda b: f"{b.name} · £{b.wage:.0f}/day · {len(b.employees)} staff", label_visibility="collapsed") if bs else None
                      if w2.button("Apply", use_container_width=True, disabled=target is None):
                          run_plan({"effects": [{"op": "work", "params": {"action": "apply", "business": target.name}}]}, f"apply at {target.name}")
                      if w3.button("Quit job", use_container_width=True, disabled=c.employer_id is None):
                          run_plan({"effects": [{"op": "work", "params": {"action": "quit"}}]}, "quit")
                      f1, f2 = st.columns([2, 1])
                      kind = f1.selectbox("Found a business", list(economy.JOB_FOR_KIND), format_func=lambda k: f"{k} (£{w.config['startup_cost']*1.1:,.0f} needed)", label_visibility="collapsed")
                      if f2.button("Found it", use_container_width=True, disabled=c.money < w.config["startup_cost"] * 1.1):
                          run_plan({"effects": [{"op": "work", "params": {"action": "found", "kind": kind}}]}, f"found a {kind}")
                      st.markdown("<div style='font-size:12px;color:#8b98a8'>People</div>", unsafe_allow_html=True)
                      known = sorted([x for x in w.alive() if x.id != c.id], key=lambda x: -abs(c.rel(x.id).score) if x.id in c.relationships else 0)
                      who = st.selectbox("Person", known, format_func=lambda x: f"{x.name} · {x.rel(c.id).kind} {c.rel(x.id).score:+.0f}" if x.id in c.relationships else f"{x.name} · stranger", label_visibility="collapsed")
                      a1, a2, a3, a4 = st.columns(4)
                      if a1.button("Visit", use_container_width=True):
                          run_plan({"effects": [{"op": "visit", "params": {"who": who.name}}]}, f"visit {who.name}")
                      if a2.button("Confront", use_container_width=True):
                          run_plan({"effects": [{"op": "confront", "params": {"who": who.name}}]}, f"confront {who.name}")
                      if a3.button("Persuade", use_container_width=True):
                          run_plan({"effects": [{"op": "persuade", "params": {"who": who.name}}]}, f"persuade {who.name}")
                      if a4.button("Propose", use_container_width=True, disabled=bool(c.spouse_id)):
                          run_plan({"effects": [{"op": "propose", "params": {"who": who.name}}]}, f"propose to {who.name}")
                      gv1, gv2 = st.columns([2, 1])
                      amt = gv1.number_input("Give £", 1, int(max(1, c.money)), min(50, int(max(1, c.money))), label_visibility="collapsed")
                      if gv2.button("Give", use_container_width=True, disabled=c.money < 1):
                          run_plan({"effects": [{"op": "give", "params": {"who": who.name, "amount": amt}}]}, f"give £{amt} to {who.name}")
                      st.markdown("<div style='font-size:12px;color:#8b98a8'>Politics & home</div>", unsafe_allow_html=True)
                      movs = [m for m in w.movements.values() if m.alive]
                      p1, p2, p3 = st.columns([2, 1, 1])
                      mv = p1.selectbox("Movement", movs, format_func=lambda m: f"{m.name} · {len(m.members)} · against {m.grievance_theme}", label_visibility="collapsed") if movs else None
                      if p2.button("Join", use_container_width=True, disabled=mv is None):
                          run_plan({"effects": [{"op": "movement", "params": {"action": "join", "name": mv.name}}]}, f"join {mv.name}")
                      if p3.button("Leave", use_container_width=True, disabled=c.movement_id is None):
                          run_plan({"effects": [{"op": "movement", "params": {"action": "leave"}}]}, "leave movement")
                      n1, n2, n3 = st.columns([1.5, 1.5, 1])
                      mname = n1.text_input("New movement name", placeholder="Riverside Union", label_visibility="collapsed")
                      mtheme = n2.text_input("Against", placeholder="the price of bread", label_visibility="collapsed")
                      if n3.button("Found", use_container_width=True, disabled=c.movement_id is not None or not mname.strip()):
                          run_plan({"effects": [{"op": "movement", "params": {"action": "found", "name": mname.strip(), "theme": mtheme.strip() or "hardship"}}]}, f"found {mname.strip()}")
                      h1_, h2_ = st.columns([2, 1])
                      near = h1_.selectbox("Move near", [None] + known, format_func=lambda x: "anywhere" if x is None else x.name, label_visibility="collapsed")
                      if h2_.button("Move house", use_container_width=True):
                          run_plan({"effects": [{"op": "move", "params": {"near": near.name if near else ""}}]}, "move house")
                  if st.button("Leave town for good (remove your person)"):
                      from civilisation.systems.lifecycle import die
                      die(w, c, "left town")
                      ss.resident_id = None; ss.steward_token = None; st.rerun()
      with m2:
          if rid and rid in w.citizens:
              c = w.citizens[rid]
              brain = w.brains.get(rid)
              st.markdown(f"#### {c.name}'s diary")
              if brain is not None:
                  stt = brain.stats()
                  st.caption(f"Mind: {stt['provider']}/{clean_text(stt['model'], 60)} · {stt['calls']} calls · ~${stt['est_cost_usd']:.3f}" + (f" · last error: {stt['last_error']}" if stt['last_error'] else ""))
              else:
                  st.caption("Mind: rules brain (add a key when moving in to give them one)")
              mine = [t for t in w.thoughts if t["cid"] == rid][-14:][::-1]
              for t in mine:
                  st.markdown(f"<div class='mem'><b>Day {t['day']}</b>{'✨ ' if t['source']=='llm' else ''}<i>{esc(t['text'])}</i></div>", unsafe_allow_html=True)
              if not mine:
                  st.caption("Nothing yet — let a few days pass.")
              if ss.get("steward_log"):
                  with st.expander("What you made them do"):
                      for e in ss.steward_log[::-1]:
                          st.markdown(f"<div class='mem'><b>Day {e['day']}</b>{esc(e['what'])} → <span style='color:#8b98a8'>{esc(' · '.join(e['done']))}</span></div>", unsafe_allow_html=True)
              with st.expander("Full biography"):
                  st.markdown(w.biography(rid))
          st.markdown("#### Residents")
          sponsored = [c for c in w.citizens.values() if c.sponsor]
          if sponsored:
              st.dataframe(pd.DataFrame([{"name": c.name, "sponsor": c.sponsor, "age": c.age_on(w.day), "job": job_label(w, c.job), "alive": c.alive,
                                          "mind": f"{w.brains[c.id].provider}/{w.brains[c.id].model}" if c.id in w.brains else "rules",
                                          "friends": sum(1 for r in c.relationships.values() if r.score >= 40)} for c in sponsored]),
                           hide_index=True, use_container_width=True)
          else:
              st.caption("Nobody has moved in yet.")

  if page == PAGES[6]:
      st.markdown("Run scenarios across many seeds and compare **distributions** of outcomes — this is the point of the project.")
      chosen = st.multiselect("Scenarios", list(SCENARIOS), default=["baseline", "automation"])
      c1, c2, c3 = st.columns(3)
      seeds = c1.slider("Seeds per scenario", 2, 30, 6)
      years = c2.slider("Years", 2, 60, 15)
      workers = c3.slider("Parallel workers", 1, 8, 4)
      if st.button("Run experiment", type="primary") and chosen:
          with st.spinner(f"Running {len(chosen)*seeds} worlds for {years} years each…"):
              ss.exp = compare(chosen, seeds=range(seeds), years=years, workers=workers)
      df = ss.get("exp")
      if df is not None:
          st.dataframe(summary(df), use_container_width=True)
          cols = st.columns(2)
          for i, mtr in enumerate(["population", "median_wealth", "gini", "unemployment", "happiness", "grievance", "parties", "deaths"]):
              fig = go.Figure()
              for j, sc in enumerate(df.scenario.unique()):
                  fig.add_trace(go.Box(y=df[df.scenario == sc][mtr], name=sc, marker=dict(color=SERIES[j % len(SERIES)]), boxpoints="all", jitter=0.4, pointpos=0))
              fig.update_layout(title=dict(text=mtr, font=dict(size=13)), height=280, showlegend=False, **{**PLOT, "hovermode": "closest", "margin": dict(l=8, r=8, t=30, b=8)})
              cols[i % 2].plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
          st.download_button("Download raw results.csv", df.to_csv(index=False), "results.csv")

  # ------------------------------------------------------------------ SETTINGS
  if page == PAGES[7]:
      s1, s2 = st.columns(2)
      with s1:
          seed = st.number_input("Seed", 0, 999999, w.seed)
          pop = st.number_input("Founding population", 20, 400, 100, step=10)
          era_pick = st.selectbox("Era", list(ERAS), index=list(ERAS).index(w.config.get("era", "medieval")),
                                  format_func=lambda k: f"{ERAS[k]['label']} — from {ERAS[k]['start_year'] if ERAS[k]['start_year'] > 0 else str(-ERAS[k]['start_year']) + ' BC'}: {ERAS[k]['blurb']}")
          st.markdown("#### Which world")
          mode = st.radio("mode", ["Private world (yours alone)", "Public village (shared with everyone on this server; ticks on its own)"],
                          index=1 if PUBLIC else 0, label_visibility="collapsed")
          want_public = mode.startswith("Public")
          if want_public != PUBLIC:
              ss.mode = "public" if want_public else "private"
              ss.playing = False
              ss.pop("iso_html", None)
              st.rerun()
          if PUBLIC:
              st.markdown("#### God login")
              if not ADMIN_PASSWORD:
                  st.warning("No ADMIN_PASSWORD is set. " + ("On this production server that means NOBODY can control the civilisation — set it in the environment." if IN_PRODUCTION else "Locally that means everyone is god; set it before opening the village to others."))
              elif ss.get("is_god"):
                  st.success("You are the god of this village.")
                  if st.button("Step down"):
                      ss.is_god = False; st.rerun()
              else:
                  pw = st.text_input("Password", type="password", key="god_pw", max_chars=200)
                  if st.button("Ascend") and pw:
                      if not limiters()["god"].allow(ss.sid):
                          st.error("Too many attempts. Try again later.")
                      else:
                          limiters()["god"].hit(ss.sid)
                          time.sleep(0.8)
                          if hmac.compare_digest(pw.encode(), ADMIN_PASSWORD.encode()):
                              ss.is_god = True; st.rerun()
                          else:
                              st.error("Not today.")
          if PUBLIC and IS_GOD:
              st.caption(f"Storage: **{shared['store'].status()}** · village '{VILLAGE}' · " + ("restored from snapshot · " if shared.get("restored") else "") +
                         f"{shared['recorder'].writes} flushes" + (f" · notes: {scrub('; '.join(shared['notes']))}" if shared.get("notes") else ""))
              c1, c2 = st.columns(2)
              shared["tick_seconds"] = c1.slider("Seconds per day (public village)", 1.0, 30.0, float(shared["tick_seconds"]), 1.0)
              shared["days_per_tick"] = int(c2.select_slider("Days per tick", [1, 7, 30], value=shared["days_per_tick"]))
              if shared.get("error"):
                  st.error(shared["error"])
          rend = st.radio("Renderer", ["3D (three.js, needs internet for the library)", "Classic isometric canvas"], index=1 if ss.get("renderer") == "classic" else 0, horizontal=True)
          new_r = "classic" if rend.startswith("Classic") else "3d"
          if new_r != ss.get("renderer", "3d"):
              ss.renderer = new_r
              ss.pop("iso_html", None)
              st.rerun()
          st.markdown("#### The mind behind the citizens")
          prov = st.selectbox("Provider", list(PROVIDERS), index=list(PROVIDERS).index(ss.get("provider", "anthropic")),
                              format_func=lambda k: f"{k} — {PROVIDERS[k][3]}")
          if prov != ss.get("provider"):
              ss.provider = prov
              ss.llm_model = PROVIDERS[prov][1]
          ss.llm_model = st.text_input("Model", value=ss.get("llm_model") or PROVIDERS[prov][1])
          if prov == "custom":
              ss.base_url = st.text_input("Base URL (OpenAI-compatible)", value=ss.get("base_url", ""))
          env = PROVIDERS[prov][2]
          ss.api_key = st.text_input("API key", value=ss.get("api_key", ""), type="password",
                                     help=f"Kept only in this browser session. Leave blank to use {env} from the environment." if env else "Not needed for this provider.")
          cfg = host_cfg()
          has_key = cfg["has_key"]
          use_llm = st.toggle("Citizens think with this model for important events", value=has_key,
                              help="Each important event becomes one small structured call: emotion, memory in their own voice, relationship changes, an action. Answers land a day or two later so play stays smooth.")
          if use_llm:
              ss.llm_threshold = st.slider("Importance threshold (lower = more calls)", 0.4, 1.0, ss.get("llm_threshold", 0.6), 0.05)
              ss.llm_max = st.number_input("Max calls per world", 1, 5000, ss.get("llm_max", 300))
              st.caption("Rough guide: at threshold 0.6 a year of 100 citizens is ~150 calls — under a dollar on most models, free on Ollama.")
              if not has_key:
                  st.warning("No key found — the toggle will fall back to the rules brain.")
          k1, k2 = st.columns(2)
          if k1.button("Test key", disabled=not has_key):
              try:
                  st.success(host_backend().ping())
              except Exception as e:
                  st.error(f"Rejected: {e}")
          if k2.button("Use this model for the current world now", disabled=not (use_llm and has_key and IS_GOD), type="primary"):
              try:
                  w.brain = make_brain()
                  st.success("Switched. From now on, important events go to the model — watch for ✨ in Inner voices.")
              except Exception as e:
                  st.error(f"Could not start the brain: {e}")
          if w.brain.name == "llm" and st.button("Back to the rules brain for this world"):
              from civilisation.brains import RulesBrain
              w.brain = RulesBrain()
              st.rerun()
          st.markdown("#### New world")
          if PUBLIC and not IS_GOD:
              st.caption("Creating a world here makes a private one; the public village is the god's.")
          if st.button("↻ Create world", type="primary"):
              ss.world = new_world(int(seed), int(pop), use_llm, era_pick); ss.mode = "private"; ss.playing = False; ss.selected = None; ss.pop("iso_html", None); st.rerun()
      with s2:
          if not PUBLIC:
              st.markdown("#### Save / load")
              if st.button("Save world to world.pkl"):
                  w.save("world.pkl"); st.success("Saved.")
              if os.path.exists("world.pkl") and st.button("Load world.pkl"):
                  ss.world = World.load("world.pkl"); ss.playing = False; ss.pop("iso_html", None); st.rerun()
          st.markdown("#### About")
          st.markdown("New Haven v0.2 · deterministic core · optional LLM cognition gated by event importance · MIT")


finally:
  w.lock.release()

# (the World page is a fragment that reruns itself while playing — see world_page)
