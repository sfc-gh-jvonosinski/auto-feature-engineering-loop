"""
Auto Feature Engineering Loop
==============================
Uses Cortex Code Agent SDK for feature ideation (judgment/reasoning).
Everything else is deterministic Python/SQL.

Usage:
    python main_loop.py                    # run with defaults (20 iterations)
    python main_loop.py --max-iterations 5 # override max iterations
    python main_loop.py --resume           # resume a previous run
"""
import asyncio
import json
import time
import argparse
from pathlib import Path
from datetime import datetime

from cortex_code_agent_sdk import (
    query,
    CortexCodeAgentOptions,
    ResultMessage,
    AssistantMessage,
)

# Snowpark for deterministic data operations
from snowflake.snowpark import Session

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "snowflake": {
        "database": "AUTO_FEATURE_ENG",
        "schema": "CREDIT_RISK",
        "warehouse": "AICOLLEGE",
    },
    "agent": {
        "model": "auto",
        "max_turns": 10,
    },
    "loop": {
        "max_iterations": 20,
        "improvement_threshold": 0.001,
        "pivot_threshold": 3,
        "max_features_per_iter": 4,
    },
    "cost": {
        "max_cost_usd": 15.0,
        "credit_rate_usd": 3.0,
    },
}


def load_config(path: Path) -> dict:
    """Load config from YAML file, falling back to defaults."""
    if path.exists():
        import yaml
        with open(path) as f:
            user_cfg = yaml.safe_load(f) or {}
        # Merge with defaults
        cfg = DEFAULT_CONFIG.copy()
        for key in user_cfg:
            if isinstance(cfg.get(key), dict):
                cfg[key].update(user_cfg[key])
            else:
                cfg[key] = user_cfg[key]
        return cfg
    return DEFAULT_CONFIG


# ---------------------------------------------------------------------------
# State management (JSON file)
# ---------------------------------------------------------------------------

STATE_FILE = Path(__file__).parent / "state.json"


def load_state(run_id: str) -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            state = json.load(f)
        if state.get("run_id") == run_id or run_id == "__resume__":
            return state
    return {
        "run_id": run_id,
        "current_iter": 0,
        "best_auc": 0.0,
        "best_iter": -1,
        "baseline_auc": 0.0,
        "stale_count": 0,
        "tried_categories": [],
        "total_cost_usd": 0.0,
    }


def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


# ---------------------------------------------------------------------------
# Snowpark session
# ---------------------------------------------------------------------------

def create_session(config: dict) -> Session:
    """Create Snowpark session using Snowflake CLI connection config."""
    sf_cfg = config["snowflake"]
    connection_name = sf_cfg.get("connection_name", "DEMO_ACCT")

    builder = Session.builder.configs({
        "connection_name": connection_name,
        "database": sf_cfg["database"],
        "schema": sf_cfg["schema"],
        "warehouse": sf_cfg["warehouse"],
        "role": sf_cfg.get("role", "ACCOUNTADMIN"),
    })
    return builder.create()


# ---------------------------------------------------------------------------
# Feature ideation via Cortex Code Agent SDK
# ---------------------------------------------------------------------------

FEATURE_SCHEMA = {
    "type": "object",
    "properties": {
        "features": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "sql_expression": {"type": "string"},
                    "rationale": {"type": "string"},
                },
                "required": ["name", "sql_expression", "rationale"],
            },
        },
        "strategy": {"type": "string"},
        "reasoning": {"type": "string"},
    },
    "required": ["features", "strategy", "reasoning"],
}


async def ideate_features(
    iteration: int,
    state: dict,
    config: dict,
    project_dir: Path,
) -> tuple[dict, dict]:
    """
    Invoke Cortex Code Agent SDK to propose new features.
    The agent can run SQL to explore data and read the feature log.
    Returns (feature_spec, sdk_cost_info).
    """
    stale_count = state.get("stale_count", 0)
    best_auc = state.get("best_auc", 0)
    run_id = state["run_id"]
    tried = state.get("tried_categories", [])

    # Build the prompt - agent will use SQL tool to explore data
    prompt = f"""You are a feature engineering agent for sub-prime credit risk modeling.

TASK: Propose 2-4 new engineered features for iteration {iteration}.

DATABASE CONTEXT:
- Database: AUTO_FEATURE_ENG, Schema: CREDIT_RISK
- Source table: AUTO_FEATURE_ENG.CREDIT_RISK.RAW_CREDIT_DATA
- Feature log: AUTO_FEATURE_ENG.CREDIT_RISK.FEATURE_LOG (WHERE RUN_ID = '{run_id}')
- Current best AUC: {best_auc:.6f}
- Stale iterations (no improvement): {stale_count}

INSTRUCTIONS:
1. Run SQL: SELECT * FROM AUTO_FEATURE_ENG.CREDIT_RISK.FEATURE_LOG WHERE RUN_ID = '{run_id}' ORDER BY ITERATION_ID
   to see what features were already tried and their results.
2. Run SQL against RAW_CREDIT_DATA to understand distributions (e.g. AVG, percentiles, correlations with target).
3. Propose 2-4 NEW features with valid Snowflake SQL expressions.
4. Categories already tried: {json.dumps(tried)}
   {"YOU MUST PIVOT to a completely new category since " + str(stale_count) + " iterations had no improvement." if stale_count >= 3 else ""}

AVAILABLE COLUMNS in RAW_CREDIT_DATA:
- REVOLVING_UTILIZATION (float): total balance on credit cards / credit limit
- AGE (int): borrower age
- PAST_DUE_30_59 (int): times 30-59 days past due in last 2 years
- DEBT_RATIO (float): monthly debt payments / gross income
- MONTHLY_INCOME (float, has NULLs): monthly gross income
- OPEN_CREDIT_LINES (int): number of open loans + credit lines
- PAST_DUE_90 (int): times 90+ days late
- REAL_ESTATE_LINES (int): number of mortgage/RE loans
- PAST_DUE_60_89 (int): times 60-89 days past due
- DEPENDENTS (float, has NULLs): number of dependents

SQL RULES:
- Use NULLIF(x, 0) to avoid division by zero
- Use COALESCE(col, default) for nullable columns
- Use IFF(condition, then, else) for conditionals
- Use LEAST/GREATEST for capping values
- Use LN(x + 1) for log transforms
- Use WIDTH_BUCKET(col, min, max, num_buckets) for binning
- Feature names must be UPPER_SNAKE_CASE

Read program.md in the current directory for additional context on feature categories.
"""

    sdk_cost = {"usd": 0.0, "tokens_in": 0, "tokens_out": 0, "duration_ms": 0}
    result_data = None

    async for msg in query(
        prompt=prompt,
        options=CortexCodeAgentOptions(
            cwd=str(project_dir),
            model=config["agent"]["model"],
            max_turns=config["agent"]["max_turns"],
            output_format={"type": "json_schema", "schema": FEATURE_SCHEMA},
            permission_mode="bypassPermissions",
            allow_dangerously_skip_permissions=True,
        ),
    ):
        if isinstance(msg, AssistantMessage):
            # Agent is working (running SQL, reading files, reasoning)
            for block in msg.content:
                if hasattr(block, "text") and block.text:
                    # Print agent's reasoning for visibility
                    print(f"  [Agent] {block.text[:200]}")
        elif isinstance(msg, ResultMessage):
            sdk_cost["usd"] = msg.total_cost_usd or 0.0
            sdk_cost["tokens_in"] = (msg.usage or {}).get("input_tokens", 0)
            sdk_cost["tokens_out"] = (msg.usage or {}).get("output_tokens", 0)
            sdk_cost["duration_ms"] = msg.duration_ms or 0
            result_data = msg.structured_output

    if not result_data:
        raise RuntimeError("Cortex Code Agent SDK did not return structured output")

    return result_data, sdk_cost


# ---------------------------------------------------------------------------
# Deterministic: Execute feature generation
# ---------------------------------------------------------------------------

def execute_features(session: Session, feature_spec: dict, iteration: int, config: dict) -> str:
    """Build and execute CTAS to create the feature table."""
    db = config["snowflake"]["database"]
    schema = config["snowflake"]["schema"]
    source_table = f"{db}.{schema}.RAW_CREDIT_DATA"
    output_table = f"{db}.{schema}.FEATURES_ITER_{iteration}"

    # Build SELECT with all raw columns plus new features
    feature_expressions = []
    for feat in feature_spec.get("features", []):
        name = feat["name"].upper().replace(" ", "_")[:60]
        expr = feat["sql_expression"]
        feature_expressions.append(f"  {expr} AS {name}")

    new_features_sql = ",\n".join(feature_expressions)

    ctas_sql = f"""
CREATE OR REPLACE TABLE {output_table} AS
SELECT
  ID,
  SERIOUSDLQIN2YRS,
  REVOLVING_UTILIZATION,
  AGE,
  PAST_DUE_30_59,
  DEBT_RATIO,
  MONTHLY_INCOME,
  OPEN_CREDIT_LINES,
  PAST_DUE_90,
  REAL_ESTATE_LINES,
  PAST_DUE_60_89,
  DEPENDENTS,
{new_features_sql}
FROM {source_table}
"""
    print(f"  [SQL] Creating {output_table} with {len(feature_spec.get('features', []))} new features...")
    try:
        session.sql(ctas_sql).collect()
        return output_table
    except Exception as e:
        raise RuntimeError(f"Feature CTAS failed: {e}\nSQL: {ctas_sql}")


# ---------------------------------------------------------------------------
# Deterministic: Train and evaluate
# ---------------------------------------------------------------------------

def train_and_evaluate(session: Session, feature_table: str, iteration: int, run_id: str) -> dict:
    """Call the fixed training stored procedure."""
    print(f"  [Train] Calling TRAIN_AND_EVALUATE on {feature_table}...")
    result = session.sql(f"""
        CALL AUTO_FEATURE_ENG.CREDIT_RISK.TRAIN_AND_EVALUATE(
            '{feature_table}', {iteration}, '{run_id}'
        )
    """).collect()

    # Extract metrics from variant result
    metrics_row = session.sql(f"""
        SELECT
            $1:auc::FLOAT as auc,
            $1:ks_stat::FLOAT as ks_stat,
            $1:gini::FLOAT as gini,
            $1:n_features::INT as n_features
        FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()))
    """).collect()

    if not metrics_row:
        raise RuntimeError("Training SP returned no results")

    row = metrics_row[0]
    return {
        "auc": float(row["AUC"]),
        "ks_stat": float(row["KS_STAT"]),
        "gini": float(row["GINI"]),
        "n_features": int(row["N_FEATURES"]),
    }


# ---------------------------------------------------------------------------
# Deterministic: Decision logic
# ---------------------------------------------------------------------------

def decide(metrics: dict, state: dict, config: dict) -> str:
    """Pure threshold comparison — no LLM needed."""
    threshold = config["loop"]["improvement_threshold"]
    if metrics["auc"] > state["best_auc"] + threshold:
        return "keep"
    return "discard"


# ---------------------------------------------------------------------------
# Deterministic: Logging
# ---------------------------------------------------------------------------

def log_iteration(
    session: Session,
    iteration: int,
    run_id: str,
    feature_spec: dict | None,
    metrics: dict | None,
    status: str,
    state: dict,
    error_msg: str = "",
):
    """Log iteration results to FEATURE_LOG."""
    features_json = json.dumps(feature_spec.get("features", [])) if feature_spec else "[]"
    strategy = feature_spec.get("strategy", "") if feature_spec else ""
    reasoning = feature_spec.get("reasoning", "") if feature_spec else ""
    auc = metrics["auc"] if metrics else 0.0
    ks = metrics["ks_stat"] if metrics else 0.0
    gini = metrics["gini"] if metrics else 0.0
    n_feat = metrics["n_features"] if metrics else 0
    delta = auc - state["best_auc"] if metrics else 0.0

    session.sql(f"""
        INSERT INTO AUTO_FEATURE_ENG.CREDIT_RISK.FEATURE_LOG
        (ITERATION_ID, RUN_ID, FEATURE_TABLE, FEATURES_ADDED, NUM_FEATURES,
         AUC, KS_STAT, GINI, DELTA_AUC, STATUS, STRATEGY, REASONING, ERROR_MSG)
        VALUES (
            {iteration}, '{run_id}', 'FEATURES_ITER_{iteration}',
            PARSE_JSON($${features_json}$$),
            {n_feat}, {auc}, {ks}, {gini}, {delta},
            '{status}', '{strategy[:200]}',
            '{reasoning[:500].replace(chr(39), "")}',
            '{error_msg[:500].replace(chr(39), "")}'
        )
    """).collect()


def log_cost(
    session: Session,
    iteration: int,
    run_id: str,
    sdk_cost: dict | None,
    duration: float,
):
    """Log cost to COST_LOG."""
    usd = sdk_cost["usd"] if sdk_cost else 0.0
    tokens_in = sdk_cost.get("tokens_in", 0) if sdk_cost else 0
    tokens_out = sdk_cost.get("tokens_out", 0) if sdk_cost else 0

    session.sql(f"""
        INSERT INTO AUTO_FEATURE_ENG.CREDIT_RISK.COST_LOG
        (ITERATION_ID, RUN_ID, PHASE, SDK_COST_USD, CREDITS_WAREHOUSE,
         CREDITS_TOTAL, SDK_TOKENS_IN, SDK_TOKENS_OUT, DURATION_SEC)
        VALUES (
            {iteration}, '{run_id}', 'total',
            {usd}, 0, {usd}, {tokens_in}, {tokens_out}, {duration}
        )
    """).collect()


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

async def run_loop(config: dict, resume: bool = False):
    """Main orchestration loop."""
    project_dir = Path(__file__).parent
    run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    if resume:
        state = load_state("__resume__")
        run_id = state["run_id"]
        print(f"Resuming run: {run_id} at iteration {state['current_iter']}")
    else:
        state = load_state(run_id)
        state["run_id"] = run_id
        print(f"Starting new run: {run_id}")

    # Establish baseline if first run (short-lived session)
    if state["baseline_auc"] == 0.0:
        print("\n--- Establishing baseline ---")
        session = create_session(config)
        try:
            session.sql(f"ALTER SESSION SET QUERY_TAG = '{run_id}'").collect()
            baseline = train_and_evaluate(
                session, "AUTO_FEATURE_ENG.CREDIT_RISK.RAW_CREDIT_DATA", -1, run_id
            )
            state["baseline_auc"] = baseline["auc"]
            state["best_auc"] = baseline["auc"]
            print(f"  Baseline AUC: {baseline['auc']:.6f}")
            save_state(state)
        finally:
            session.close()

    max_iter = config["loop"]["max_iterations"]
    print(f"\n{'='*60}")
    print(f"  AUTO FEATURE ENGINEERING LOOP")
    print(f"  Baseline AUC: {state['baseline_auc']:.6f}")
    print(f"  Max iterations: {max_iter}")
    print(f"  Cost ceiling: ${config['cost']['max_cost_usd']:.2f}")
    print(f"{'='*60}\n")

    for i in range(state["current_iter"], max_iter):
        print(f"\n{'─'*60}")
        print(f"  ITERATION {i+1}/{max_iter}")
        print(f"  Best AUC: {state['best_auc']:.6f} | Stale: {state['stale_count']}")
        print(f"{'─'*60}")
        t0 = time.time()
        sdk_cost = None

        # Phase 1: SDK inference — no Snowpark session needed.
        # The SDK manages its own connection internally.
        print("  [Phase 1] Feature ideation (Cortex Code Agent SDK)...")
        try:
            feature_spec, sdk_cost = await ideate_features(i, state, config, project_dir)
            print(f"  [Phase 1] Got {len(feature_spec.get('features', []))} features, strategy: {feature_spec.get('strategy', '?')}")
        except Exception as e:
            print(f"  ✗ CRASH in ideation: {e}")
            feature_spec = None

        # Phases 2-6: Snowpark session for SQL operations.
        # Session is created after inference completes and closed at end of iteration.
        session = create_session(config)
        try:
            session.sql(f"ALTER SESSION SET QUERY_TAG = '{run_id}'").collect()

            if feature_spec is None:
                # Ideation failed — log crash and continue
                log_iteration(session, i, run_id, None, None, "crash", state, "Ideation failed")
            else:
                try:
                    # 2. DETERMINISTIC: Execute feature CTAS
                    print("  [Phase 2] Executing feature SQL...")
                    feat_table = execute_features(session, feature_spec, i, config)

                    # 3. DETERMINISTIC: Train and evaluate
                    print("  [Phase 3] Training model...")
                    metrics = train_and_evaluate(session, feat_table, i, run_id)
                    print(f"  [Phase 3] AUC: {metrics['auc']:.6f} (delta: {metrics['auc'] - state['best_auc']:+.6f})")

                    # 4. DETERMINISTIC: Decision
                    status = decide(metrics, state, config)
                    if status == "keep":
                        state["best_auc"] = metrics["auc"]
                        state["best_iter"] = i
                        state["stale_count"] = 0
                        strategy = feature_spec.get("strategy", "")
                        if strategy and strategy not in state["tried_categories"]:
                            state["tried_categories"].append(strategy)
                        print(f"  ✓ KEEP — new best AUC: {metrics['auc']:.6f}")
                    else:
                        state["stale_count"] += 1
                        print(f"  ✗ DISCARD — no improvement (stale: {state['stale_count']})")

                    # 5. Log success
                    log_iteration(session, i, run_id, feature_spec, metrics, status, state)

                except Exception as e:
                    print(f"  ✗ CRASH: {e}")
                    log_iteration(session, i, run_id, None, None, "crash", state, str(e)[:500])

            # 6. Log cost (always, including on crash)
            duration = time.time() - t0
            log_cost(session, i, run_id, sdk_cost, duration)

        finally:
            session.close()

        # Track cumulative cost
        if sdk_cost:
            state["total_cost_usd"] = state.get("total_cost_usd", 0) + sdk_cost["usd"]

        # 7. Check cost ceiling
        if state["total_cost_usd"] > config["cost"]["max_cost_usd"]:
            print(f"\n  COST CEILING REACHED (${state['total_cost_usd']:.2f} > ${config['cost']['max_cost_usd']:.2f}). Stopping.")
            break

        # 8. Persist state
        state["current_iter"] = i + 1
        save_state(state)

    # Summary
    print(f"\n{'='*60}")
    print(f"  RUN COMPLETE: {run_id}")
    print(f"  Baseline AUC: {state['baseline_auc']:.6f}")
    print(f"  Best AUC:     {state['best_auc']:.6f} (iter {state['best_iter']})")
    print(f"  Improvement:  {state['best_auc'] - state['baseline_auc']:+.6f}")
    print(f"  Total cost:   ${state['total_cost_usd']:.4f}")
    print(f"{'='*60}")

    return state


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Auto Feature Engineering Loop")
    parser.add_argument("--max-iterations", type=int, default=None)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--config", type=str, default="config.yaml")
    args = parser.parse_args()

    config = load_config(Path(__file__).parent / args.config)
    if args.max_iterations:
        config["loop"]["max_iterations"] = args.max_iterations

    asyncio.run(run_loop(config, resume=args.resume))


if __name__ == "__main__":
    main()
