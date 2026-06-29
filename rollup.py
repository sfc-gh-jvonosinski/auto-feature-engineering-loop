"""
Results Rollup — Visual Summary of a Completed Run
====================================================
Queries FEATURE_LOG and COST_LOG, generates charts and summary metrics.

Usage:
    python rollup.py                       # uses most recent run
    python rollup.py --run-id run_20250629_143000
    streamlit run rollup.py                # interactive dashboard
"""
import argparse
import json
from pathlib import Path

from snowflake.snowpark import Session

# Try importing plotting libraries
try:
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    HAS_MPL = True
except ImportError:
    HAS_MPL = False

try:
    import streamlit as st
    HAS_STREAMLIT = True
except ImportError:
    HAS_STREAMLIT = False


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def get_session() -> Session:
    return Session.builder.configs({
        "connection_name": "DEMO_ACCT",
        "database": "AUTO_FEATURE_ENG",
        "schema": "CREDIT_RISK",
        "warehouse": "AICOLLEGE",
        "role": "ACCOUNTADMIN",
    }).create()


def get_latest_run_id(session: Session) -> str:
    result = session.sql("""
        SELECT RUN_ID FROM FEATURE_LOG
        ORDER BY TS DESC LIMIT 1
    """).collect()
    if not result:
        raise ValueError("No runs found in FEATURE_LOG")
    return result[0]["RUN_ID"]


def load_feature_log(session: Session, run_id: str):
    return session.sql(f"""
        SELECT ITERATION_ID, AUC, KS_STAT, GINI, DELTA_AUC,
               STATUS, STRATEGY, NUM_FEATURES, FEATURES_ADDED, REASONING
        FROM FEATURE_LOG
        WHERE RUN_ID = '{run_id}'
        ORDER BY ITERATION_ID
    """).to_pandas()


def load_cost_log(session: Session, run_id: str):
    return session.sql(f"""
        SELECT ITERATION_ID, SDK_COST_USD, CREDITS_WAREHOUSE,
               CREDITS_TOTAL, SDK_TOKENS_IN, SDK_TOKENS_OUT, DURATION_SEC
        FROM COST_LOG
        WHERE RUN_ID = '{run_id}'
        ORDER BY ITERATION_ID
    """).to_pandas()


# ---------------------------------------------------------------------------
# Matplotlib report (static HTML/PNG)
# ---------------------------------------------------------------------------

def generate_matplotlib_report(feature_log, cost_log, run_id: str, output_dir: Path):
    """Generate a multi-panel matplotlib report."""
    if not HAS_MPL:
        print("matplotlib not installed. Install with: pip install matplotlib")
        return

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle(f"Auto Feature Engineering — Run: {run_id}", fontsize=14, fontweight="bold")

    # Panel 1: AUC progression
    ax = axes[0, 0]
    kept = feature_log[feature_log["STATUS"] == "keep"]
    discarded = feature_log[feature_log["STATUS"] == "discard"]
    crashed = feature_log[feature_log["STATUS"] == "crash"]

    if not discarded.empty:
        ax.scatter(discarded["ITERATION_ID"], discarded["AUC"], c="red", marker="x", s=60, label="Discarded", zorder=3)
    if not kept.empty:
        ax.scatter(kept["ITERATION_ID"], kept["AUC"], c="green", marker="o", s=80, label="Kept", zorder=3)
    if not crashed.empty:
        ax.scatter(crashed["ITERATION_ID"], crashed["AUC"], c="gray", marker="^", s=60, label="Crash", zorder=3)

    # Running best line
    running_best = feature_log["AUC"].expanding().max()
    ax.plot(feature_log["ITERATION_ID"], running_best, "b--", alpha=0.7, label="Running Best")

    ax.set_xlabel("Iteration")
    ax.set_ylabel("AUC")
    ax.set_title("AUC Progression")
    ax.legend(loc="lower right")
    ax.grid(True, alpha=0.3)

    # Panel 2: Cost per iteration
    ax = axes[0, 1]
    if not cost_log.empty:
        ax.bar(cost_log["ITERATION_ID"], cost_log["SDK_COST_USD"], color="steelblue", alpha=0.8)
        ax.set_xlabel("Iteration")
        ax.set_ylabel("SDK Cost (USD)")
        ax.set_title("Cost per Iteration")
        ax.grid(True, alpha=0.3, axis="y")

    # Panel 3: Cumulative cost
    ax = axes[1, 0]
    if not cost_log.empty:
        cumulative = cost_log["SDK_COST_USD"].cumsum()
        ax.fill_between(cost_log["ITERATION_ID"], cumulative, alpha=0.3, color="steelblue")
        ax.plot(cost_log["ITERATION_ID"], cumulative, "b-", linewidth=2)
        ax.set_xlabel("Iteration")
        ax.set_ylabel("Cumulative Cost (USD)")
        ax.set_title("Cumulative Spend")
        ax.grid(True, alpha=0.3)

    # Panel 4: Strategy distribution
    ax = axes[1, 1]
    if "STRATEGY" in feature_log.columns:
        strategy_counts = feature_log["STRATEGY"].value_counts()
        if not strategy_counts.empty:
            colors = plt.cm.Set3(range(len(strategy_counts)))
            ax.pie(strategy_counts.values, labels=strategy_counts.index,
                   autopct="%1.0f%%", colors=colors)
            ax.set_title("Strategy Distribution")

    plt.tight_layout()
    out_path = output_dir / f"rollup_{run_id}.png"
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"Report saved to: {out_path}")
    plt.close()


# ---------------------------------------------------------------------------
# Summary metrics
# ---------------------------------------------------------------------------

def print_summary(feature_log, cost_log, run_id: str):
    """Print text summary of the run."""
    total_iter = len(feature_log)
    kept_count = len(feature_log[feature_log["STATUS"] == "keep"])
    discard_count = len(feature_log[feature_log["STATUS"] == "discard"])
    crash_count = len(feature_log[feature_log["STATUS"] == "crash"])

    baseline_auc = feature_log["AUC"].iloc[0] - feature_log["DELTA_AUC"].iloc[0] if len(feature_log) > 0 else 0
    best_auc = feature_log["AUC"].max() if len(feature_log) > 0 else 0
    improvement = best_auc - baseline_auc

    total_cost = cost_log["SDK_COST_USD"].sum() if not cost_log.empty else 0
    total_duration = cost_log["DURATION_SEC"].sum() if not cost_log.empty else 0

    print(f"""
{'='*60}
  RUN SUMMARY: {run_id}
{'='*60}

  Iterations:      {total_iter}
  Kept:            {kept_count}
  Discarded:       {discard_count}
  Crashed:         {crash_count}
  Success Rate:    {kept_count/max(total_iter,1)*100:.1f}%

  Baseline AUC:    {baseline_auc:.6f}
  Best AUC:        {best_auc:.6f}
  Improvement:     {improvement:+.6f}

  Total Cost:      ${total_cost:.4f}
  Total Duration:  {total_duration:.0f}s ({total_duration/60:.1f}min)
  Cost/Iteration:  ${total_cost/max(total_iter,1):.4f}
  Cost/AUC Point:  ${total_cost/max(improvement, 0.0001):.2f} per +0.001 AUC
{'='*60}
""")


# ---------------------------------------------------------------------------
# Streamlit dashboard (optional)
# ---------------------------------------------------------------------------

def streamlit_dashboard():
    """Interactive Streamlit dashboard."""
    if not HAS_STREAMLIT:
        return

    st.set_page_config(page_title="Auto Feature Engineering Results", layout="wide")
    st.title("Auto Feature Engineering — Results Dashboard")

    session = get_session()

    # Get available runs
    runs = session.sql("SELECT DISTINCT RUN_ID FROM FEATURE_LOG ORDER BY RUN_ID DESC").to_pandas()
    if runs.empty:
        st.warning("No runs found in FEATURE_LOG")
        return

    run_id = st.selectbox("Select Run", runs["RUN_ID"].tolist())

    feature_log = load_feature_log(session, run_id)
    cost_log = load_cost_log(session, run_id)

    if feature_log.empty:
        st.warning("No data for this run")
        return

    # Metrics row
    col1, col2, col3, col4 = st.columns(4)
    best_auc = feature_log["AUC"].max()
    baseline = feature_log["AUC"].iloc[0] - feature_log["DELTA_AUC"].iloc[0]
    col1.metric("Best AUC", f"{best_auc:.4f}", f"{best_auc - baseline:+.4f}")
    col2.metric("Iterations", len(feature_log))
    col3.metric("Kept", len(feature_log[feature_log["STATUS"] == "keep"]))
    col4.metric("Total Cost", f"${cost_log['SDK_COST_USD'].sum():.3f}" if not cost_log.empty else "$0")

    # Charts
    st.subheader("AUC Progression")
    st.line_chart(feature_log.set_index("ITERATION_ID")["AUC"])

    if not cost_log.empty:
        st.subheader("Cost per Iteration")
        st.bar_chart(cost_log.set_index("ITERATION_ID")["SDK_COST_USD"])

    # Detail table
    st.subheader("Iteration Details")
    st.dataframe(feature_log[["ITERATION_ID", "AUC", "DELTA_AUC", "STATUS", "STRATEGY", "NUM_FEATURES"]])

    session.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    # Check if running under streamlit
    import sys
    if "streamlit" in sys.modules.get("__main__", object).__class__.__module__ if hasattr(sys.modules.get("__main__"), "__class__") else False:
        streamlit_dashboard()
        return

    parser = argparse.ArgumentParser(description="Auto Feature Engineering — Results Rollup")
    parser.add_argument("--run-id", type=str, default=None, help="Run ID to analyze")
    parser.add_argument("--output", type=str, default=".", help="Output directory for charts")
    args = parser.parse_args()

    session = get_session()

    run_id = args.run_id or get_latest_run_id(session)
    print(f"Analyzing run: {run_id}")

    feature_log = load_feature_log(session, run_id)
    cost_log = load_cost_log(session, run_id)

    if feature_log.empty:
        print("No data found for this run.")
        session.close()
        return

    print_summary(feature_log, cost_log, run_id)
    generate_matplotlib_report(feature_log, cost_log, run_id, Path(args.output))

    session.close()


if __name__ == "__main__":
    # Support both direct execution and streamlit
    try:
        import streamlit
        if hasattr(streamlit, "runtime") and streamlit.runtime.exists():
            streamlit_dashboard()
        else:
            main()
    except (ImportError, AttributeError):
        main()
