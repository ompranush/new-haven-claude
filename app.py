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
from civilisation.realm import ELEMENTS
from civilisation.systems import animals as animal_sys
from civilisation import behaviour


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
  div[data-testid="stSegmentedControl"] button{border-radius:10px;padding:4px 9px;min-height:34px}
  div[data-testid="stSegmentedControl"] button p{font-size:13.5px;white-space:nowrap}
  .brand .t{font-size:21px !important}
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
    return World(seed=seed, population=pop, brain=brain, config={"era": era})


@st.cache_resource(show_spinner="Joining the public village…")
def shared_village():
    """One village for everyone on this server. It ticks on its own thread, persists to the store,
    and restores itself (people, history, sponsored minds) after a restart."""
    from civilisation.llm import LLMBrain
    store = get_store(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "newhaven.db"))
    state = {"running": True, "tick_seconds": float(os.environ.get("TICK_SECONDS", 60)), "days_per_tick": int(os.environ.get("DAYS_PER_TICK", 1)), "error": "", "residents": {},
             "store": store, "restored": False, "notes": []}
    w = None
    try:
        w = restore_world(store, VILLAGE)
    except Exception as e:
        state["notes"].append(f"could not restore snapshot: {e}")
    if w is not None and not hasattr(w, "villages"):
        # a save from before the five villages: carry every adopted person across, keep their tokens
        from civilisation.persistence import migrate_single_village
        try:
            w, moved = migrate_single_village(store, VILLAGE, w, seed=int(os.environ.get("VILLAGE_SEED", 2026)),
                                              population=int(os.environ.get("VILLAGE_POP", 300)), era=os.environ.get("VILLAGE_ERA", "medieval"))
            state["notes"].append(f"migrated to the five villages: {moved} adopted people carried across")
            state["migrated"] = True
        except Exception as e:
            state["notes"].append(f"migration failed, starting fresh: {e}")
            w = None
    if w is None:
        w = World(seed=int(os.environ.get("VILLAGE_SEED", 2026)), population=int(os.environ.get("VILLAGE_POP", 300)), name="New Haven",
              config={"era": os.environ.get("VILLAGE_ERA", "medieval"),
                      "max_population": int(os.environ.get("MAX_POPULATION", 600)),        # per village
                      "max_relationships": int(os.environ.get("MAX_RELATIONSHIPS", 150))})
    else:
        state["restored"] = not state.get("migrated")
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
            if cid in w.animals:
                continue
            if cid in w.citizens and not w.citizens[cid].sponsor:
                w.citizens[cid].sponsor = r.get("sponsor") or "anonymous"   # backfill people who moved in before this was required
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
    if state["restored"]:                      # an older snapshot may carry years of unpruned history
        before = sum(len(c.relationships) for c in w.citizens.values())
        w.prune()
        after = sum(len(c.relationships) for c in w.citizens.values())
        if before != after:
            state["notes"].append(f"tidied on restore: {before - after:,} stale relationships released")
    rec = Recorder(store, VILLAGE,
                   snapshot_every=int(os.environ.get("SNAPSHOT_EVERY_DAYS", 365)),
                   write_interval=float(os.environ.get("WRITE_INTERVAL_SECONDS", 30)),
                   snapshot_interval=float(os.environ.get("SNAPSHOT_INTERVAL_SECONDS", 900)),
                   max_snapshot_mb=float(os.environ.get("MAX_SNAPSHOT_MB", 8)),
                   min_importance=float(os.environ.get("STORE_MIN_IMPORTANCE", 0)))
    rec.prime(w, restored=state["restored"])
    state["recorder"] = rec
    if state.get("migrated"):
        rec.flush(w, force_snapshot=True)      # save the new realm now, so a restart never migrates the old village twice
    import atexit
    atexit.register(lambda: rec.save_now(state["world"], timeout=5.0))     # a graceful shutdown (a redeploy) saves first

    def loop():
        while True:
            time.sleep(state["tick_seconds"])
            if state["running"]:
                try:
                    state["world"].step(state["days_per_tick"])
                    rec.flush(state["world"])
                    state["error"] = ""                # a clean day clears the last complaint
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
    ss.mode = os.environ.get("DEFAULT_MODE", "public")
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
            if r.get("token_hash") == th and (int(r["citizen_id"]) in w.citizens or int(r["citizen_id"]) in w.animals):
                ss.resident_id = int(r["citizen_id"]); ss.steward_token = tok; ss.selected = ss.resident_id
                ss.welcomed = True
                ss.nav = "🏡 Move in"
                break
    st.query_params.clear()
def claim_person(token: str) -> bool:
    """Attach this session to an existing resident. True on success."""
    if not (PUBLIC and token.strip()):
        return False
    if not limiters()["claim"].allow(ss.sid):
        st.error("Too many attempts. Try again later.")
        return False
    limiters()["claim"].hit(ss.sid)
    th = token_hash(clean_text(token, 100))
    hit = next((r for r in shared["store"].read_residents(VILLAGE) if r.get("token_hash") == th), None)
    if hit and (int(hit["citizen_id"]) in w.citizens or int(hit["citizen_id"]) in w.animals):
        ss.resident_id = int(hit["citizen_id"])
        ss.steward_token = token.strip()
        ss.selected = ss.resident_id
        ss.welcomed = True
        ss.nav = "🏡 Move in"
        return True
    st.error("No person matches that token.")
    return False


FONTS = '<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600;9..144,700&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">'

HERO_CSS = """<style>
#hero{position:absolute;inset:0;z-index:3;pointer-events:none;display:flex;flex-direction:column;justify-content:flex-end;
  padding:0 clamp(20px,5vw,56px) clamp(22px,4vw,40px);font-family:Inter,system-ui,sans-serif;color:#e6edf3;
  background:linear-gradient(180deg,rgba(11,18,32,.25) 0%,rgba(11,18,32,0) 28%,rgba(11,18,32,.5) 60%,rgba(11,18,32,.97) 100%),
             linear-gradient(90deg,rgba(11,18,32,.75) 0%,rgba(11,18,32,0) 65%)}
#hero .live{display:inline-flex;align-items:center;gap:9px;width:max-content;font-size:11px;font-weight:600;letter-spacing:.14em;text-transform:uppercase;
  color:#d5e4f7;background:rgba(15,23,42,.55);border:1px solid rgba(148,163,184,.25);backdrop-filter:blur(6px);padding:6px 13px;border-radius:999px}
#hero .dot{width:7px;height:7px;border-radius:50%;background:#4ade80;animation:pulse 2s infinite}
@keyframes pulse{0%{box-shadow:0 0 0 0 rgba(74,222,128,.7)}70%{box-shadow:0 0 0 8px rgba(74,222,128,0)}100%{box-shadow:0 0 0 0 rgba(74,222,128,0)}}
#hero h1{font-family:Fraunces,Georgia,serif;font-weight:700;font-size:clamp(40px,7vw,78px);line-height:.95;letter-spacing:-.02em;
  margin:16px 0 14px;color:#fff;text-shadow:0 2px 30px rgba(0,0,0,.45)}
#hero .lede{max-width:600px;font-size:clamp(14px,1.5vw,17px);line-height:1.6;color:#cdd6e1;margin:0 0 22px}
#hero .stats{display:flex;flex-wrap:wrap;gap:8px}
#hero .s{background:rgba(15,23,42,.6);border:1px solid rgba(148,163,184,.18);backdrop-filter:blur(8px);border-radius:12px;padding:8px 14px;min-width:80px}
#hero .s b{display:block;font-size:20px;font-weight:600;color:#fff;font-variant-numeric:tabular-nums;line-height:1.2}
#hero .s span{font-size:10.5px;color:#93a1b3;text-transform:uppercase;letter-spacing:.09em}
@media (max-width:560px){#hero .s{padding:6px 10px;min-width:0}#hero .s b{font-size:16px}#hero .lede{margin-bottom:14px}}
</style>"""

WELCOME_CSS = """<style>
  .block-container{max-width:1180px !important;margin:0 auto}
  [class*="st-key-card_"]{background:linear-gradient(180deg,#15203a 0%,#111a2a 100%);border:1px solid #22304a;border-radius:18px;
    padding:22px 22px 20px;gap:0.35rem;transition:transform .18s ease,border-color .18s ease,box-shadow .18s ease}
  [class*="st-key-card_"]:hover{transform:translateY(-3px);border-color:#34507a;box-shadow:0 14px 34px -14px rgba(0,0,0,.6)}
  [data-testid="stLayoutWrapper"]:has(> [class*="st-key-card_"]){flex:1}
  [class*="st-key-card_"]{height:100%}
  [class*="st-key-card_"] > div:last-child{margin-top:auto}
  .st-key-card_watch{border-color:#2c4a7c;background:linear-gradient(180deg,#172a4d 0%,#111a2a 100%)}
  .nh-ic{width:44px;height:44px;border-radius:12px;display:flex;align-items:center;justify-content:center;font-size:22px;margin-bottom:12px}
  .nh-t{font-family:Fraunces,Georgia,serif;font-size:22px;font-weight:600;color:#fff;letter-spacing:-.01em;margin-bottom:6px}
  .nh-d{font-family:Inter,system-ui,sans-serif;font-size:14px;line-height:1.55;color:#9fb0c3;min-height:4.7em;margin-bottom:10px}
  [class*="st-key-card_"] button{border-radius:11px;font-weight:600;padding:.55rem 1rem}
  .nh-kicker{font-family:Inter,system-ui,sans-serif;font-size:11px;font-weight:600;letter-spacing:.14em;text-transform:uppercase;color:#7aa2f7;margin:30px 0 10px}
  .nh-feed{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:10px}
  .nh-feed div{font-family:Inter,system-ui,sans-serif;font-size:13.5px;line-height:1.5;color:#cdd6e1;background:#0f1726;border:1px solid #1c2940;
    border-left:3px solid #3b82f6;border-radius:10px;padding:10px 13px}
  .nh-feed b{display:block;font-size:11px;font-weight:600;color:#7aa2f7;letter-spacing:.06em;text-transform:uppercase;margin-bottom:3px}
  .st-key-private_strip{margin-top:26px;background:#0f1726;border:1px dashed #2a3a55;border-radius:16px;padding:16px 20px}
  .nh-p{font-family:Inter,system-ui,sans-serif;font-size:14px;line-height:1.55;color:#9fb0c3}
  .nh-p b{color:#e6edf3}
  .nh-foot{font-family:Inter,system-ui,sans-serif;text-align:center;color:#5d6b7e;font-size:12px;margin:28px 0 8px}
</style>"""


def welcome_screen():
    alive_now = w.alive_all()
    sponsored_all = [c for c in w.citizens.values() if c.sponsor] + [a for a in w.animals.values() if a.sponsor]
    residents = [c for c in sponsored_all if c.alive]
    wars_now = [x for x in w.wars if x.get("active")]
    st.markdown(FONTS + WELCOME_CSS, unsafe_allow_html=True)

    stats = [(f"{len(alive_now):,}", "people"), ("5", "villages"), (f"{sum(a.alive for a in w.animals.values()):,}", "animals"),
             (f"{len(wars_now)}", "wars now" if len(wars_now) != 1 else "war now"),
             (f"{w.day // 365:,}", "years old") if w.day >= 730 else (f"{w.day:,}", "days old")]
    if sponsored_all:
        stats.append((f"{len(residents):,}", "adopted"))
    overlay = FONTS + HERO_CSS + f"""<div id="hero">
      <div class="live"><i class="dot"></i>Live now · {esc(display_year(w))} · day {w.day:,}</div>
      <h1>{esc(w.realm_name)}</h1>
      <div class="lede">Five villages — Sky, Air, Earth, Fire and Water — on one river that is never quite enough. Their people work,
        love, steal, riot and go to war entirely on their own, and somewhere in each village a secret circle keeps the old power.
        Nobody writes the story in advance.</div>
      <div class="stats">{"".join(f'<div class="s"><b>{v}</b><span>{k}</span></div>' for v, k in stats)}</div>
    </div>"""
    if "hero_html" not in ss:              # built once per session: the iframe must not re-mount on every rerun
        ss.hero_html = render_3d(w, None, height=520, overlay=overlay)
    components.html(ss.hero_html, height=524)

    cards = [("watch", "👁", "#1e3a8a", "Watch the village",
              "Follow the town as it lives: the map, its people, the economy, politics and the chronicle. Nothing to sign up for."),
             ("move", "🏡", "#14532d", "Move someone in",
              "A person or an animal, into any of the five villages. Give them a temperament and a past — and, if you like, your own model as a mind."),
             ("claim", "🔑", "#713f12", "Return to your person",
              "Already have someone living here? Paste the claim token you were given when they moved in.")]
    cols = st.columns(3, gap="medium")
    for col, (key, icon, tint, title, desc) in zip(cols, cards):
        with col, st.container(key=f"card_{key}"):
            st.markdown(f'<div class="nh-ic" style="background:{tint}66;border:1px solid {tint}">{icon}</div>'
                        f'<div class="nh-t">{title}</div><div class="nh-d">{desc}</div>', unsafe_allow_html=True)
            if key == "watch":
                if st.button("Enter the village  →", use_container_width=True, type="primary"):
                    ss.welcomed = True
                    st.rerun()
            elif key == "move":
                if st.button("Create a person", use_container_width=True):
                    ss.welcomed = True
                    ss.nav = "🏡 Move in"
                    st.rerun()
            else:
                with st.form("welcome_claim", clear_on_submit=False, border=False):
                    tok = st.text_input("Claim token", type="password", label_visibility="collapsed", placeholder="Claim token", max_chars=100)
                    if st.form_submit_button("Claim", use_container_width=True) and claim_person(tok):
                        st.rerun()

    notable = [e for e in w.events if e.importance >= 0.55 and not e.secret][-4:][::-1]
    if notable:
        st.markdown('<div class="nh-kicker">Lately in the village</div><div class="nh-feed">'
                    + "".join(f"<div><b>Day {e.day:,}{' · ' + esc(w.villages[e.village].name) if e.village >= 0 else ''}</b>{esc(e.text)}</div>" for e in notable)
                    + "</div>", unsafe_allow_html=True)

    with st.container(key="private_strip"):
        d, e = st.columns([3, 1], vertical_alignment="center")
        d.markdown('<div class="nh-p"><b>Or run a world of your own.</b> A private civilisation where you control the weather, '
                   "the economy and the fate of everyone in it. It lives in your browser session only.</div>", unsafe_allow_html=True)
        if e.button("🌍 Create a private world", use_container_width=True):
            ss.mode = "private"
            ss.welcomed = True
            ss.playing = False
            ss.pop("iso_html", None)
            st.rerun()
    st.markdown('<div class="nh-foot">New Haven · five villages, one river · no script, no ending</div>', unsafe_allow_html=True)


w.lock.acquire()          # the public village ticks on another thread; hold it still while we draw
try:
  # which of the five villages this visitor is looking at (their own person's, at first)
  if ss.get("pending_village") is not None:          # set before the picker is drawn (widgets can't be changed after)
      ss.village = ss.pop("pending_village")
  if ss.get("pending_nav"):
      ss.nav = ss.pop("pending_nav")
  if ss.get("village") is None or not (0 <= int(ss.get("village")) < len(w.villages)):
      rid0 = ss.get("resident_id")
      ss.village = w.citizens[rid0].village if rid0 in w.citizens else (w.animals[rid0].village if rid0 in w.animals else 0)
  w.focus = int(ss.village)
  VILLAGE_NOW = w.villages[w.focus]
  if PUBLIC and not ss.get("welcomed"):
      welcome_screen()
      st.stop()
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


  def realm_full():
      """MAX_RESIDENTS caps everyone visitors have moved in — people and animals, across the five villages."""
      moved_in = sum(1 for c in w.citizens.values() if c.sponsor and c.alive) + sum(1 for x in w.animals.values() if x.sponsor and x.alive)
      return PUBLIC and moved_in >= int(os.environ.get("MAX_RESIDENTS", 60))

  def animal_steward(a):
      sp = animal_sys.SPECIES[a.species]
      st.markdown(f"#### You look after {sp['emoji']} {esc(a.name)}")
      if ss.get("steward_token"):
          st.info(f"Your claim token — keep it:\n\n`{ss.steward_token}`")
      owner = w.citizens.get(a.owner_id) if a.owner_id else None
      st.markdown(f"<div style='font-size:13px;color:#c9d3df'>{a.species}, {a.age_on(w.day)} years · {'wild' if a.wild else 'tame'} · "
                  f"{esc(w.villages[a.village].name)} · {esc(a.doing)}" + (f" · follows {esc(owner.name)}" if owner else "") +
                  f" · health {a.health*100:.0f}% · hunger {a.hunger*100:.0f}%" + (f" · {a.kills} kills" if a.kills else "") + "</div>", unsafe_allow_html=True)
      if not a.alive:
          st.error(f"{a.name} died on day {a.died_day:,} ({a.cause_of_death}).")
          if st.button("Let them go (bring someone new)"):
              ss.resident_id = None; ss.steward_token = None; st.rerun()
          return
      with st.form("animal_instr", clear_on_submit=True, border=False):
          instr = st.text_input("Tell them", placeholder=f"Follow Ivy Walker · Go for the tax collector · Run free in the hills · Cross into Galehaven · Hunt",
                                label_visibility="collapsed")
          if st.form_submit_button("Call to them", type="primary", use_container_width=True) and instr.strip():
              done = animal_sys.instruct(w, a, clean_text(instr, 300))
              st.toast(" · ".join(done), icon="🐾")

  EMO_COL = {"anger": "#ef4444", "fear": "#a78bfa", "grief": "#60a5fa", "joy": "#facc15", "shame": "#f472b6", "pride": "#fb923c",
             "envy": "#22c55e", "hope": "#2dd4bf", "love": "#fb7185"}
  DICE = "⚀⚁⚂⚃⚄⚅"

  def feelings_html(c):
      """What they feel, how strongly — the level decides what they'll do."""
      em = sorted(c.emotions.items(), key=lambda kv: -kv[1])[:3]
      if not em:
          return '<div style="font-size:12px;color:#8b98a8;margin-top:6px">Feeling: calm</div>'
      return '<div style="font-size:13px;color:#8b98a8;margin-top:6px">Feeling</div>' + "".join(
          f'<div style="display:flex;justify-content:space-between;font-size:12px;color:#c9d3df"><span>{e} · <i>{behaviour.band_name(l)}</i></span><span>{l*100:.0f}</span></div>'
          f'<div class="bar"><div style="width:{l*100:.0f}%;background:{EMO_COL.get(e, "#8b98a8")}"></div></div>' for e, l in em)

  def last_roll_html(c):
      """The six things they considered last time something happened to them, and where the die landed."""
      t = next((t for t in reversed(w.thoughts) if t.get("cid") == c.id and t.get("options")), None)
      if not t:
          return ""
      rows = "".join(f'<div style="font-size:11.5px;display:flex;justify-content:space-between;padding:1px 0;{"color:#fff;font-weight:700" if i + 1 == t["face"] else "color:#8b98a8"}">'
                     f'<span>{DICE[i]} {k.replace("_", " ")}</span><span>{p*100:.0f}%</span></div>' for i, (k, p) in enumerate(t["options"][:6]))
      return (f'<div style="font-size:13px;color:#8b98a8;margin-top:8px">Last decision · day {t["day"]}</div>'
              f'<div style="background:#101826;border:1px solid #1f2a3a;border-radius:8px;padding:6px 8px;margin-top:3px">{rows}</div>')


  # ------------------------------------------------------------------ header
  h1, h2, h3, h4 = st.columns([1.2, 5.9, 0.75, 1.15])
  with h1:
      st.markdown('<div class="brand"><span style="font-size:34px">🌲</span><div><div class="t">New Haven</div><div class="s">An AI Civilisation Simulator</div></div></div>', unsafe_allow_html=True)
  def pace_phrase(state) -> str:
      """How fast time runs here, in words."""
      per_min = 60.0 / max(0.1, state["tick_seconds"]) * state["days_per_tick"]
      if per_min < 1:
          return f"a day every {state['tick_seconds'] * state['days_per_tick'] / 60:.0f} minutes"
      if per_min < 2:
          return "a day every minute"
      for days, label in ((7, "a week"), (30, "a month"), (365, "a year")):
          if per_min < days * 2:
              return f"about {label} every minute"
      return f"{per_min / 365:.0f} years every minute"

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
  badge_col, switch_col = st.columns([5, 1])
  badge_col.markdown(f'<div style="font-size:12px;margin:-6px 0 6px 0;text-align:right">{brain_badge(w)}</div>', unsafe_allow_html=True)
  with switch_col.popover("🏘️ Public" if PUBLIC else "🌍 Private", use_container_width=True):
      st.caption("You are in the shared village that everyone sees." if PUBLIC else "You are in a private world of your own. Nobody else can see it.")
      if PUBLIC:
          if st.button("Switch to a private world", use_container_width=True):
              ss.mode = "private"; ss.playing = False; ss.pop("iso_html", None); st.rerun()
          if ss.get("resident_id") and ss.resident_id in w.citizens:
              if st.button(f"Go to {w.citizens[ss.resident_id].name.split()[0]}", use_container_width=True, type="primary"):
                  ss.nav = "🏡 Move in"; st.rerun()
          else:
              with st.form("hdr_claim", clear_on_submit=False, border=False):
                  t = st.text_input("Claim token", type="password", label_visibility="collapsed", placeholder="claim token", max_chars=100)
                  if st.form_submit_button("Claim my person", use_container_width=True) and claim_person(t):
                      st.rerun()
      else:
          if st.button("Join the public village", use_container_width=True, type="primary"):
              ss.mode = "public"; ss.playing = False; ss.pop("iso_html", None); st.rerun()
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
      PAGES = ["🌍 World", "👥 Citizens", "📊 Economy", "🏛️ Politics", "✦ Magic", "⚡ Events", "🏡 Move in", "🧪 Research", "⚙️ Settings"]
      page = st.segmented_control("nav", PAGES, default=PAGES[0], key="nav", label_visibility="collapsed") or PAGES[0]

  def village_label(i):
      v = w.villages[i]
      at_war = any(x.get("active") and i in (x["a"], x["b"]) for x in w.wars)
      flags = (" ⚔️" if at_war else "") + (" ⛓️" if v.occupier is not None else "") + (" ☠️" if v.fallen else "")
      return f"{ELEMENTS[v.element]['emblem']} {v.name}{flags}"
  vcol, vinfo = st.columns([3.2, 2.3])
  with vcol:
      st.segmented_control("village", list(range(len(w.villages))), format_func=village_label, key="village", label_visibility="collapsed")
  with vinfo:
      V = VILLAGE_NOW
      war_line = "; ".join(f"at war with {w.villages[x['b'] if x['a'] == V.idx else x['a']].name}" for x in w.wars if x.get("active") and V.idx in (x["a"], x["b"]))
      st.markdown(f'<div style="font-size:12px;color:#c9d3df;line-height:1.35;padding-top:2px"><b style="color:{V.colour}">{esc(V.name)}</b> · the {V.element} village · '
                  f'river {V.water_met*100:.0f}% of need · takes {V.diversion*100:.0f}% of the flow'
                  + (f' · <span style="color:#f87171">{esc(war_line)}</span>' if war_line else "")
                  + (f' · <span style="color:#eda100">occupied by {esc(w.villages[V.occupier].name)}</span>' if V.occupier is not None else "")
                  + (' · <span style="color:#f87171">in ruins</span>' if V.fallen else "") + "</div>", unsafe_allow_html=True)

  # ------------------------------------------------------------------ WORLD
  def world_page():
      global alive, last, prev
      with w.lock:
          w.focus = int(ss.get("village") or 0)
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
                      stat("💧", "River share", f"{VILLAGE_NOW.water_met*100:.0f}% of need") +
                      stat("🚨", "Crimes this year", f"{VILLAGE_NOW.crimes_year} ({VILLAGE_NOW.arrests_year} arrests)") +
                      stat("⚔️", "Guards · watch", f"{last.get('soldiers', 0)} · {last.get('police', 0)}") +
                      stat("🛡️", "Security", f"{security:.0f}%") + "</div>", unsafe_allow_html=True)
          rows_r = ""
          for v in w.villages:
              pop_v = sum(1 for c in w.citizens.values() if c.alive and c.village == v.idx)
              state_v = "ruins" if v.fallen else (f"held by {w.villages[v.occupier].name}" if v.occupier is not None else
                        ("at war" if any(x.get("active") and v.idx in (x["a"], x["b"]) for x in w.wars) else "at peace"))
              col_v = "#f87171" if state_v in ("ruins", "at war") or v.occupier is not None else "#8b98a8"
              rows_r += (f'<div class="stat"><div class="ic" style="background:{v.colour}33;color:{v.colour}">{ELEMENTS[v.element]["emblem"]}</div>'
                         f'<div><div class="lb">{esc(v.name)} · <span style="color:{col_v}">{state_v}</span></div><div class="vl" style="font-size:14px">{pop_v} people · '
                         f'💧{v.water_met*100:.0f}%</div></div></div>')
          st.markdown(f'<div class="panel"><h4>The Realm</h4>{rows_r}<div style="font-size:11px;color:#8b98a8;margin-top:4px">The river flows Sky → Air → Earth → Fire → Water.</div></div>',
                      unsafe_allow_html=True)
          # minimap
          cols = {terrain.WATER: "#3b82c4", terrain.GRASS: "#6fa857", terrain.FARMLAND: "#c9a85a", terrain.FOREST: "#3f7d4e", terrain.ROCK: "#8f8f8a",
                  terrain.TOWN: "#cfc2a8", terrain.ROAD: "#b8a888", terrain.SAND: "#e2cf98", terrain.SNOW: "#eef3f7", terrain.ASH: "#4a3f3a",
                  terrain.LAVA: "#ff5a1f", terrain.DAM: "#6b5a44", terrain.RUIN: "#2b2b2b"}
          fig = go.Figure()
          cs = []
          n = 13
          for k, c in cols.items():
              cs += [[k / n, c], [(k + 1) / n, c]]
          fig.add_trace(go.Heatmap(z=w.grid, colorscale=cs, zmin=0, zmax=n, showscale=False, hoverinfo="skip"))
          bs = w.open_businesses()
          fig.add_trace(go.Scatter(x=[b.x for b in bs], y=[b.y for b in bs], mode="markers", marker=dict(size=6, color="#ffd43b", symbol="square"), hoverinfo="skip"))
          homes = list({c.home for c in alive})
          fig.add_trace(go.Scatter(x=[h[0] for h in homes], y=[h[1] for h in homes], mode="markers", marker=dict(size=3, color="#f97316", symbol="square"), hoverinfo="skip"))
          x0_, y0_, x1_, y1_ = VILLAGE_NOW.region
          fig.add_shape(type="rect", x0=x0_ - 0.5, y0=y0_ - 0.5, x1=x1_ - 0.5, y1=y1_ - 0.5, line=dict(color=VILLAGE_NOW.colour, width=2))
          for x in w.wars:
              if x.get("active"):
                  fig.add_trace(go.Scatter(x=[x["front"][0]], y=[x["front"][1]], mode="text", text=["⚔️"], hoverinfo="skip"))
          fig.update_layout(height=170, margin=dict(l=0, r=0, t=0, b=0), paper_bgcolor="rgba(0,0,0,0)", showlegend=False,
                            xaxis=dict(visible=False), yaxis=dict(visible=False, scaleanchor="x", autorange="reversed"))
          with st.container(border=True):
              st.markdown("<h4>Map</h4>", unsafe_allow_html=True)
              st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
              st.markdown('<div style="font-size:11px;color:#8b98a8;display:flex;gap:10px;flex-wrap:wrap"><span>🟨 business</span><span>🟧 home</span><span style="color:#c9a85a">■ fields</span><span style="color:#3f7d4e">■ forest</span><span style="color:#8f8f8a">■ hills</span></div>', unsafe_allow_html=True)

      with mid:
          snap = os.path.join(STATIC, f"world_{ss.sid}.json")
          if "iso_html" not in ss:
              render = render_iso if ss.get("renderer") == "classic" else render_3d
              ss.iso_html = render(w, ss.selected, height=600, url=f"/app/static/world_{ss.sid}.json")
          fronts = [x for x in w.wars if x.get("active") and w.focus in (x["a"], x["b"])]
          write_snapshot(w, snap, ss.selected, follow=bool(ss.get("follow")), look=ss.get("look"))
          components.html(ss.iso_html, height=604)
          cam1, cam2, cam3 = st.columns(3)
          if fronts and cam1.button("⚔️ Go to the front", use_container_width=True):
              ss.look = tuple(fronts[0]["front"]); ss.follow = False; st.rerun()
          if VILLAGE_NOW.dam and cam2.button("💧 Look at the dam", use_container_width=True):
              ss.look = tuple(VILLAGE_NOW.dam); ss.follow = False; st.rerun()
          if ss.get("look") and cam3.button("🏘️ Back to the village", use_container_width=True):
              ss.look = None; st.rerun()
          if w.pandemic:
              st.error(f"🦠 {w.pandemic['name']} is spreading — {last['infected']} sick, {w.pandemic['deaths']} dead.")
          if w.strike:
              sm = w.movements.get(w.strike["movement"])
              st.warning(f"✊ {len(w.strike['members'])} members of the {sm.name if sm else 'movement'} are on strike until day {w.strike['until']:,} "
                         f"({w.strike['until'] - w.day} days to go — strikes end as days pass, or decree an end).")
          if w.recession_days:
              st.warning(f"📉 Recession — {w.recession_days} days to go.")

      with right:
          options = {c.id: f"{c.name} ({c.age_on(w.day)}{', ' + c.role if c.role else ''})" for c in sorted(alive, key=lambda c: c.id)}
          if not options:
              options = {c.id: f"{c.name} († day {c.died_day})" for c in list(w.citizens.values())[:50]}
          if ss.selected not in options:
              ss.selected = max(alive, key=lambda c: len(c.memories)).id if alive else next(iter(options))
          ss.selected = st.selectbox("Selected citizen", list(options), index=list(options).index(ss.selected) if ss.selected in options else 0,
                                     format_func=lambda i: options[i], label_visibility="collapsed")
          ss.follow = st.toggle("🎥 Camera follows them", value=bool(ss.get("follow", False)))
          write_snapshot(w, os.path.join(STATIC, f"world_{ss.sid}.json"), ss.selected, follow=bool(ss.get("follow")), look=ss.get("look"))
          c = w.citizens[ss.selected]
          emp = w.businesses.get(c.employer_id) if c.employer_id else None
          mood = "😊 Happy" if c.happiness > 0.65 else ("😐 Fine" if c.happiness > 0.45 else "😟 Struggling")
          near = min(w.open_businesses(), key=lambda b: abs(b.x - c.pos[0]) + abs(b.y - c.pos[1]), default=None)
          where = "In the cells" if c.jailed_until >= w.day else "Home" if c.pos == c.home or (abs(c.pos[0] - c.home[0]) + abs(c.pos[1] - c.home[1]) <= 2) else (near.name if near and abs(near.x - c.pos[0]) + abs(near.y - c.pos[1]) <= 2 else "Out and about")
          hue = (c.id * 47) % 360
          social = min(1.0, sum(1 for r in c.relationships.values() if r.score >= 40) / 8)
          mems = sorted(c.memories, key=lambda m: -m.day)[:4]
          st.markdown('<div class="panel"><h4>Selected Citizen</h4>'
                      f'<div style="display:flex;gap:12px;align-items:flex-start"><div class="avatar" style="background:linear-gradient(135deg,hsl({hue},60%,45%),hsl({hue+40},60%,30%))">{c.name[0]}</div>'
                      f'<div style="font-size:13px;color:#c9d3df;line-height:1.5"><div style="font-size:16px;font-weight:700;color:#fff">{esc(c.name)}</div>'
                      f'<span style="color:#eda100">{", ".join(describe(c)).capitalize()}</span><br>Age: {c.age_on(w.day)} · {job_label(w, c.job).title()}{" at " + esc(emp.name) if emp else ""}<br>Mood: {mood}<br>Location: {esc(where)}</div></div>'
                      f'<div style="margin:10px 0 6px 0;padding:8px 10px;border-left:3px solid #eda100;background:#1b2636;border-radius:6px;font-size:13px;color:#e6edf3;font-style:italic">“{esc(thought(w, c))}”</div>'
                      + bar("Health", c.health, "#4ade80") + bar("Happiness", c.happiness, "#3b82f6") + bar("Energy", 1 - c.hunger, "#eda100") + bar("Social", social, "#8b5cf6")
                      + feelings_html(c) + (f'<div style="font-size:12px;color:#c9d3df;margin-top:4px">🏛️ {c.role.title()} of {esc(VILLAGE_NOW.name)}</div>' if c.role else "")
                      + (f'<div style="font-size:12px;color:#8b5cf6;margin-top:4px">✦ {c.magic["element"]} mage · power {c.magic["power"]*100:.0f}%'
                         + ('' if c.magic.get("revealed") else ' · <i>secret</i>') + '</div>' if c.magic and c.magic.get("awakened") and (IS_GOD or c.magic.get("revealed"))
                         else (f'<div style="font-size:12px;color:#8b5cf6;margin-top:4px">📜 apprentice of the old arts · practice {c.magic.get("practice", 0)*100:.0f}%</div>'
                               if IS_GOD and c.magic and c.magic.get("practice", 0) > 0 else ""))
                      + (f'<div style="font-size:12px;color:#f87171;margin-top:4px">⛓️ In the cells until day {c.jailed_until:,}</div>' if c.jailed_until >= w.day else "")
                      + last_roll_html(c)
                      + f'<div style="font-size:13px;color:#8b98a8;margin-top:6px">Current goal</div><div style="font-size:14px;color:#fff">🎯 {c.goal.capitalize()} <span style="color:#8b98a8">({c.goal_progress*100:.0f}%)</span></div>'
                      + '<div style="font-size:13px;color:#8b98a8;margin-top:8px">Recent memories</div>'
                      + "".join(f'<div class="mem"><b>Day {m.day}</b>{esc(m.text)}</div>' for m in mems) + (f'<div class="mem" style="color:#8b98a8">Nothing memorable yet.</div>' if not mems else "")
                      + f'<div style="font-size:12px;color:#8b98a8;margin-top:8px">£{c.money:,.0f} · {sum(1 for r in c.relationships.values() if r.score>=40)} friends · {sum(1 for r in c.relationships.values() if r.score<=-40)} enemies'
                      + (f" · married to {esc(w.citizens[c.spouse_id].name)}" if c.spouse_id else "") + (f" · {esc(w.movements[c.movement_id].name)}" if c.movement_id else "") + '</div></div>', unsafe_allow_html=True)
          with st.container(border=True):
              st.markdown("<h4>Simulation Controls</h4>" + ("" if IS_GOD else "<div style='font-size:12px;color:#eda100'>🔒 Only the god of this village controls the civilisation. You control your own person on the Move in page.</div>"), unsafe_allow_html=True)
              if not IS_GOD:
                  st.markdown(f"<div style='font-size:12px;color:#8b98a8'>Pace: {pace_phrase(shared)} · {'running' if shared['running'] else 'paused'}</div>", unsafe_allow_html=True)
              if not PUBLIC:
                  ss.speed = st.select_slider("Speed while playing", options=list(SPEEDS), value=ss.speed if ss.speed in SPEEDS else "1 day / sec")
              INJECTABLE = all_injectable(w)
              shock = st.selectbox("God mode", list(INJECTABLE), format_func=lambda k: f"⚡ {k.replace('_', ' ')} — {INJECTABLE[k]}", label_visibility="collapsed", disabled=not IS_GOD)
              if st.button(f"Smite {VILLAGE_NOW.name}", use_container_width=True, type="primary", disabled=not IS_GOD):
                  w.inject(shock); st.toast(INJECTABLE[shock], icon="⚡"); st.rerun()
              sp1, sp2 = st.columns([2, 1])
              wonder = sp1.selectbox("Wonder", ["meteor_shower", "wildfire", "earthquake", "lightning_storm", "tornado", "flood", "aurora", "eclipse"],
                                     format_func=lambda k: "☄️ " + k.replace("_", " "), label_visibility="collapsed", disabled=not IS_GOD)
              w_where = sp2.selectbox("On", [w.focus] + [v.idx for v in w.villages if v.idx != w.focus] + [-1],
                                      format_func=lambda i: "every village" if i == -1 else w.villages[i].name, label_visibility="collapsed", disabled=not IS_GOD)
              if st.button(f"Unleash on {'every village' if w_where == -1 else w.villages[w_where].name}", use_container_width=True, disabled=not IS_GOD):
                  from civilisation.commands import spectacle
                  done_w = []
                  for idx in ([v.idx for v in w.villages if not v.fallen] if w_where == -1 else [w_where]):
                      with w.at(idx):
                          spectacle(w, wonder, 0.7, done_w, set())
                  if w_where not in (-1, w.focus):
                      ss.pending_village = w_where; ss.look = None          # go and see where it fell
                  st.toast(" ".join(done_w), icon="☄️"); st.rerun()
              has_key = host_cfg()["has_key"]
              st.markdown('<div style="font-size:13px;color:#8b98a8;margin-top:6px">✍️ Or decree anything — it happens, whatever it is' + ("" if has_key else " <span style='color:#8b98a8'>(keyword reading; add an API key in Settings for anything you can type)</span>") + "</div>", unsafe_allow_html=True)
              with st.form("decree_form", clear_on_submit=True, border=False):
                  decree = st.text_area("Decree", placeholder="e.g. War between Fire and Water · A meteor shower falls on Emberhold · Ivy Walker must kill Elif Patel · Give Omar the power of fire · Wolves come down from the hills · Break Skyreach's dam",
                                        label_visibility="collapsed", height=80)
                  d_where = st.selectbox("Where", ["the village it names (or " + VILLAGE_NOW.name + ")", "every village"] + [v.name for v in w.villages],
                                         label_visibility="collapsed")
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
                          if not [e for e in plan.get("effects", []) if e.get("op") != "memory"]:
                              plan = None                  # a model that declined or did nothing: the decree still happens
                      except Exception as e:
                          st.toast(f"The model didn't answer ({scrub(e)}); reading the decree by keywords.", icon="⚠️")
                  if plan is None:
                      plan, source = fallback_plan(decree, w), "rules"
                  if plan:
                      if d_where == "every village":
                          plan["village"] = "all"
                      elif not d_where.startswith("the village it names"):
                          plan["village"] = next(v.element for v in w.villages if v.name == d_where)
                      done = apply_plan(w, plan, source)
                      from civilisation.commands import village_index
                      hit = village_index(w, plan.get("village")) if plan.get("village") not in (None, "", "all") else []
                      if len(hit) == 1 and hit[0] != w.focus:
                          ss.pending_village = hit[0]; ss.look = None       # go and see where it happened
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
          for t in [t for t in w.thoughts if t.get("village", w.focus) == w.focus][-9:][::-1]:
              spark = "✨ " if t["source"] == "llm" else ""
              die = f'<span title="rolled {t["face"]} of 6" style="color:#8b98a8">{DICE[t["face"] - 1]} </span>' if t.get("face") else ""
              rows += f'<div class="ev"><b>Day {t["day"]}</b>{die}<span style="color:#eda100">{spark}{esc(t["name"])}</span>: <i>{esc(t["text"])}</i></div>'
          title = "Inner voices" + (" <span style='font-size:11px;color:#4ade80'>✨ = written by Claude</span>" if w.brain.name == "llm" else "")
          st.markdown(f'<div class="panel"><h4>{title}</h4>{rows or "<div class=ev>Nothing on anyone\'s mind yet.</div>"}</div>', unsafe_allow_html=True)
      with bl:
          icons = {"disaster": "🌪️", "politics": "🗳️", "economy": "💰", "life": "🌱", "society": "💍", "social": "💬", "work": "🔧", "discovery": "💡", "founding": "🏛️", "year": "📅", "collapse": "💀", "decree": "✨", "environment": "🌦️"}
          icons.update({"crime": "🚨", "justice": "⚖️", "war": "⚔️", "diplomacy": "🕊️", "river": "💧", "magic": "✦", "animals": "🐾"})
          seen_ev = [e for e in w.events if e.importance >= 0.4 and e.village in (w.focus, -1) and (IS_GOD or not e.secret)]
          rows = "".join(f'<div class="ev{" big" if e.importance >= 0.55 else ""}"><b>Day {e.day}</b>{"🔒 " if e.secret else ""}{esc(e.text)} {icons.get(e.category, "")}</div>' for e in seen_ev[-12:][::-1])
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
          everywhere = st.toggle("Whole realm", value=False, key="cit_all")
          def magic_of(cid):
              c = w.citizens.get(cid)
              m = c.magic if c else None
              if not m:
                  return ""
              if m.get("awakened") and (IS_GOD or m.get("revealed")):
                  return f"✦ {m['element']} {m['power']*100:.0f}%" + ("" if m.get("revealed") else " (secret)")
              return f"apprentice {m.get('practice', 0)*100:.0f}%" if IS_GOD and m.get("practice", 0) >= 0.1 else ""
          if len(df):
              df.insert(3, "magic", df["id"].map(magic_of))
          if not everywhere and len(df):
              df = df[df.village == VILLAGE_NOW.name]
          st.dataframe(df.drop(columns=["x", "y"]).sort_values("id"), use_container_width=True, height=560, hide_index=True)
          fauna = [a for a in w.animals.values() if a.alive and (everywhere or a.village == w.focus)]
          if fauna:
              st.markdown("#### Animals")
              st.dataframe(pd.DataFrame([{"name": a.name, "species": f"{animal_sys.SPECIES[a.species]['emoji']} {a.species}", "village": w.villages[a.village].name,
                                          "age": a.age_on(w.day), "wild": a.wild, "owner": w.citizens[a.owner_id].name if a.owner_id in w.citizens else "",
                                          "doing": a.doing, "kills": a.kills, "sponsor": a.sponsor} for a in fauna]), hide_index=True, use_container_width=True, height=260)
      with c2:
          opts = {f"{c.name} (#{c.id}, {c.age_on(w.day)}{'' if c.alive else ', dead'})": c.id for c in sorted(w.citizens.values(), key=lambda c: (not c.alive, c.id))
                  if everywhere or c.village == w.focus}
          pick = st.selectbox("Full biography", list(opts))
          st.markdown(w.biography(opts[pick]))

  # ------------------------------------------------------------------ ECONOMY
  if page == PAGES[2]:
      e1, e2 = st.columns(2)
      with e1:
          st.markdown("#### Businesses")
          st.dataframe(pd.DataFrame([{"name": b.name, "kind": b.kind, "owner": w.citizens[b.owner_id].name if b.owner_id else "—", "staff": len(b.employees),
                                      "wage": round(b.wage), "cash": round(b.cash), "revenue/day": round(float(np.mean(b.revenue_history[-30:])) if b.revenue_history else 0),
                                      "founded": b.founded_day, "open": b.alive} for b in w.businesses.values() if b.village == w.focus]).sort_values(["open", "cash"], ascending=False),
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
              movs = {m.id: m for m in w.movements_here() if m.alive}
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
          if w.movements_here():
              st.dataframe(pd.DataFrame([{"name": m.name, "founder": w.citizens[m.founder_id].name, "founded": m.founded_day, "against": m.grievance_theme,
                                          "members": len(m.members), "party": m.is_party, "active": m.alive, "economic": round(m.platform["economic"], 2),
                                          "last votes": m.seats_won} for m in w.movements_here()]), hide_index=True, use_container_width=True)
          council = [c for c in w.alive() if c.role == "councillor"]
          st.markdown("#### Council of " + esc(VILLAGE_NOW.name))
          st.markdown(" · ".join(f"**{esc(c.name)}** ({c.reputation:+.2f})" for c in council) or "_The council house is empty._")
          st.markdown("#### The river and the realm")
          st.dataframe(pd.DataFrame([{"village": v.name, "element": v.element, "takes of the flow": f"{v.diversion*100:.0f}%",
                                      "gets of its need": f"{v.water_met*100:.0f}%", "morale": round(v.morale, 2),
                                      "wars won/lost": f"{v.wars_won}/{v.wars_lost}",
                                      "status": "ruins" if v.fallen else (f"held by {w.villages[v.occupier].name}" if v.occupier is not None else "free"),
                                      **{f"tension→{o.element}": round(v.tension.get(o.idx, 0), 2) for o in w.villages if o.idx != v.idx}}
                                     for v in w.villages]), hide_index=True, use_container_width=True)
          if w.wars:
              st.dataframe(pd.DataFrame([{"war": f"{w.villages[x['a']].name} vs {w.villages[x['b']].name}", "over": x.get("reason", ""),
                                          "from day": x["start"], "to day": x.get("end", "—"), "battles": x["battles"],
                                          "dead": x["dead"][x["a"]] + x["dead"][x["b"]],
                                          "winner": w.villages[x["winner"]].name if x.get("winner") is not None else ("—" if x.get("active") else "nobody")}
                                         for x in w.wars[::-1]]), hide_index=True, use_container_width=True)
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

  # ------------------------------------------------------------------ MAGIC
  if page == PAGES[4]:
      from civilisation.systems import magic as magic_sys
      st.markdown("#### The secret circles")
      st.caption("Each village has a hidden circle that can work its element. Nobody is born a mage: power comes from years of practice "
                 "(the goal *master the old arts*), or wakes in someone at the edge of grief or rage — or god grants it. A steward can't. "
                 "Mages keep themselves secret until war draws them out: in battle each one is worth several guards, and using it reveals them. "
                 "When their village is occupied, the circle plots to drive the garrison out; when it falls to ruin, its scattered mages are "
                 "the only way its people ever go home. "
                 + ("**You are god: you see every mage and apprentice.**" if IS_GOD else "**Only mages who have revealed themselves are shown.**"))
      WHAT = {"fire": "fireballs · the forge", "water": "waves · rain · healing", "earth": "quakes · stone · roots",
              "air": "whirlwinds · speed", "sky": "lightning · storms · stars"}
      circles = [magic_sys.circle(w, v.idx) for v in w.villages]
      cols = st.columns(5)
      for col, cr in zip(cols, circles):
          v = cr["village"]
          shown = [c for c in cr["mages"] if IS_GOD or c.magic.get("revealed")]
          guards = cr["battle"] / 2.0
          if v.occupier is not None:
              fate = (f"⛓ held by {esc(w.villages[v.occupier].name)} · rising: <b>{cr['rise']*100:.0f}%</b>/week" if IS_GOD
                      else f"⛓ held by {esc(w.villages[v.occupier].name)}")
          elif v.fallen:
              fate = f"☠ in ruins · return: <b>{cr['return']*100:.0f}%</b>/week" if IS_GOD else "☠ in ruins"
          else:
              fate = "free"
          col.markdown(
              f'<div class="panel" style="border-top:3px solid {v.colour}"><h4>{ELEMENTS[v.element]["emblem"]} {esc(v.name)}</h4>'
              f'<div style="font-size:12px;color:#c9d3df">{v.element.title()} — {esc(ELEMENTS[v.element]["power"])}<br>'
              f'<span style="color:#8b98a8">in battle: {WHAT[v.element]}</span></div>'
              + stat("✦", "Mages" + ("" if IS_GOD else " (revealed)"), f"{len(shown)}")
              + (stat("📜", "Apprentices", f"{len(cr['apprentices'])}") if IS_GOD else "")
              + (stat("⚔️", "Worth defending it", f"≈ {guards:.0f} guards") if IS_GOD else "")
              + (f'<div style="font-size:11px;color:#8b98a8">counts mages living there and free; exiles and prisoners can\'t fight for it</div>'
                 if IS_GOD and len(cr["mages"]) and guards < 0.5 else "")
              + f'<div style="font-size:12px;color:#c9d3df;margin-top:6px">{fate}</div></div>', unsafe_allow_html=True)
      rows = []
      for cr in circles:
          v = cr["village"]
          for c in cr["mages"]:
              if not (IS_GOD or c.magic.get("revealed")):
                  continue
              rows.append({"name": c.name, "circle": v.name, "lives in": w.villages[c.village].name, "element": c.magic["element"],
                           "power": f"{c.magic['power']*100:.0f}%", "worth in battle": f"≈ {magic_sys.mage_worth(c)/2:.1f} guards",
                           "revealed": "yes" if c.magic.get("revealed") else "secret", "age": c.age_on(w.day), "job": job_label(w, c.job),
                           "role": c.role, "goal": c.goal, "in the cells": c.jailed_until >= w.day, "id": c.id})
      st.markdown("#### Mages")
      if rows:
          st.dataframe(pd.DataFrame(rows).drop(columns=["id"]), hide_index=True, use_container_width=True)
          pick = st.selectbox("Show a mage on the map", [r["id"] for r in rows],
                              format_func=lambda i: f"{w.citizens[i].name} — {w.villages[w.citizens[i].village].name}", key="mage_pick")
          if st.button("🎥 Go and watch them", key="mage_go"):
              c = w.citizens[pick]
              ss.pending_village = c.village; ss.selected = c.id; ss.follow = True; ss.pending_nav = PAGES[0]; ss.look = None
              st.rerun()
      else:
          st.caption("No mage has revealed themselves yet. They will, when a war comes." if not IS_GOD else "There are no mages left alive.")
      if IS_GOD:
          st.markdown("#### Apprentices — practising, not yet awakened")
          pupils = [(c, cr["village"]) for cr in circles for c in cr["apprentices"]]
          if pupils:
              st.dataframe(pd.DataFrame([{"name": c.name, "circle": v.name, "lives in": w.villages[c.village].name,
                                          "practice": f"{(c.magic or {}).get('practice', 0)*100:.0f}%", "goal": c.goal,
                                          "openness": round(c.personality["openness"], 2), "age": c.age_on(w.day)} for c, v in pupils]),
                           hide_index=True, use_container_width=True)
              st.caption("Practice builds with the *practise the old arts* act and the goal *master the old arts*. Past about 45% practice, "
                         "each session has a small chance to awaken them; open, diligent people get there faster.")
          else:
              st.caption("Nobody is practising the old arts right now.")
          st.markdown("#### Grant or take away power")
          g1, g2, g3 = st.columns([2, 1, 1])
          everyone = sorted(w.alive_all(), key=lambda c: (c.village, c.name))
          who = g1.selectbox("Person", [c.id for c in everyone], key="grant_who",
                             format_func=lambda i: f"{w.citizens[i].name} — {w.villages[w.citizens[i].village].name}"
                             + (" ✦" if magic_sys.is_mage(w.citizens[i]) else ""))
          pw = g2.slider("Power", 0.1, 1.0, 0.6, 0.05, key="grant_power")
          if g3.button("✦ Grant", use_container_width=True, key="grant_go"):
              c = w.citizens[who]
              with w.at(c.village):
                  magic_sys.awaken(w, c, element=w.villages[c.origin].element, power=pw, why="a gift from the gods", granted=True)
              st.toast(f"{c.name} can call on the {c.magic['element']} now.", icon="✦"); st.rerun()
          if g3.button("Take it away", use_container_width=True, key="grant_strip", disabled=not magic_sys.is_mage(w.citizens[who])):
              w.citizens[who].magic = None
              st.toast(f"{w.citizens[who].name}'s power is gone.", icon="✦"); st.rerun()

  # ------------------------------------------------------------------ EVENTS
  if page == PAGES[5]:
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
          evs = [e for e in reversed(w.events) if (IS_GOD or not e.secret) and (e.village in (w.focus, -1) or st.session_state.get("ev_all"))][:400]
          st.toggle("Every village", key="ev_all")
          st.dataframe(pd.DataFrame([{"day": e.day, "where": w.villages[e.village].name if e.village >= 0 else "realm", "category": e.category,
                                      "importance": round(e.importance, 2), "text": ("🔒 " if e.secret else "") + e.text, "brain": e.brain} for e in evs]),
                       hide_index=True, use_container_width=True, height=700)

  # ------------------------------------------------------------------ RESEARCH

  if page == PAGES[6]:
      rid = ss.get("resident_id")
      if rid and rid not in w.citizens and rid not in w.animals:
          rid = ss.resident_id = None
      m1, m2 = st.columns([1, 1.1])
      with m1:
          if rid and rid in w.animals:
              animal_steward(w.animals[rid])
          elif not rid:
              st.markdown("#### Move someone into the realm")
              mk1, mk2 = st.columns(2)
              who_kind = mk1.radio("Who", ["A person", "An animal"], horizontal=True, label_visibility="collapsed", key="mi_kind")
              home_v = mk2.selectbox("Village", list(range(len(w.villages))), index=w.focus, key="mi_village",
                                     format_func=lambda i: f"{ELEMENTS[w.villages[i].element]['emblem']} {w.villages[i].name} — {w.villages[i].element}",
                                     label_visibility="collapsed")
              st.caption(ELEMENTS[w.villages[home_v].element]["blurb"].capitalize() + ". Magic can't be given to them — "
                         "they can only earn it, by years of practice.")
          if not rid and st.session_state.get("mi_kind") == "An animal":
              with st.form("move_in_animal", border=True):
                  an_name = st.text_input("Name", placeholder="Ember")
                  sp_opts = list(animal_sys.SPECIES)
                  an_sp = st.selectbox("Species", sp_opts, format_func=lambda k: f"{animal_sys.SPECIES[k]['emoji']} {k}" + (" · wild" if animal_sys.SPECIES[k]["wild"] else " · tame"))
                  an_back = st.text_area("Their story", placeholder="A one-eyed tiger who came down from the ash fields after the lava took her den.", height=70)
                  t1, t2 = st.columns(2)
                  bold = t1.slider("Timid ↔ bold", 0.0, 1.0, 0.6)
                  aggr = t2.slider("Gentle ↔ fierce", 0.0, 1.0, 0.4)
                  loyal = t1.slider("Independent ↔ loyal", 0.0, 1.0, 0.6)
                  cur = t2.slider("Wary ↔ curious", 0.0, 1.0, 0.6)
                  an_sponsor = st.text_input("Your name (shown as sponsor)", placeholder="om")
                  go_animal = st.form_submit_button("Release them 🐾", type="primary", use_container_width=True)
              if go_animal and realm_full():
                  st.error("The realm is full for now.")
              elif go_animal:
                  a = animal_sys.adopt(w, an_name, an_sp, int(st.session_state.get("mi_village", w.focus)), sponsor=an_sponsor, backstory=an_back,
                                       temperament={"boldness": bold, "aggression": aggr, "loyalty": loyal, "curiosity": cur})
                  token = secrets.token_urlsafe(18)
                  ss.resident_id = a.id; ss.steward_token = token; ss.sponsor_name = an_sponsor.strip(); ss.pending_village = a.village
                  if PUBLIC:
                      shared["residents"][a.id] = an_sponsor.strip() or "anonymous"
                      try:
                          shared["store"].write_resident(VILLAGE, {"citizen_id": a.id, "name": a.name, "sponsor": an_sponsor.strip(), "provider": "animal",
                                                                   "model": a.species, "base_url": None, "enc_key": None, "max_calls": 0, "token_hash": token_hash(token)})
                          shared["recorder"].flush(w, force_snapshot=True)
                      except Exception as e:
                          st.warning(f"Saved in memory but not to the store: {e}")
                  st.rerun()
          elif not rid:
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
                  elif realm_full():
                      st.error("The realm is full for now.")
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
                                  backstory=backstory, sponsor=sponsor, brain=brain, village=int(st.session_state.get("mi_village", w.focus)))
                      ss.pending_village = c.village
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
              if PUBLIC:
                  st.markdown("#### Already have a person here?")
                  with st.form("moveinpage_claim", clear_on_submit=False, border=False):
                      claim = st.text_input("Paste your claim token", type="password", max_chars=100)
                      if st.form_submit_button("Claim") and claim_person(claim):
                          st.rerun()
          elif rid in w.citizens:
              c = w.citizens[rid]
              brain = w.brains.get(rid)
              st.markdown(f"#### You are the steward of {c.name}")
              if ss.get("steward_token"):
                  st.info(f"Your claim token — keep it, it is the only way back to {c.name.split()[0]} from another device:\n\n`{ss.steward_token}`\n\nPaste it into the claim box when you return (avoid putting it in a URL you might share).")
              if not c.alive:
                  st.error(f"{c.name} died on day {c.died_day:,} of {c.cause_of_death}, aged {c.age_on(c.died_day)}.")
                  with st.expander(f"Read {c.name.split()[0]}'s life", expanded=False):
                      st.markdown(w.biography(rid))

                  def take_over(new_id, label):
                      ss.resident_id = new_id
                      ss.selected = new_id
                      if PUBLIC:
                          try:
                              shared["store"].transfer_resident(VILLAGE, rid, new_id, w.citizens[new_id].name)
                              shared["residents"][new_id] = w.citizens[new_id].sponsor
                              shared["residents"].pop(rid, None)
                              shared["recorder"].flush(w, force_snapshot=True)
                          except Exception as e:
                              st.warning(f"Carried over here but not saved to the store: {scrub(e)}")
                      st.toast(label, icon="🕯️")
                      st.rerun()

                  heirs = w.heirs_of(rid)
                  if heirs:
                      st.markdown("**Your line continues.** Their children are still here — choose who carries it on. "
                                  "Your claim token stays the same.")
                      for h in heirs[:6]:
                          emp = w.businesses.get(h.employer_id) if h.employer_id else None
                          if st.button(f"Continue as {h.name} · {h.age_on(w.day)} · {job_label(w, h.job)}{' at ' + emp.name if emp else ''}",
                                       key=f"heir_{h.id}", use_container_width=True, type="primary"):
                              w.inherit(rid, h.id)
                              take_over(h.id, f"{h.name} carries the line on.")
                  else:
                      st.markdown("**They left no living children.** A relative could come and take up the family's place — "
                                  "same name, same claim token.")
                      if st.button("Send for a relative", use_container_width=True, type="primary"):
                          new = w.adopt_relative(rid)
                          take_over(new.id, f"{new.name} arrived to take up the name.")
                  if st.button("Let the line end (move someone new in instead)"):
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
                      instr = st.text_area("Instruction", placeholder="Get a better-paid job · Court Otto Petrov · Steal from the richest merchant · Burn down the tavern · Practise the old arts · Move to Galehaven", label_visibility="collapsed", height=70)
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
                              st.warning("Couldn't read that without a model. Try a verb: steal, fight, court, marry, pray, practise, enlist, emigrate to <village>, get a job, quit…")
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
                      e1_, e2_ = st.columns([2, 1])
                      dest = e1_.selectbox("Emigrate to", [v.idx for v in w.villages if v.idx != c.village], format_func=lambda i: w.villages[i].name, label_visibility="collapsed")
                      if e2_.button("Emigrate", use_container_width=True):
                          run_plan({"effects": [{"op": "emigrate", "params": {"to": w.villages[dest].element}}]}, f"emigrate to {w.villages[dest].name}")
                      st.markdown("<div style='font-size:12px;color:#8b98a8'>Do anything — they will</div>", unsafe_allow_html=True)
                      d1_, d2_ = st.columns([2, 1])
                      act_key = d1_.selectbox("Act", sorted(behaviour.ACTS), format_func=lambda k: k.replace("_", " "), label_visibility="collapsed")
                      if d2_.button("Do it", use_container_width=True):
                          run_plan({"effects": [{"op": "act", "params": {"act": act_key, "who": who.name if who else None}}]}, f"{act_key.replace('_', ' ')} ({who.name if who else ''})")
                  if st.button("Leave town for good (remove your person)"):
                      from civilisation.systems.lifecycle import die
                      die(w, c, "left town")
                      ss.resident_id = None; ss.steward_token = None; st.rerun()
      with m2:
          if rid and rid in w.animals:
              a = w.animals[rid]
              st.markdown(f"#### {a.name}'s days")
              for m in a.memories[-14:][::-1]:
                  st.markdown(f"<div class='mem'><b>Day {m.day}</b><i>{esc(m.text)}</i></div>", unsafe_allow_html=True)
              if not a.memories:
                  st.caption("Nothing yet — let a few days pass.")
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
          pets = [a for a in w.animals.values() if a.sponsor]
          if sponsored or pets:
              st.dataframe(pd.DataFrame([{"name": c.name, "village": w.villages[c.village].name, "sponsor": c.sponsor, "age": c.age_on(w.day),
                                          "job": job_label(w, c.job), "alive": c.alive,
                                          "mind": f"{w.brains[c.id].provider}/{w.brains[c.id].model}" if c.id in w.brains else "rules",
                                          "friends": sum(1 for r in c.relationships.values() if r.score >= 40)} for c in sponsored]
                                        + [{"name": a.name, "village": w.villages[a.village].name, "sponsor": a.sponsor, "age": a.age_on(w.day),
                                            "job": a.species, "alive": a.alive, "mind": "instinct", "friends": 1 if a.owner_id else 0} for a in pets]),
                           hide_index=True, use_container_width=True)
          else:
              st.caption("Nobody has moved in yet.")

  if page == PAGES[7]:
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
  if page == PAGES[8]:
      s1, s2 = st.columns(2)
      with s1:
          seed = st.number_input("Seed", 0, 999999, w.seed)
          pop = st.number_input("Founding population (split across the five villages)", 50, 1000, 300, step=25)
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
              rst = shared["recorder"].stats()
              ago = (time.time() - rst["last_snapshot_at"]) / 60 if rst["snapshots"] else None       # minutes only for saves made in this run
              lost = w.day - rst["last_snapshot_day"] if rst["last_snapshot_day"] >= 0 else w.day
              sv1, sv2 = st.columns([3, 1])
              sv1.markdown(f"**Last saved:** day {rst['last_snapshot_day']:,}" + (f", {ago:.0f} min ago" if ago is not None else "")
                           + (f" — a restart now would roll the world back **{lost:,} days**. Save before you deploy." if lost > 0 else " — up to date."))
              if sv2.button("💾 Save the world now", use_container_width=True, type="primary"):
                  ok = shared["recorder"].save_now(w)
                  (st.success if ok else st.error)(f"Saved at day {w.day:,}." if ok else f"Not saved: {shared['recorder'].last_error or 'unknown error'}")
                  rst = shared["recorder"].stats()
              st.caption(f"Storage: **{shared['store'].status()}** · village '{VILLAGE}' · " + ("restored from snapshot · " if shared.get("restored") else "") +
                         f"{rst['writes']} writes · {rst['snapshots']} snapshots (last {rst['last_snapshot_mb']} MB) · "
                         f"{rst['throttled']} throttled · **{rst['dropped']} lost**"
                         + (f" · notes: {scrub('; '.join(shared['notes']))}" if shared.get("notes") else ""))
              if rst["last_error"]:
                  st.error(f"store: {rst['last_error']}")
              cit = len(w.citizens)
              st.caption(f"World size: {cit} citizens on record ({len(w.alive())} alive), "
                         f"{sum(len(c.relationships) for c in w.citizens.values()):,} relationships, {len(w.chronicle)} chronicle entries.")
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
          st.markdown("New Haven v0.3 · five elemental villages on one river · a behaviour engine of situations, feelings and a loaded die · "
                      "optional LLM minds gated by event importance · MIT")
          st.caption("3D models: people and most animals by Quaternius (CC0 — Universal Animation Library, Animated Animal Pack). "
                     "Bear, tiger, lion, elephant and eagle by Poly by Google (CC-BY 3.0, via poly.pizza). Full list in static/models/CREDITS.md.")


finally:
  w.lock.release()

# (the World page is a fragment that reruns itself while playing — see world_page)
