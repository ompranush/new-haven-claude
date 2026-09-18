import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

import networkx as nx
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from civilisation import World, chronicle_text
from civilisation import terrain
from civilisation.experiments import SCENARIOS, compare, summary
from civilisation.systems.disasters import INJECTABLE

st.set_page_config(page_title="New Haven — AI Civilisation", page_icon="🌍", layout="wide")

# fixed categorical palette (validated, assigned in order — never cycled)
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
TERRAIN_COLOURS = {terrain.WATER: "#4a8fd1", terrain.GRASS: "#8fbf7a", terrain.FARMLAND: "#d8c36e", terrain.FOREST: "#3f7d4e",
                   terrain.ROCK: "#8e8e8a", terrain.TOWN: "#cbb9a1", terrain.ROAD: "#b3a48d"}
BUSINESS_ICON = {"farm": "🌾", "bakery": "🥖", "workshop": "⚒️", "market": "🏪", "mine": "⛏️", "tavern": "🍺", "school": "🏫", "clinic": "🏥"}
JOB_COLOUR = {"farmer": SERIES[5], "baker": SERIES[3], "craftsperson": SERIES[1], "merchant": SERIES[0], "miner": SERIES[6],
              "innkeeper": SERIES[4], "teacher": SERIES[2], "doctor": SERIES[7], "unemployed": "#6b6b66", "child": "#ffffff", "retired": "#bdbdb5"}
LAYOUT = dict(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", margin=dict(l=8, r=8, t=30, b=8),
              font=dict(size=12), legend=dict(orientation="h", y=-0.15), hovermode="x unified")


def new_world(seed, pop, llm):
    brain = None
    if llm:
        try:
            from civilisation.llm import LLMBrain
            brain = LLMBrain(threshold=st.session_state.get("llm_threshold", 0.75), max_calls=st.session_state.get("llm_max", 100))
        except Exception as e:  # missing package or credentials
            st.sidebar.error(f"LLM brain unavailable: {e}")
    return World(seed=seed, population=pop, brain=brain)


if "world" not in st.session_state:
    st.session_state.world = new_world(42, 100, False)
w: World = st.session_state.world

# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.title("🌍 New Haven")
    st.caption("Small people. Big stories.")
    seed = st.number_input("Seed", 0, 999999, w.seed)
    pop = st.number_input("Founding population", 20, 500, 100, step=10)
    use_llm = st.toggle("Claude brain for major events", value=False, help="Needs `pip install anthropic` and credentials. Only fires for events above the threshold; hard-capped.")
    if use_llm:
        st.session_state.llm_threshold = st.slider("LLM importance threshold", 0.4, 1.0, 0.75, 0.05)
        st.session_state.llm_max = st.number_input("Max LLM calls per world", 1, 5000, 100)
    if st.button("↻ New world", use_container_width=True):
        st.session_state.world = new_world(int(seed), int(pop), use_llm)
        st.rerun()
    st.divider()
    st.subheader("⏩ Run")
    c1, c2, c3 = st.columns(3)
    if c1.button("1 week", use_container_width=True):
        w.step(7); st.rerun()
    if c2.button("1 year", use_container_width=True):
        with st.spinner("Living…"):
            w.step(365)
        st.rerun()
    if c3.button("10 yrs", use_container_width=True):
        prog = st.progress(0.0)
        for i in range(10):
            w.step(365); prog.progress((i + 1) / 10)
        st.rerun()
    st.divider()
    st.subheader("⚡ God mode")
    shock = st.selectbox("Inject", list(INJECTABLE), format_func=lambda k: f"{k} — {INJECTABLE[k]}")
    if st.button("Smite", use_container_width=True, type="primary"):
        w.inject(shock); st.rerun()
    st.divider()
    st.caption(f"Brain: **{w.brain.name}** · calls so far {w.brain_calls}")
    if hasattr(w.brain, "stats"):
        st.caption(str(w.brain.stats()))

# ------------------------------------------------------------------ header metrics
alive = w.alive()
last = w.history[-1]
st.markdown(f"## Year {w.year}, day {w.day:,} · *{w.policy.ruling_party}* governs")
m = st.columns(8)
prev = w.history[-53] if len(w.history) > 53 else w.history[0]
for col, (label, key, fmt) in zip(m, [("Population", "population", "{:,}"), ("Median wealth", "median_wealth", "£{:,.0f}"),
                                       ("Happiness", "happiness", "{:.0f}%"), ("Unemployment", "unemployment", "{:.0f}%"),
                                       ("Inequality (Gini)", "gini", "{:.2f}"), ("Bread price", "food_price", "£{:.2f}"),
                                       ("Grievance", "grievance", "{:.0f}%"), ("Businesses", "businesses", "{}")]):
    col.metric(label, fmt.format(last[key]), delta=f"{last[key]-prev[key]:+.2f}" if key in ("gini", "food_price") else f"{last[key]-prev[key]:+.0f}",
               delta_color="inverse" if key in ("unemployment", "gini", "food_price", "grievance") else "normal")
if w.pandemic:
    st.error(f"🦠 {w.pandemic['name']} is spreading: {last['infected']} sick, {w.pandemic['deaths']} dead.")
if w.strike:
    st.warning(f"✊ {len(w.strike['members'])} workers are on strike.")
if w.recession_days:
    st.warning(f"📉 Recession: {w.recession_days} days to go.")

tabs = st.tabs(["🗺️ World", "👥 Citizens", "🏛️ Society", "📈 Trajectory", "📜 Chronicle", "🧪 Experiments"])

# ------------------------------------------------------------------ world map
with tabs[0]:
    left, right = st.columns([2.2, 1])
    with left:
        fig = go.Figure()
        colorscale = []
        n = len(TERRAIN_COLOURS)
        for k, c in TERRAIN_COLOURS.items():
            colorscale += [[k / n, c], [(k + 1) / n, c]]
        fig.add_trace(go.Heatmap(z=w.grid, colorscale=colorscale, zmin=0, zmax=n, showscale=False, hoverinfo="skip"))
        bs = w.open_businesses()
        fig.add_trace(go.Scatter(x=[b.x for b in bs], y=[b.y for b in bs], mode="text", text=[BUSINESS_ICON[b.kind] for b in bs],
                                 textfont=dict(size=20), hovertext=[f"{b.name}<br>{len(b.employees)} staff · £{b.cash:,.0f} cash · wage £{b.wage:.0f}" for b in bs],
                                 hoverinfo="text", name="Businesses"))
        df = w.citizens_df()
        if not df.empty:
            jitter = np.random.default_rng(w.day).uniform(-0.4, 0.4, (len(df), 2))
            fig.add_trace(go.Scatter(x=df.x + jitter[:, 0], y=df.y + jitter[:, 1], mode="markers",
                                     marker=dict(size=8, color=[JOB_COLOUR.get(j, "#999") for j in df.job],
                                                 line=dict(width=[2 if i else 0.5 for i in df.infected], color=["#e34948" if i else "#222" for i in df.infected])),
                                     text=df.name, customdata=df[["job", "age", "money", "happiness"]],
                                     hovertemplate="<b>%{text}</b><br>%{customdata[0]}, %{customdata[1]}<br>£%{customdata[2]:,} · happiness %{customdata[3]}%<extra></extra>",
                                     name="Citizens"))
        fig.update_layout(height=600, margin=dict(l=0, r=0, t=0, b=0), paper_bgcolor="rgba(0,0,0,0)", showlegend=False,
                          xaxis=dict(visible=False, range=[-0.5, w.width - 0.5]), yaxis=dict(visible=False, range=[-0.5, w.height - 0.5], scaleanchor="x"),
                          hovermode="closest")
        st.plotly_chart(fig, use_container_width=True)
        st.caption("Citizens are drawn where they spent the day. " + " · ".join(f"<span style='color:{c}'>●</span> {j}" for j, c in JOB_COLOUR.items()), unsafe_allow_html=True)
    with right:
        st.subheader("Recent events")
        for e in w.events[-25:][::-1]:
            icon = {"disaster": "🌪️", "politics": "🗳️", "economy": "💰", "life": "🌱", "society": "💍", "social": "💬", "work": "🔧", "discovery": "💡", "founding": "🏛️", "year": "📅", "collapse": "💀"}.get(e.category, "•")
            weight = "**" if e.importance >= 0.55 else ""
            st.markdown(f"{icon} `d{e.day}` {weight}{e.text}{weight}" + (f" _(brain: {e.brain})_" if e.brain else ""))

# ------------------------------------------------------------------ citizens
with tabs[1]:
    df = w.citizens_df()
    c1, c2 = st.columns([1.3, 1])
    with c1:
        st.dataframe(df.drop(columns=["x", "y"]).sort_values("id"), use_container_width=True, height=520, hide_index=True)
    with c2:
        options = {f"{c.name} (#{c.id}, {c.age_on(w.day)})": c.id for c in sorted(w.citizens.values(), key=lambda c: (not c.alive, c.id))}
        default = max(alive, key=lambda c: len(c.memories)).id if alive else None
        pick = st.selectbox("Inspect a citizen", list(options), index=list(options.values()).index(default) if default else 0)
        cid = options[pick]
        st.markdown(w.biography(cid))
        if st.button("Kill this citizen (god mode)"):
            from civilisation.systems.lifecycle import die
            die(w, w.citizens[cid], "divine intervention"); st.rerun()

# ------------------------------------------------------------------ society
with tabs[2]:
    a, b = st.columns(2)
    with a:
        st.subheader("Political landscape")
        adults = w.adults()
        if adults:
            movs = {m.id: m for m in w.movements.values() if m.alive}
            fig = go.Figure()
            groups = {"Unaffiliated": [c for c in adults if not c.movement_id]}
            for m in movs.values():
                groups[m.name] = [c for c in adults if c.movement_id == m.id]
            for i, (name, cs) in enumerate(groups.items()):
                if not cs:
                    continue
                fig.add_trace(go.Scatter(x=[c.beliefs["economic"] for c in cs], y=[c.beliefs["authority"] for c in cs], mode="markers", name=name,
                                         marker=dict(size=8, color=SERIES[i % len(SERIES)] if i else "#9a9a94", opacity=0.85),
                                         text=[f"{c.name}<br>grievance {c.grievance*100:.0f}%" for c in cs], hoverinfo="text"))
            for i, m in enumerate(movs.values(), start=1):
                fig.add_trace(go.Scatter(x=[m.platform["economic"]], y=[m.platform["authority"]], mode="markers+text", text=[m.name], textposition="top center",
                                         marker=dict(symbol="star", size=18, color=SERIES[i % len(SERIES)], line=dict(width=1, color="#222")), showlegend=False, hoverinfo="skip"))
            fig.update_layout(height=420, xaxis=dict(title="← redistribution · markets →", range=[-1.05, 1.05], zeroline=True),
                              yaxis=dict(title="← liberty · order →", range=[-1.05, 1.05], zeroline=True), **{**LAYOUT, "hovermode": "closest"})
            st.plotly_chart(fig, use_container_width=True)
        pol = w.policy
        st.markdown(f"**Policy** — tax {pol.tax_rate*100:.0f}% · welfare £{pol.welfare:.0f}/day · pension £{pol.pension:.0f}/day · min wage £{pol.min_wage:.0f} · "
                    f"{'public' if pol.public_education else 'private'} schools · {'public' if pol.public_health else 'private'} clinic · treasury £{w.treasury:,.0f} · next election day {w.next_election_day:,}")
        if w.movements:
            st.dataframe(pd.DataFrame([{"name": m.name, "founder": w.citizens[m.founder_id].name, "founded": m.founded_day, "against": m.grievance_theme,
                                        "members": len(m.members), "party": m.is_party, "active": m.alive, "economic": round(m.platform["economic"], 2),
                                        "last votes": m.seats_won} for m in w.movements.values()]), hide_index=True, use_container_width=True)
    with b:
        st.subheader("Social graph")
        g = w.social_graph()
        if g.number_of_nodes() > 1:
            pos = nx.spring_layout(g, seed=1, k=0.6, weight=None)
            ex, ey, ec = [], [], []
            for u, v, d in g.edges(data=True):
                ex += [pos[u][0], pos[v][0], None]; ey += [pos[u][1], pos[v][1], None]
            fig = go.Figure()
            pos_edges = [(u, v) for u, v, d in g.edges(data=True) if d["weight"] > 0]
            neg_edges = [(u, v) for u, v, d in g.edges(data=True) if d["weight"] < 0]
            for edges, colour, name in [(pos_edges, "rgba(42,120,214,0.35)", "friendship"), (neg_edges, "rgba(227,73,72,0.6)", "enmity")]:
                xs, ys = [], []
                for u, v in edges:
                    xs += [pos[u][0], pos[v][0], None]; ys += [pos[u][1], pos[v][1], None]
                fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", line=dict(width=1.2, color=colour), hoverinfo="skip", name=name))
            nodes = list(g.nodes)
            fig.add_trace(go.Scatter(x=[pos[n][0] for n in nodes], y=[pos[n][1] for n in nodes], mode="markers",
                                     marker=dict(size=[6 + 2 * min(8, g.degree(n)) for n in nodes],
                                                 color=[SERIES[(w.citizens[n].movement_id or 0) % len(SERIES)] if w.citizens[n].movement_id else "#9a9a94" for n in nodes],
                                                 line=dict(width=0.5, color="#222")),
                                     text=[f"{w.citizens[n].name}<br>{g.degree(n)} ties" for n in nodes], hoverinfo="text", name="citizens"))
            fig.update_layout(height=420, xaxis=dict(visible=False), yaxis=dict(visible=False), **{**LAYOUT, "hovermode": "closest"})
            st.plotly_chart(fig, use_container_width=True)
            st.caption(f"{g.number_of_nodes()} people, {len(pos_edges)} friendships, {len(neg_edges)} feuds. Node colour = movement.")
        st.subheader("Wealth distribution")
        money = np.array([c.money for c in alive])
        if len(money):
            fig = go.Figure(go.Histogram(x=money, nbinsx=30, marker=dict(color=SERIES[0], line=dict(width=1, color="rgba(0,0,0,0)"))))
            fig.update_layout(height=220, xaxis_title="£", yaxis_title="people", **{**LAYOUT, "hovermode": "x"})
            st.plotly_chart(fig, use_container_width=True)
            top10 = np.sort(money)[-max(1, len(money) // 10):].sum() / max(1, money.sum())
            st.caption(f"Top 10% hold {top10*100:.0f}% of wealth. Gini {w.gini:.2f}.")

# ------------------------------------------------------------------ trajectory
with tabs[3]:
    h = w.metrics_df()
    panels = [("People", [("population", "Population", SERIES[0]), ("infected", "Infected", SERIES[7])]),
              ("Money", [("median_wealth", "Median wealth £", SERIES[0]), ("avg_wealth", "Mean wealth £", SERIES[1])]),
              ("Mood", [("happiness", "Happiness %", SERIES[2]), ("grievance", "Grievance %", SERIES[7]), ("unemployment", "Unemployment %", SERIES[1])]),
              ("Inequality", [("gini", "Gini", SERIES[6])]),
              ("Prices & tech", [("food_price", "Bread £", SERIES[3]), ("tech", "Technology ×", SERIES[2])]),
              ("State", [("treasury", "Treasury £", SERIES[0]), ("businesses", "Businesses", SERIES[1]), ("movements", "Movements", SERIES[4])])]
    cols = st.columns(2)
    for i, (title, series) in enumerate(panels):
        fig = go.Figure()
        for key, name, colour in series:
            fig.add_trace(go.Scatter(x=h.day / 365, y=h[key], mode="lines", name=name, line=dict(width=2, color=colour)))
        for e in w.chronicle:
            if e.importance >= 0.75 and e.category in ("disaster", "politics", "economy", "discovery"):
                fig.add_vline(x=e.day / 365, line=dict(width=1, dash="dot", color="rgba(120,120,120,0.5)"))
        fig.update_layout(title=title, height=260, xaxis_title="year", showlegend=len(series) > 1, **LAYOUT)
        cols[i % 2].plotly_chart(fig, use_container_width=True)
    st.caption("Dotted lines mark major disasters, elections and economic shocks.")

# ------------------------------------------------------------------ chronicle
with tabs[4]:
    text = chronicle_text(w)
    st.markdown(text)
    st.download_button("Download chronicle.md", text, "chronicle.md")
    if st.button("🎬 Narrate with Claude (one API call)"):
        try:
            from civilisation.llm import narrate
            with st.spinner("Writing the documentary…"):
                st.session_state.narration = narrate(w)
        except Exception as e:
            st.error(f"Could not narrate: {e}")
    if st.session_state.get("narration"):
        st.markdown("---")
        st.markdown(st.session_state.narration)

# ------------------------------------------------------------------ experiments
with tabs[5]:
    st.markdown("Run scenarios across many seeds and compare the **distributions** of outcomes — this is the point of the project.")
    chosen = st.multiselect("Scenarios", list(SCENARIOS), default=["baseline", "automation"])
    c1, c2, c3 = st.columns(3)
    seeds = c1.slider("Seeds per scenario", 2, 30, 6)
    years = c2.slider("Years", 2, 60, 15)
    workers = c3.slider("Parallel workers", 1, 8, 4)
    if st.button("Run experiment", type="primary") and chosen:
        with st.spinner(f"Running {len(chosen)*seeds} worlds for {years} years each…"):
            st.session_state.exp = compare(chosen, seeds=range(seeds), years=years, workers=workers)
    df = st.session_state.get("exp")
    if df is not None:
        st.dataframe(summary(df), use_container_width=True)
        metrics = ["population", "median_wealth", "gini", "unemployment", "happiness", "grievance", "parties", "deaths"]
        cols = st.columns(2)
        for i, mtr in enumerate(metrics):
            fig = go.Figure()
            for j, sc in enumerate(df.scenario.unique()):
                fig.add_trace(go.Box(y=df[df.scenario == sc][mtr], name=sc, marker=dict(color=SERIES[j % len(SERIES)]), boxpoints="all", jitter=0.4, pointpos=0))
            fig.update_layout(title=mtr, height=280, showlegend=False, **{**LAYOUT, "hovermode": "closest"})
            cols[i % 2].plotly_chart(fig, use_container_width=True)
        st.download_button("Download raw results.csv", df.to_csv(index=False), "results.csv")

st.divider()
st.caption("New Haven v0.2 · deterministic core, optional LLM cognition · seed "
           f"{w.seed} · {len(w.citizens)} people ever lived here")
