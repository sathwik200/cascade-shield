"""Cascade Shield - Interactive Streamlit Dashboard.

An Intelligent Framework for Cascading Failure Containment and Recovery
in Distributed Microservice Systems.
"""

from __future__ import annotations

import time
import pandas as pd
import streamlit as st

from cascade_shield.config import (
    FAULT_UNAVAILABLE,
    FAULT_HIGH_LATENCY,
    FAULT_HIGH_ERROR_RATE,
    FAULT_TIMEOUT,
    ACTION_OPEN_CIRCUIT_BREAKER,
    ACTION_RATE_LIMIT,
    ACTION_ISOLATE,
    ACTION_RESTART,
    ACTION_FAILOVER,
    ACTION_RETRY_WITH_BACKOFF,
    ACTION_DEFER_AND_ALERT,
    ACTION_RESTORE_TRAFFIC,
    DEFAULT_EXPERIMENT_DURATION,
)
from cascade_shield.graph.profiles import (
    DOMAIN_KEYS,
    PROFILES,
    build_topology,
    get_scenario_names,
    build_failure_scenarios,
)
from cascade_shield.models.service import (
    FailureScenario,
    FaultType,
    HealthState,
    CircuitState,
    ContainmentAction,
)
from cascade_shield.failure.simulator import FailureSimulator
from cascade_shield.containment.policies import ContainmentManager
from cascade_shield.engine.decision_engine import DecisionEngine
from cascade_shield.recovery.manager import RecoveryManager
from cascade_shield.metrics.collector import MetricsCollector
from cascade_shield.experiment.runner import ExperimentRunner, POLICY_LABELS

# pyrefly: ignore[missing-import]
from components.styles import get_custom_css
# pyrefly: ignore[missing-import]
from components.topology_view import create_topology_figure
# pyrefly: ignore[missing-import]
from components.metrics_view import (
    create_availability_chart,
    create_health_distribution_chart,
    create_policy_comparison_chart,
    create_policy_metrics_bar,
)


# ---------------------------------------------------------------------------
# App Configuration & Setup
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Cascade Shield | Microservice Failure Containment",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(get_custom_css(), unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Session State Initialization
# ---------------------------------------------------------------------------
def init_system(domain: str = "ecommerce"):
    graph = build_topology(domain)
    simulator = FailureSimulator(graph, seed=42)
    containment = ContainmentManager(graph)
    engine = DecisionEngine(graph, containment)
    recovery = RecoveryManager(graph)
    metrics = MetricsCollector(graph)

    # Initial snapshot
    metrics.snapshot()

    st.session_state.domain = domain
    st.session_state.graph = graph
    st.session_state.simulator = simulator
    st.session_state.containment = containment
    st.session_state.engine = engine
    st.session_state.recovery = recovery
    st.session_state.metrics = metrics
    st.session_state.selected_service = None
    st.session_state.highlight_blast = False
    st.session_state.sim_tick = 0
    st.session_state.active_faults = []
    st.session_state.comparison_result = None


if "graph" not in st.session_state:
    init_system("ecommerce")


# ---------------------------------------------------------------------------
# Simulation Step Function
# ---------------------------------------------------------------------------
def step_simulation(apply_containment: bool = True):
    sim = st.session_state.simulator
    graph = st.session_state.graph
    cm = st.session_state.containment
    eng = st.session_state.engine
    rec = st.session_state.recovery
    met = st.session_state.metrics

    st.session_state.sim_tick += 1

    # 1. Simulator step
    sim.step()

    # 2. Intelligent Containment (Cascade Shield Policy)
    if apply_containment:
        for svc in list(graph.services.values()):
            if svc.health in (HealthState.FAILED, HealthState.DEGRADED):
                if not sim.is_contained(svc.service_id) or (svc.health == HealthState.FAILED and not svc.is_isolated):
                    recommendation = eng.recommend(svc.service_id)
                    if recommendation.feasible:
                        res = cm.execute_action(recommendation)
                        if res.success:
                            sim.set_contained(svc.service_id)

        # 3. Recovery step
        if st.session_state.sim_tick > 3:
            rec.recover_cascade()

    # 4. Tick containment and recovery
    cm.tick()
    rec.tick()

    # 5. Metrics snapshot
    met.tick()


# ---------------------------------------------------------------------------
# Header Section
# ---------------------------------------------------------------------------
col_title, col_stat = st.columns([2.5, 1])

with col_title:
    st.markdown(
        """
        <div style="margin-bottom: 8px;">
            <span class="badge-healthy" style="margin-bottom: 6px;">● ONLINE SIMULATOR</span>
            <span class="badge-recovering" style="margin-bottom: 6px;">STAGED RECOVERY ENGINE</span>
            <span class="badge-isolated" style="margin-bottom: 6px;">EXPLAINABLE HEURISTIC AI</span>
        </div>
        <h1 class="cs-title">Cascade Shield</h1>
        <p class="cs-subtitle">Intelligent Framework for Cascading Failure Containment and Recovery in Microservice Systems</p>
        """,
        unsafe_allow_html=True,
    )

with col_stat:
    cur_domain = st.session_state.domain
    selected_domain = st.selectbox(
        "Active Domain Architecture",
        options=DOMAIN_KEYS,
        index=DOMAIN_KEYS.index(cur_domain),
        format_func=lambda d: PROFILES[d]["name"],
        key="domain_selector_top",
    )
    if selected_domain != cur_domain:
        init_system(selected_domain)
        st.rerun()


# ---------------------------------------------------------------------------
# Global Metrics Strip
# ---------------------------------------------------------------------------
history = st.session_state.metrics.history
latest = history[-1] if history else None

eff_avail = f"{latest.effective_availability * 100:.1f}%" if latest else "100.0%"
crit_avail = f"{latest.critical_availability * 100:.1f}%" if latest else "100.0%"
healthy_count = latest.healthy_count if latest else st.session_state.graph.service_count
degraded_count = latest.degraded_count if latest else 0
failed_count = latest.failed_count if latest else 0
cascades = st.session_state.simulator.cascade_count
cur_tick = st.session_state.sim_tick

m1, m2, m3, m4, m5, m6 = st.columns(6)
with m1:
    st.markdown(f'<div class="metric-box"><div class="metric-value">{cur_tick}</div><div class="metric-label">Sim Tick</div></div>', unsafe_allow_html=True)
with m2:
    st.markdown(f'<div class="metric-box"><div class="metric-value" style="color:#00f2fe;">{eff_avail}</div><div class="metric-label">Effective Avail</div></div>', unsafe_allow_html=True)
with m3:
    st.markdown(f'<div class="metric-box"><div class="metric-value" style="color:#a855f7;">{crit_avail}</div><div class="metric-label">Critical Avail</div></div>', unsafe_allow_html=True)
with m4:
    st.markdown(f'<div class="metric-box"><div class="metric-value" style="color:#00e676;">{healthy_count}</div><div class="metric-label">Healthy Nodes</div></div>', unsafe_allow_html=True)
with m5:
    st.markdown(f'<div class="metric-box"><div class="metric-value" style="color:#ff1744;">{failed_count + degraded_count}</div><div class="metric-label">Degraded/Failed</div></div>', unsafe_allow_html=True)
with m6:
    st.markdown(f'<div class="metric-box"><div class="metric-value" style="color:#ffab00;">{cascades}</div><div class="metric-label">Cascades Blocked</div></div>', unsafe_allow_html=True)

st.write("")

# ---------------------------------------------------------------------------
# Main Navigation Tabs
# ---------------------------------------------------------------------------
tab_topo, tab_fault, tab_engine, tab_bench, tab_arch = st.tabs([
    "🛡️ Live Topology & Simulation",
    "⚡ Fault Injection Studio",
    "🧠 Decision Engine & Containment",
    "📊 Benchmark Arena & Policy Comparison",
    "🏛️ Domain Profiles & Architecture",
])


# ===========================================================================
# TAB 1: Live Topology & Simulation
# ===========================================================================
with tab_topo:
    # Controls strip
    ctrl_col1, ctrl_col2, ctrl_col3, ctrl_col4, ctrl_col5 = st.columns([1, 1, 1, 1.5, 2.5])
    with ctrl_col1:
        if st.button("▶ Step 1 Tick", key="btn_step_tick", use_container_width=True):
            step_simulation(apply_containment=True)
            st.rerun()

    with ctrl_col2:
        if st.button("⏩ Run 5 Ticks", key="btn_run_5", use_container_width=True):
            for _ in range(5):
                step_simulation(apply_containment=True)
            st.rerun()

    with ctrl_col3:
        if st.button("🔄 Reset Cluster", key="btn_reset_cluster", use_container_width=True):
            init_system(st.session_state.domain)
            st.rerun()

    with ctrl_col4:
        st.session_state.highlight_blast = st.checkbox("Highlight Blast Radius", value=st.session_state.highlight_blast, key="chk_blast")

    with ctrl_col5:
        # Quick service selector for inspection
        services = list(st.session_state.graph.services.keys())
        idx = services.index(st.session_state.selected_service) if st.session_state.selected_service in services else 0
        st.session_state.selected_service = st.selectbox(
            "Inspect Service Node",
            options=services,
            index=idx,
            format_func=lambda s: f"{st.session_state.graph.get_service(s).display_name} ({s})",
            key="sel_node_inspect",
        )

    col_graph, col_info = st.columns([2.3, 1.2])

    with col_graph:
        st.markdown('<div class="cs-card">', unsafe_allow_html=True)
        st.markdown("### Interactive Microservice Dependency Graph")
        fig_topo = create_topology_figure(
            st.session_state.graph,
            selected_service=st.session_state.selected_service,
            highlight_blast=st.session_state.highlight_blast,
            height=540,
        )
        st.plotly_chart(fig_topo, use_container_width=True, key="plotly_topo_main")

        # Health chart below graph
        st.markdown("### Real-Time Availability & Health Trend")
        fig_avail = create_availability_chart(st.session_state.metrics.history, height=260)
        st.plotly_chart(fig_avail, use_container_width=True, key="plotly_avail_trend")
        st.markdown('</div>', unsafe_allow_html=True)

    with col_info:
        # Node Details Card
        st.markdown('<div class="cs-card">', unsafe_allow_html=True)
        sel_id = st.session_state.selected_service
        if sel_id and st.session_state.graph.has_service(sel_id):
            svc = st.session_state.graph.get_service(sel_id)
            health_color = {
                HealthState.HEALTHY: "badge-healthy",
                HealthState.DEGRADED: "badge-degraded",
                HealthState.FAILED: "badge-failed",
                HealthState.ISOLATED: "badge-isolated",
                HealthState.RECOVERING: "badge-recovering",
            }.get(svc.health, "badge-healthy")

            st.markdown(f"### {svc.display_name}")
            st.markdown(f'<span class="{health_color}">● {svc.health.value}</span> <span class="badge-recovering">{svc.criticality.value} CRITICALITY</span>', unsafe_allow_html=True)
            st.write("")

            col_a, col_b = st.columns(2)
            with col_a:
                st.metric("Circuit Breaker", svc.circuit_state.value)
                st.metric("Traffic Pct", f"{svc.traffic_percentage:.0%}")
            with col_b:
                st.metric("Recovery Attempts", f"{svc.recovery_attempts}/5")
                st.metric("Rate Limited", "Yes" if svc.is_rate_limited else "No")

            if svc.active_backup_id:
                st.info(f"🔄 Active Failover Target: **{svc.active_backup_id}**")

            # Blast radius summary for node
            impact = st.session_state.graph.analyze_impact(sel_id)
            st.markdown(f"**Blast Radius:** `{impact.blast_radius}` service(s)")
            if impact.directly_affected:
                st.markdown(f"- **Direct Callers:** {', '.join(impact.directly_affected)}")
            if impact.transitively_affected:
                st.markdown(f"- **Transitive Callers:** {', '.join(impact.transitively_affected)}")

            # Quick Containment trigger
            st.markdown("---")
            st.markdown("**Manual Operator Override**")
            col_ov1, col_ov2 = st.columns(2)
            with col_ov1:
                if st.button("Open Circuit", key="btn_ov_open_cb", use_container_width=True):
                    st.session_state.containment.execute_action(ContainmentAction(ACTION_OPEN_CIRCUIT_BREAKER, sel_id))
                    st.session_state.simulator.set_contained(sel_id)
                    st.rerun()
            with col_ov2:
                if st.button("Isolate Service", key="btn_ov_isolate", use_container_width=True):
                    st.session_state.containment.execute_action(ContainmentAction(ACTION_ISOLATE, sel_id))
                    st.session_state.simulator.set_contained(sel_id)
                    st.rerun()

        st.markdown('</div>', unsafe_allow_html=True)

        # Event stream card
        st.markdown('<div class="cs-card">', unsafe_allow_html=True)
        st.markdown("### Simulation Event Stream")
        events = st.session_state.simulator.events[-12:]
        if not events:
            st.caption("No events recorded yet. Step simulation or inject faults.")
        else:
            for ev in reversed(events):
                st.markdown(
                    f'<div class="event-row event-{ev.severity}">'
                    f'<b>[T+{ev.tick}] {ev.event_type}</b> ({ev.service_id})<br>'
                    f'{ev.description}'
                    f'</div>',
                    unsafe_allow_html=True,
                )
        st.markdown('</div>', unsafe_allow_html=True)


# ===========================================================================
# TAB 2: Fault Injection Studio
# ===========================================================================
with tab_fault:
    st.markdown('<div class="cs-card">', unsafe_allow_html=True)
    st.markdown("## Failure Injection Studio")
    st.markdown("Inject realistic faults into single or multiple microservices to evaluate cascading failure behavior.")

    col_preset, col_custom = st.columns([1, 1])

    with col_preset:
        st.markdown("### 🎯 Preset Scenarios (Domain Specific)")
        scenario_names = get_scenario_names(st.session_state.domain)
        preset_sc = st.selectbox("Choose Preset Scenario", options=scenario_names, key="preset_sc_select")

        # Find scenario description
        cur_sc_info = next((sc for sc in PROFILES[st.session_state.domain]["scenarios"] if sc["name"] == preset_sc), None)
        if cur_sc_info:
            st.info(f"**Description:** {cur_sc_info.get('description', '')}\n\n**Injected Faults:** `{cur_sc_info.get('failures', [])}`")

        if st.button("🚀 Inject Preset Scenario", key="btn_inject_preset", use_container_width=True):
            scenarios = build_failure_scenarios(st.session_state.domain, preset_sc)
            st.session_state.simulator.inject_failures(scenarios)
            st.session_state.active_faults.extend(scenarios)
            st.success(f"Injected preset scenario: {preset_sc}!")
            st.rerun()

    with col_custom:
        st.markdown("### 🛠️ Custom Fault Generator")
        custom_target = st.selectbox("Target Microservice", options=st.session_state.graph.service_ids, key="cust_target")
        custom_type = st.selectbox("Fault Type", options=[FAULT_UNAVAILABLE, FAULT_HIGH_LATENCY, FAULT_HIGH_ERROR_RATE, FAULT_TIMEOUT], key="cust_type")
        custom_duration = st.slider("Duration (Ticks)", min_value=1, max_value=30, value=10, key="cust_duration")
        custom_severity = st.slider("Fault Severity", min_value=0.1, max_value=1.0, value=1.0, step=0.1, key="cust_severity")

        if st.button("🔥 Inject Custom Fault", key="btn_inject_custom", use_container_width=True):
            scenario = FailureScenario(
                target_service_id=custom_target,
                fault_type=FaultType(custom_type),
                duration_ticks=custom_duration,
                severity=custom_severity,
                description=f"Manual custom injection of {custom_type}",
            )
            st.session_state.simulator.inject_failure(scenario)
            st.session_state.active_faults.append(scenario)
            st.success(f"Injected {custom_type} fault into {custom_target}!")
            st.rerun()

    st.markdown('</div>', unsafe_allow_html=True)

    # Active Faults and Blast Radius analysis table
    st.markdown('<div class="cs-card">', unsafe_allow_html=True)
    st.markdown("### Active Injected Faults & Blast Radius Analysis")

    active_svcs = [svc for svc in st.session_state.graph.services.values() if svc.active_failure is not None]
    if not active_svcs:
        st.caption("No active faults currently injected.")
    else:
        fault_data = []
        for svc in active_svcs:
            f = svc.active_failure
            impact = st.session_state.graph.analyze_impact(svc.service_id)
            fault_data.append({
                "Service": svc.display_name,
                "Fault Type": f.fault_type.value,
                "Ticks Remaining": svc.failure_ticks_remaining,
                "Severity": f"{f.severity:.1f}",
                "Direct Callers Affected": len(impact.directly_affected),
                "Transitive Blast Radius": impact.blast_radius,
                "Critical Services At Risk": len(impact.critical_services_at_risk),
            })
        st.dataframe(pd.DataFrame(fault_data), use_container_width=True)

        if st.button("🧹 Clear All Faults", key="btn_clear_all_faults"):
            st.session_state.simulator.clear_all_failures()
            st.rerun()

    st.markdown('</div>', unsafe_allow_html=True)


# ===========================================================================
# TAB 3: Decision Engine & Containment
# ===========================================================================
with tab_engine:
    st.markdown('<div class="cs-card">', unsafe_allow_html=True)
    st.markdown("## Intelligent Decision Engine & Heuristic Explainability")
    st.markdown(
        "Cascade Shield evaluates candidate containment actions using a multi-factor weighted scoring model. "
        "Every decision is deterministic, transparent, and auditable."
    )

    col_target_sel, col_w = st.columns([1, 2])
    with col_target_sel:
        unhealthy_or_all = [
            sid for sid, s in st.session_state.graph.services.items()
            if s.health != HealthState.HEALTHY
        ] or st.session_state.graph.service_ids

        eval_service = st.selectbox(
            "Select Service for Decision Audit",
            options=unhealthy_or_all,
            format_func=lambda s: f"{st.session_state.graph.get_service(s).display_name} [{st.session_state.graph.get_service(s).health.value}]",
            key="sel_eval_service",
        )

    candidates = st.session_state.engine.evaluate(eval_service)
    best_action = candidates[0] if candidates else None

    if best_action:
        st.markdown(
            f"""
            <div style="background: rgba(0, 242, 254, 0.08); border: 1px solid rgba(0, 242, 254, 0.3); border-radius: 12px; padding: 16px; margin: 16px 0;">
                <h4 style="margin: 0; color: #00f2fe;">🏆 Top Recommended Action: {best_action.action_type} (Score: {best_action.score:.3f})</h4>
                <p style="margin-top: 6px; margin-bottom: 0; color: #e2e8f0;">{best_action.explanation}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # Detailed table of candidates
    cand_data = []
    for c in candidates:
        cand_data.append({
            "Action Type": c.action_type,
            "Feasible": "✅ Feasible" if c.feasible else "❌ Infeasible",
            "Score": round(c.score, 3),
            "Explanation & Rationale": c.explanation,
        })
    st.dataframe(pd.DataFrame(cand_data), use_container_width=True)

    st.markdown('</div>', unsafe_allow_html=True)

    # Decision Engine Weights Reference
    st.markdown('<div class="cs-card">', unsafe_allow_html=True)
    st.markdown("### Heuristic Decision Scoring Weights")
    st.markdown(
        """
        | Factor | Weight | Description |
        |---|---|---|
        | **Criticality** | `0.25` | Priority assigned to Tier-1 critical business paths |
        | **Blast Radius** | `0.20` | Upstream caller dependency graph impact |
        | **Failure Severity** | `0.20` | Impact score based on fault type (Unavailable = 1.0, Timeout = 0.8) |
        | **Dependency Impact** | `0.15` | Critical dependencies threatened |
        | **Feasibility Penalty** | `-100.0` | Infeasible actions disqualified immediately |
        | **Recovery Penalty** | `-0.10` | Repeated failure recovery attempt budget consumption |
        """
    )
    st.markdown('</div>', unsafe_allow_html=True)


# ===========================================================================
# TAB 4: Benchmark Arena & Policy Comparison
# ===========================================================================
with tab_bench:
    st.markdown('<div class="cs-card">', unsafe_allow_html=True)
    st.markdown("## Comparative Policy Benchmarking Arena")
    st.markdown(
        "Rigorous, reproducible comparison between three containment paradigms under identical conditions: "
        "**No Containment**, **Simple Circuit Breakers**, and **Cascade Shield**."
    )

    b_col1, b_col2 = st.columns([1.5, 1])
    with b_col1:
        bench_domain = st.selectbox("Benchmark Domain", options=DOMAIN_KEYS, format_func=lambda d: PROFILES[d]["name"], key="bench_domain_sel")
        bench_scenario = st.selectbox("Benchmark Scenario", options=get_scenario_names(bench_domain), key="bench_sc_sel")

    with b_col2:
        st.write("")
        st.write("")
        if st.button("⚔️ Run Comparative Policy Test", key="btn_run_comp_policy", use_container_width=True):
            with st.spinner("Executing comparative simulation runs across all 3 policies..."):
                runner = ExperimentRunner()
                res = runner.run_scenario(bench_domain, bench_scenario, duration=DEFAULT_EXPERIMENT_DURATION, seed=42)
                st.session_state.comparison_result = res

    res = st.session_state.comparison_result
    if res:
        winner_label = POLICY_LABELS.get(res.winner, res.winner)
        st.markdown(
            f"""
            <div style="background: rgba(0, 230, 118, 0.1); border: 1px solid rgba(0, 230, 118, 0.4); border-radius: 12px; padding: 18px; margin: 16px 0;">
                <h3 style="margin: 0; color: #00e676;">🏆 Winner: {winner_label}</h3>
                <p style="margin: 6px 0 0 0; color: #94a3b8;">
                    Cascade Shield Availability Improvement over No Containment: <b>{res.shield_improvement:.1f}%</b>
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.plotly_chart(create_policy_comparison_chart(res, height=360), use_container_width=True, key="plotly_comp_line")
        st.plotly_chart(create_policy_metrics_bar(res, height=300), use_container_width=True, key="plotly_comp_bar")

        # Metric table
        table_rows = []
        for policy, pr in res.policy_results.items():
            table_rows.append({
                "Policy": POLICY_LABELS.get(policy, policy),
                "Min Availability": f"{pr.min_availability * 100:.2f}%",
                "Avg Availability": f"{pr.avg_availability * 100:.2f}%",
                "Peak Affected Services": pr.peak_affected,
                "Cascades Blocked / Triggered": pr.cascade_count,
                "Downtime Ticks": pr.downtime_ticks,
                "Recovery Duration (Ticks)": pr.recovery_time,
                "Containment Actions Executed": pr.containment_actions,
            })
        st.dataframe(pd.DataFrame(table_rows), use_container_width=True)

    st.markdown('</div>', unsafe_allow_html=True)

    # Full Suite Benchmark Runner
    st.markdown('<div class="cs-card">', unsafe_allow_html=True)
    st.markdown("### 🏆 Full Benchmark Suite (All 16 Scenarios)")
    if st.button("🚀 Run Full 16-Scenario Benchmark", key="btn_run_full_bench"):
        with st.spinner("Running full benchmark across all 4 domain profiles (16 scenarios)..."):
            runner = ExperimentRunner()
            suite_results = runner.run_benchmark(duration=30, seed=42)
            st.session_state.suite_results = suite_results

    if "suite_results" in st.session_state:
        sr = st.session_state.suite_results
        w1, w2, w3 = st.columns(3)
        with w1:
            st.metric("Cascade Shield Wins", sr.wins.get("cascade_shield", 0))
        with w2:
            st.metric("Simple Circuit Breaker Wins", sr.wins.get("simple_circuit_breaker", 0))
        with w3:
            st.metric("Ties", sr.ties)

        suite_rows = []
        for s in sr.scenarios:
            cs = s.policy_results.get("cascade_shield")
            cb = s.policy_results.get("simple_circuit_breaker")
            nc = s.policy_results.get("no_containment")
            suite_rows.append({
                "Domain": s.domain,
                "Scenario": s.scenario,
                "Winner": POLICY_LABELS.get(s.winner, s.winner),
                "No Containment Min": f"{nc.min_availability * 100:.1f}%" if nc else "-",
                "Simple CB Min": f"{cb.min_availability * 100:.1f}%" if cb else "-",
                "Cascade Shield Min": f"{cs.min_availability * 100:.1f}%" if cs else "-",
                "Cascades (CS / CB / NC)": f"{cs.cascade_count} / {cb.cascade_count} / {nc.cascade_count}" if cs and cb and nc else "-",
            })
        st.dataframe(pd.DataFrame(suite_rows), use_container_width=True)

    st.markdown('</div>', unsafe_allow_html=True)


# ===========================================================================
# TAB 5: Domain Profiles & Architecture
# ===========================================================================
with tab_arch:
    st.markdown('<div class="cs-card">', unsafe_allow_html=True)
    st.markdown("## Domain Profiles & Topological Architecture")
    st.markdown("Inspect the 4 comprehensive microservice architectures modeled in Cascade Shield.")

    sel_p_domain = st.selectbox("Select Domain Profile", options=DOMAIN_KEYS, format_func=lambda d: PROFILES[d]["name"], key="sel_arch_domain")
    p_data = PROFILES[sel_p_domain]

    st.markdown(f"### {p_data['name']}")
    st.markdown(f"*{p_data['description']}*")

    st.markdown("#### 1. Registered Microservices")
    svc_rows = []
    for s in p_data["services"]:
        svc_rows.append({
            "Service ID": s["id"],
            "Display Name": s["name"],
            "Criticality Tier": s["criticality"],
            "Failover Backup Service": s.get("backup", "None"),
        })
    st.dataframe(pd.DataFrame(svc_rows), use_container_width=True)

    st.markdown("#### 2. Directed Dependency Graph")
    dep_rows = []
    for d in p_data["dependencies"]:
        dep_rows.append({
            "Source (Caller)": d["source"],
            "Target (Dependency)": d["target"],
            "Critical Edge": "Yes (Strict SLA)" if d.get("critical", True) else "No (Optional/Fallback)",
        })
    st.dataframe(pd.DataFrame(dep_rows), use_container_width=True)

    st.markdown('</div>', unsafe_allow_html=True)
