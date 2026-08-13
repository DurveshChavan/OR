"""Streamlit dashboard for the SLA-driven ticket allocation pipeline.

Thin UI layer only: every OR computation is delegated to src/. This file
just wires widgets to src.pipeline's composable stage functions and plots
the results.
"""
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st

from src.m0_data import make_synthetic
from src.m7_replacement import workstation_factors
from src.pipeline import (
    _reassigned_tickets,
    assignment_stage,
    choose_replacements,
    distribute_regions,
    make_escalation_decision,
    plan_major_incident,
    sequence_sample_batch,
    size_capacity,
)

st.set_page_config(page_title="SLA Ticket Allocation", layout="wide")


@st.cache_data
def load_data(n_tickets, n_agents, n_workstations, seed):
    return make_synthetic(n_tickets, n_agents, n_workstations, seed=seed)


def assignment_table(tickets, agents, matrix, pairs):
    rows = []
    for r, c in pairs:
        rows.append({
            "ticket": tickets.iloc[r]["id"],
            "agent": agents.iloc[c]["id"],
            "cost": matrix[r][c],
        })
    return pd.DataFrame(rows)


def plot_heatmap(matrix, title):
    matrix = np.array(matrix, dtype=float)
    fig, ax = plt.subplots(figsize=(4, 3))
    im = ax.imshow(matrix, cmap="viridis")
    for i in range(matrix.shape[0]):
        for j in range(matrix.shape[1]):
            ax.text(j, i, f"{matrix[i, j]:.0f}", ha="center", va="center", color="white", fontsize=8)
    ax.set_xlabel("demand region")
    ax.set_ylabel("supply region")
    ax.set_title(title)
    fig.colorbar(im, ax=ax, fraction=0.046)
    return fig


def plot_gantt(schedule):
    activities = list(schedule["ES"].keys())
    fig, ax = plt.subplots(figsize=(6, 0.5 * len(activities) + 1))
    for i, act in enumerate(activities):
        es, ef = schedule["ES"][act], schedule["EF"][act]
        color = "crimson" if act in schedule["critical_path"] else "steelblue"
        ax.barh(i, ef - es, left=es, color=color, height=0.5)
        ax.text(es, i, f" {act}", va="center", fontsize=8)
    ax.set_yticks(range(len(activities)))
    ax.set_yticklabels(activities)
    ax.set_xlabel("time")
    ax.set_title(f"CPM schedule (critical path in red), duration={schedule['project_duration']:.1f}")
    ax.invert_yaxis()
    return fig


def plot_stage_costs(stage_costs):
    fig, ax = plt.subplots(figsize=(4, 3))
    names = list(stage_costs.keys())
    values = list(stage_costs.values())
    colors = ["steelblue", "darkorange", "seagreen"][: len(names)]
    ax.bar(names, values, color=colors)
    ax.set_ylabel("total resolution cost")
    ax.set_title("Cost by stage")
    for i, v in enumerate(values):
        ax.text(i, v, f"{v:.0f}", ha="center", va="bottom", fontsize=9)
    return fig


st.title("SLA-Driven Ticket Allocation, Escalation & Hardware Replacement")

with st.sidebar:
    st.header("Synthetic data")
    n_tickets = st.slider("n_tickets", 10, 200, 50)
    n_agents = st.slider("n_agents", 5, 200, 150)
    n_workstations = st.slider("n_workstations", 5, 50, 20)
    seed = st.slider("seed", 0, 1000, 42)
    run_clicked = st.button("Run pipeline", type="primary")

    st.header("Hardware ageing")
    age_toggle = st.toggle("Age workstations")
    age_by_months = st.slider("age by N months", 0, 60, 24, disabled=not age_toggle)

if run_clicked or "data" not in st.session_state:
    st.session_state["data"] = load_data(n_tickets, n_agents, n_workstations, seed)
    st.session_state["tickets"] = st.session_state["data"]["tickets"]
    st.session_state["agents"] = st.session_state["data"]["agents"]
    st.session_state["workstations"] = st.session_state["data"]["workstations"]
    st.session_state["replaced"] = False

if "data" not in st.session_state:
    st.info("Click **Run pipeline** in the sidebar to generate data and solve the model.")
    st.stop()

tickets = st.session_state["tickets"]
agents = st.session_state["agents"]
workstations = st.session_state["workstations"]

baseline = assignment_stage(tickets, agents, degradation=None)

aged = None
aged_workstations = workstations
if age_toggle:
    aged_workstations = workstations.copy()
    aged_workstations["age_months"] = aged_workstations["age_months"] + age_by_months
    aged_factors = workstation_factors(aged_workstations)
    aged = assignment_stage(tickets, agents, degradation=aged_factors)

replacement = choose_replacements(aged_workstations if age_toggle else workstations)

post = None
if age_toggle:
    st.sidebar.header("Replacement")
    replace_clicked = st.sidebar.button("Replace recommended workstations")
    if replace_clicked:
        st.session_state["replaced"] = True
    if st.session_state.get("replaced"):
        replaced_workstations = aged_workstations.copy()
        replaced_workstations.loc[
            replaced_workstations["id"].isin(replacement["to_replace"]), "age_months"
        ] = 0
        post_factors = workstation_factors(replaced_workstations)
        post = assignment_stage(tickets, agents, degradation=post_factors)

tabs = st.tabs(["M1 Capacity", "M2 Transport", "M3 Assignment", "M4 Sequencing",
                 "M5 Escalation", "M6 CPM/PERT", "M7 Replacement"])

with tabs[0]:
    st.subheader("M1 — Capacity allocation (LPP / Simplex)")
    m1 = size_capacity(tickets, agents)
    st.write(f"Status: **{m1['status']}**  |  Total staffing cost: **{m1['total_cost']:.0f}**")
    st.dataframe(pd.DataFrame(m1["agents_per_skill"].items(), columns=["skill", "agents"]))

with tabs[1]:
    st.subheader("M2 — Regional distribution (transportation problem)")
    m2 = distribute_regions()
    st.write(f"Total transport cost: **{m2['total_cost']:.1f}**")
    st.pyplot(plot_heatmap(m2["allocation"], "Region allocation"))

with tabs[2]:
    st.subheader("M3 — Agent-to-ticket assignment (Hungarian)")
    st.write(f"Baseline total resolution cost: **{baseline['total_cost']:.1f}**")
    st.dataframe(assignment_table(tickets, agents, baseline["matrix"], baseline["pairs"]))

    if age_toggle and aged is not None:
        col1, col2 = st.columns(2)
        col1.metric("Baseline cost", f"{baseline['total_cost']:.1f}")
        col2.metric("Aged cost", f"{aged['total_cost']:.1f}", delta=f"{aged['total_cost'] - baseline['total_cost']:.1f}")

        reassigned = _reassigned_tickets(baseline["pairs"], aged["pairs"])
        st.write(f"Reassigned tickets after ageing: **{len(reassigned)}**")
        if reassigned:
            st.dataframe(pd.DataFrame({"ticket": [tickets.iloc[r]["id"] for r in reassigned]}))

        if post is not None:
            col3 = st.columns(1)[0]
            col3.metric("Post-replacement cost", f"{post['total_cost']:.1f}", delta=f"{post['total_cost'] - aged['total_cost']:.1f}")

        stage_costs = {"baseline": baseline["total_cost"], "aged": aged["total_cost"]}
        if post is not None:
            stage_costs["replaced"] = post["total_cost"]
        st.pyplot(plot_stage_costs(stage_costs))
    elif age_toggle:
        st.info("Toggle is on but ageing hasn't been applied yet — adjust the age slider.")

with tabs[3]:
    st.subheader("M4 — Sequencing (Johnson's rule)")
    m4 = sequence_sample_batch(tickets)
    st.write(f"Sequence: **{' -> '.join(m4['sequence'])}**")
    st.write(f"Makespan: **{m4['makespan']:.1f} minutes**")
    st.dataframe(pd.DataFrame(m4["schedule"]))

with tabs[4]:
    st.subheader("M5 — Escalation decision (EMV)")
    m5 = make_escalation_decision()
    st.write(f"Recommended action: **{m5['acts'][m5['best_index']]}**  (EMV = {m5['best_value']:.2f})")
    st.bar_chart(pd.DataFrame({"act": m5["acts"], "EMV": m5["values"]}).set_index("act"))

with tabs[5]:
    st.subheader("M6 — CPM / PERT (major-incident plan)")
    m6 = plan_major_incident()
    schedule, probability = m6["schedule"], m6["probability"]
    st.write(f"Critical path: **{' -> '.join(schedule['critical_path'])}**")
    st.write(f"Project duration: **{schedule['project_duration']:.1f}h**")
    st.write(f"P(finish by deadline): **{probability['probability']:.2f}** (Z = {probability['z']:.2f})")
    st.pyplot(plot_gantt(schedule))

with tabs[6]:
    st.subheader("M7 — Replacement recommendation")
    st.write(f"Fleet economic replacement age: **{replacement['replace_threshold_months']} months**")
    st.write(f"Optimal single-item replacement year: **{replacement['deteriorating']['optimal_year']}**")
    st.dataframe(pd.DataFrame(replacement["deteriorating"]["table"]))
    st.write(f"Workstations flagged for replacement: **{replacement['to_replace']}**")
    st.write(
        f"Group-vs-individual: cheaper policy is **{replacement['group']['cheaper_policy']}** "
        f"(group @ interval {replacement['group']['optimal_group_interval']} = "
        f"{replacement['group']['optimal_group_average_cost']:.2f}, "
        f"individual = {replacement['group']['individual_average_cost']:.2f})"
    )
