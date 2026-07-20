"""
Auto Feature Engineering Loop
==============================
Uses Cortex Code Agent SDK for feature ideation (judgment/reasoning).
Everything else is deterministic Python/SQL.

Usage:
    python main_loop.py                    # run with defaults (20 iterations)
    python main_loop.py --max-iterations 5 # override max iterations
    python main_loop.py --resume           # resume a previous run
    python main_loop.py -v                 # verbose (show agent reasoning)
    python main_loop.py -q                 # quiet (decisions and errors only)
    python main_loop.py --no-live          # disable rich status panel (CI/pipes)
"""
import asyncio
import json
import logging
import logging.handlers
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

# Snowflake ML — Feature Store and Model Registry
from snowflake.ml.feature_store import FeatureStore, FeatureView, Entity, CreationMode

# Rich — optional terminal status panel
try:
    from rich.live import Live
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text
    from rich.console import Console
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

# ---------------------------------------------------------------------------
# Logging setup (Snowflake-aligned: Python logging module with extra attrs)
# ---------------------------------------------------------------------------

def setup_logging(run_id: str, verbosity: str = "normal") -> logging.Logger:
    """
    Configure logging with file + console handlers.

    Uses Python's logging module — the same API Snowflake uses in stored
    procedures and event tables. Structured extra={} attributes map to
    RECORD_ATTRIBUTES in Snowflake event tables if ported to server-side.
    """
    logger = logging.getLogger("auto_fe")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    # Ensure logs/ directory exists
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)

    # File handler — persistent, rotated, captures everything
    fh = logging.handlers.RotatingFileHandler(
        log_dir / f"{run_id}.log", maxBytes=5_000_000, backupCount=3
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-5s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    ))
    logger.addHandler(fh)

    # Console handler — respects verbosity
    ch = logging.StreamHandler()
    level_map = {"verbose": logging.DEBUG, "normal": logging.INFO, "quiet": logging.WARNING}
    ch.setLevel(level_map.get(verbosity, logging.INFO))
    ch.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-5s %(message)s", datefmt="%H:%M:%S"
    ))
    logger.addHandler(ch)

    return logger


# ---------------------------------------------------------------------------
# Live terminal status panel (rich)
# ---------------------------------------------------------------------------

class LoopMonitor:
    """Auto-updating terminal status panel using rich.live.Live.

    Renders a live panel to stderr showing current iteration, best AUC,
    stale count, cost, and the last 4 iteration outcomes. Falls back to
    _NoOpMonitor when rich is unavailable or --no-live is set.
    """

    def __init__(self, run_id: str, max_iter: int, cost_ceiling: float, enabled: bool = True):
        self.run_id = run_id
        self.max_iter = max_iter
        self.cost_ceiling = cost_ceiling
        self.current_iter = 0
        self.phase = "setup"
        self.best_auc = 0.0
        self.best_iter = -1
        self.stale_count = 0
        self.cost_usd = 0.0
        self.iter_start = time.time()
        self.run_start = time.time()
        self.history: list[tuple[int, str, float, str]] = []  # (iter, status, auc, strategy)
        self.enabled = enabled and HAS_RICH
        self._live = None

    def start(self):
        if self.enabled:
            self._live = Live(
                self._render(),
                console=Console(stderr=True),
                refresh_per_second=2,
                transient=True,
            )
            self._live.start()

    def stop(self):
        if self._live:
            self._live.stop()
            self._live = None

    def update(self, **kwargs):
        for k, v in kwargs.items():
            if hasattr(self, k):
                setattr(self, k, v)
        if self._live:
            self._live.update(self._render())

    def add_history(self, iteration: int, status: str, auc: float, strategy: str):
        self.history.append((iteration, status, auc, strategy))
        if len(self.history) > 5:
            self.history = self.history[-5:]

    def _render(self) -> Panel:
        elapsed = time.time() - self.iter_start
        total_elapsed = time.time() - self.run_start
        mins, secs = divmod(int(elapsed), 60)
        t_mins, t_secs = divmod(int(total_elapsed), 60)

        # Status line
        lines = []
        lines.append(
            f" Run: {self.run_id} | Iter: {self.current_iter}/{self.max_iter} "
            f"| Phase: {self.phase} | {mins}:{secs:02d} iter / {t_mins}:{t_secs:02d} total"
        )
        lines.append(
            f" Best AUC: {self.best_auc:.6f} (iter {self.best_iter}) "
            f"| Stale: {self.stale_count} "
            f"| Cost: ${self.cost_usd:.2f} / ${self.cost_ceiling:.2f}"
        )

        # History row
        if self.history:
            hist_parts = []
            for (it, st, auc, strat) in self.history[-4:]:
                icon = "\u2713" if st == "keep" else "\u2717" if st == "discard" else "!"
                hist_parts.append(f"#{it+1} {icon} {auc:.4f} {strat[:12]}")
            lines.append(" " + " | ".join(hist_parts))

        content = Text("\n".join(lines))
        return Panel(content, title="Auto Feature Eng Loop", border_style="blue")


class _NoOpMonitor:
    """Fallback when rich is unavailable or --no-live is set."""
    def start(self): pass
    def stop(self): pass
    def update(self, **kwargs): pass
    def add_history(self, *args, **kwargs): pass


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
        "max_turns": 10,  # max SDK back-and-forth turns per ideation call
    },
    "loop": {
        "max_iterations": 20,
        "improvement_threshold": 0.001,  # min AUC delta to accept a feature set
        "pivot_threshold": 3,            # stale iterations before forcing a strategy pivot
        "max_features_per_iter": 4,
    },
    "cost": {
        "max_cost_usd": 15.0,
        "credit_rate_usd": 3.0,  # USD per Snowflake credit, used for cost estimation
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
    # "__resume__" is a sentinel: load whatever run is saved regardless of ID
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
        "client_store_temporary_credential": True,
    })
    return builder.create()


# ---------------------------------------------------------------------------
# Infrastructure setup (idempotent)
# ---------------------------------------------------------------------------

_SP_BODY = r'''
import json
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score
from scipy.stats import ks_2samp
import xgboost as xgb

def run(session, feature_table_name, iteration_id, run_id, register_model=False):
    df = session.table(feature_table_name).to_pandas()

    target = 'SERIOUSDLQIN2YRS'
    exclude = ['ID', target]
    feature_cols = [c for c in df.columns if c not in exclude]

    X = df[feature_cols].fillna(0).astype(float)
    y = df[target].astype(int)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, stratify=y, random_state=42
    )

    # Compute class-imbalance weight: XGBoost scale_pos_weight = neg/pos
    # so the minority default class is up-weighted during training.
    pos_count = int(y_train.sum())
    neg_count = int(len(y_train) - pos_count)
    scale_pos = neg_count / max(pos_count, 1)

    model = xgb.XGBClassifier(
        n_estimators=200,
        max_depth=6,
        learning_rate=0.1,
        scale_pos_weight=scale_pos,
        random_state=42,
        eval_metric='auc',
        verbosity=0,
        use_label_encoder=False
    )
    model.fit(X_train, y_train)

    y_prob = model.predict_proba(X_test)[:, 1]
    auc = float(roc_auc_score(y_test, y_prob))

    pos_probs = y_prob[y_test == 1]
    neg_probs = y_prob[y_test == 0]
    ks = float(ks_2samp(pos_probs, neg_probs).statistic)

    gini = 2 * auc - 1

    importances = dict(zip(
        feature_cols,
        [float(x) for x in model.feature_importances_]
    ))
    top_features = dict(sorted(importances.items(), key=lambda x: x[1], reverse=True)[:20])

    result = {
        "auc": round(auc, 6),
        "ks_stat": round(ks, 6),
        "gini": round(gini, 6),
        "n_features": len(feature_cols),
        "feature_importances": top_features,
        "iteration_id": iteration_id,
        "run_id": run_id
    }

    if register_model:
        from snowflake.ml.registry import Registry

        reg = Registry(
            session=session,
            database_name="AUTO_FEATURE_ENG",
            schema_name="CREDIT_RISK",
        )

        sample_input = pd.DataFrame(X_test.head(10))
        version_name = run_id.replace("-", "_").upper()

        mv = reg.log_model(
            model,
            model_name="CREDIT_RISK_XGBOOST",
            version_name=version_name,
            sample_input_data=sample_input,
            conda_dependencies=["xgboost", "scikit-learn", "numpy", "scipy"],
            target_platforms=["WAREHOUSE"],
            comment=f"Auto Feature Eng iter {iteration_id}, AUC={auc:.6f}, features={len(feature_cols)}",
        )

        result["model_version"] = mv.version_name
        result["model_name"] = "CREDIT_RISK_XGBOOST"

    return result
'''


def ensure_infrastructure(session: Session, config: dict):
    """
    Idempotently create all Snowflake objects needed for the loop.
    Safe to call on every run — uses IF NOT EXISTS / CREATE OR REPLACE.
    """
    logger = logging.getLogger("auto_fe")
    db = config["snowflake"]["database"]
    schema = config["snowflake"]["schema"]

    logger.info("[Setup] Ensuring infrastructure exists...")

    # Database and schemas
    session.sql(f"CREATE DATABASE IF NOT EXISTS {db}").collect()
    session.sql(f"CREATE SCHEMA IF NOT EXISTS {db}.{schema}").collect()
    session.sql(f"CREATE SCHEMA IF NOT EXISTS {db}.FEATURE_STORE").collect()

    # Source data table
    session.sql(f"""
        CREATE TABLE IF NOT EXISTS {db}.{schema}.RAW_CREDIT_DATA (
            ID INT,
            SERIOUSDLQIN2YRS INT,
            REVOLVING_UTILIZATION FLOAT,
            AGE INT,
            PAST_DUE_30_59 INT,
            DEBT_RATIO FLOAT,
            MONTHLY_INCOME FLOAT,
            OPEN_CREDIT_LINES INT,
            PAST_DUE_90 INT,
            REAL_ESTATE_LINES INT,
            PAST_DUE_60_89 INT,
            DEPENDENTS FLOAT
        )
    """).collect()

    # Feature log
    session.sql(f"""
        CREATE TABLE IF NOT EXISTS {db}.{schema}.FEATURE_LOG (
            ITERATION_ID INT,
            RUN_ID VARCHAR,
            TS TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
            FEATURE_TABLE VARCHAR,
            FEATURES_ADDED VARIANT,
            NUM_FEATURES INT,
            AUC FLOAT,
            KS_STAT FLOAT,
            GINI FLOAT,
            DELTA_AUC FLOAT,
            STATUS VARCHAR,
            STRATEGY VARCHAR,
            REASONING VARCHAR,
            ERROR_MSG VARCHAR
        )
    """).collect()

    # Cost log
    session.sql(f"""
        CREATE TABLE IF NOT EXISTS {db}.{schema}.COST_LOG (
            ITERATION_ID INT,
            RUN_ID VARCHAR,
            TS TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
            PHASE VARCHAR,
            SDK_COST_USD FLOAT,
            CREDITS_WAREHOUSE FLOAT,
            CREDITS_TOTAL FLOAT,
            SDK_TOKENS_IN INT,
            SDK_TOKENS_OUT INT,
            DURATION_SEC FLOAT
        )
    """).collect()

    # Stage for CSV upload
    session.sql(f"""
        CREATE STAGE IF NOT EXISTS {db}.{schema}.CREDIT_DATA_STAGE
        FILE_FORMAT = (TYPE = 'CSV' SKIP_HEADER = 1 FIELD_OPTIONALLY_ENCLOSED_BY = '"')
    """).collect()

    # Drop both known SP overloads before recreating — Snowflake procedures are
    # identified by their full signature, so an updated signature would otherwise
    # leave the old overload orphaned.
    session.sql(f"DROP PROCEDURE IF EXISTS {db}.{schema}.TRAIN_AND_EVALUATE(VARCHAR, INT, VARCHAR)").collect()
    session.sql(f"DROP PROCEDURE IF EXISTS {db}.{schema}.TRAIN_AND_EVALUATE(VARCHAR, INT, VARCHAR, BOOLEAN)").collect()

    sp_sql = f"""
CREATE OR REPLACE PROCEDURE {db}.{schema}.TRAIN_AND_EVALUATE(
    FEATURE_TABLE_NAME VARCHAR,
    ITERATION_ID INT,
    RUN_ID VARCHAR,
    REGISTER_MODEL BOOLEAN DEFAULT FALSE
)
RETURNS VARIANT
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python', 'snowflake-ml-python', 'xgboost', 'scikit-learn', 'numpy', 'scipy')
HANDLER = 'run'
AS $${_SP_BODY}$$"""
    session.sql(sp_sql).collect()

    logger.info("[Setup] Infrastructure ready.")

    # Load sample data if table is empty
    row_count = session.sql(f"SELECT COUNT(*) AS N FROM {db}.{schema}.RAW_CREDIT_DATA").collect()
    if row_count[0]["N"] == 0:
        data_file = Path(__file__).parent / "data" / "cs-training.csv"
        if data_file.exists():
            logger.info("[Setup] Loading sample data (cs-training.csv)...")
            stage = f"{db}.{schema}.CREDIT_DATA_STAGE"
            session.sql(f"REMOVE @{stage}").collect()
            session.file.put(
                str(data_file), f"@{stage}", auto_compress=False, overwrite=True
            )
            session.sql(f"""
                COPY INTO {db}.{schema}.RAW_CREDIT_DATA
                FROM @{stage}/cs-training.csv
                FILE_FORMAT = (
                    TYPE = 'CSV'
                    SKIP_HEADER = 1
                    FIELD_OPTIONALLY_ENCLOSED_BY = '"'
                )
                ON_ERROR = 'CONTINUE'
            """).collect()
            loaded = session.sql(f"SELECT COUNT(*) AS N FROM {db}.{schema}.RAW_CREDIT_DATA").collect()
            logger.info(f"[Setup] Loaded {loaded[0]['N']:,} rows into RAW_CREDIT_DATA.")
        else:
            logger.warning(f"[Setup] RAW_CREDIT_DATA is empty and data/cs-training.csv not found.")
            logger.warning(f"[Setup] Place the Kaggle 'Give Me Some Credit' CSV at: {data_file}")


# ---------------------------------------------------------------------------
# Feature ideation via Cortex Code Agent SDK
# ---------------------------------------------------------------------------

# JSON schema that constrains the agent's output — enforces structured feature proposals
# so downstream SQL generation is reliable without any parsing heuristics.
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
    logger = logging.getLogger("auto_fe")
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

    # Stream SDK messages; the agent runs SQL against Snowflake and reads files
    # before emitting a final ResultMessage with the structured feature spec.
    # bypassPermissions lets it execute tools without interactive prompts.
    async for msg in query(
        prompt=prompt,
        options=CortexCodeAgentOptions(
            cwd=str(project_dir),
            model=config["agent"]["model"],
            max_turns=config["agent"]["max_turns"],
            output_format={"type": "json_schema", "schema": FEATURE_SCHEMA},  # constrained generation
            permission_mode="bypassPermissions",
            allow_dangerously_skip_permissions=True,
        ),
    ):
        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if hasattr(block, "text") and block.text:
                    logger.debug(f"[Agent] {block.text[:200]}")
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
    logger = logging.getLogger("auto_fe")
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
    logger.debug(f"[SQL] CTAS:\n{ctas_sql}")
    try:
        session.sql(ctas_sql).collect()
        return output_table
    except Exception as e:
        raise RuntimeError(f"Feature CTAS failed: {e}\nSQL: {ctas_sql}")


# ---------------------------------------------------------------------------
# Deterministic: Train and evaluate
# ---------------------------------------------------------------------------

def train_and_evaluate(
    session: Session,
    feature_table: str,
    iteration: int,
    run_id: str,
    register_model: bool = False,
) -> dict:
    """Call the training stored procedure. Optionally registers model in registry."""
    logger = logging.getLogger("auto_fe")
    reg_flag = "TRUE" if register_model else "FALSE"
    logger.debug(f"[Train] Calling TRAIN_AND_EVALUATE on {feature_table} (register={register_model})...")
    session.sql(f"""
        CALL AUTO_FEATURE_ENG.CREDIT_RISK.TRAIN_AND_EVALUATE(
            '{feature_table}', {iteration}, '{run_id}', {reg_flag}
        )
    """).collect()

    # RESULT_SCAN(LAST_QUERY_ID()) reads the VARIANT return value of the CALL
    # statement as a queryable table row, avoiding a second round-trip.
    metrics_row = session.sql("""
        SELECT
            $1:auc::FLOAT as auc,
            $1:ks_stat::FLOAT as ks_stat,
            $1:gini::FLOAT as gini,
            $1:n_features::INT as n_features,
            $1:model_version::VARCHAR as model_version
        FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()))
    """).collect()

    if not metrics_row:
        raise RuntimeError("Training SP returned no results")

    row = metrics_row[0]
    result = {
        "auc": float(row["AUC"]),
        "ks_stat": float(row["KS_STAT"]),
        "gini": float(row["GINI"]),
        "n_features": int(row["N_FEATURES"]),
    }
    if row["MODEL_VERSION"] is not None:
        result["model_version"] = row["MODEL_VERSION"]
    return result


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
    strategy = (feature_spec.get("strategy", "") if feature_spec else "")[:200].replace("'", "")
    reasoning = (feature_spec.get("reasoning", "") if feature_spec else "")[:500].replace("'", "")
    error_msg_clean = error_msg[:500].replace("'", "")
    auc = metrics["auc"] if metrics else 0.0
    ks = metrics["ks_stat"] if metrics else 0.0
    gini = metrics["gini"] if metrics else 0.0
    n_feat = metrics["n_features"] if metrics else 0
    delta = auc - state["best_auc"] if metrics else 0.0

    # Dollar-quoting ($$...$$) safely embeds the JSON string without escaping
    # every double-quote, and PARSE_JSON converts it to a Snowflake VARIANT.
    session.sql(f"""
        INSERT INTO AUTO_FEATURE_ENG.CREDIT_RISK.FEATURE_LOG
        (ITERATION_ID, RUN_ID, FEATURE_TABLE, FEATURES_ADDED, NUM_FEATURES,
         AUC, KS_STAT, GINI, DELTA_AUC, STATUS, STRATEGY, REASONING, ERROR_MSG)
        SELECT
            {iteration}, '{run_id}', 'FEATURES_ITER_{iteration}',
            PARSE_JSON($${features_json}$$),
            {n_feat}, {auc}, {ks}, {gini}, {delta},
            '{status}', '{strategy}',
            '{reasoning}',
            '{error_msg_clean}'
    """).collect()


def log_cost(
    session: Session,
    iteration: int,
    run_id: str,
    sdk_cost: dict | None,
    duration: float,
    iter_start_utc: str = "",
    iter_end_utc: str = "",
):
    """Log cost to COST_LOG. Actual USD is backfilled by reconciliation."""
    usd = sdk_cost["usd"] if sdk_cost else 0.0
    tokens_in = sdk_cost.get("tokens_in", 0) if sdk_cost else 0
    tokens_out = sdk_cost.get("tokens_out", 0) if sdk_cost else 0

    session.sql(f"""
        INSERT INTO AUTO_FEATURE_ENG.CREDIT_RISK.COST_LOG
        (ITERATION_ID, RUN_ID, PHASE, SDK_COST_USD, CREDITS_WAREHOUSE,
         CREDITS_TOTAL, SDK_TOKENS_IN, SDK_TOKENS_OUT, DURATION_SEC,
         ITER_START_TS, ITER_END_TS, RECONCILED)
        VALUES (
            {iteration}, '{run_id}', 'total',
            {usd}, 0, {usd}, {tokens_in}, {tokens_out}, {duration},
            '{iter_start_utc}'::TIMESTAMP_NTZ, '{iter_end_utc}'::TIMESTAMP_NTZ, FALSE
        )
    """).collect()


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

async def run_loop(config: dict, resume: bool = False, verbosity: str = "normal", live: bool = True):
    """Main orchestration loop."""
    project_dir = Path(__file__).parent
    run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    if resume:
        state = load_state("__resume__")
        run_id = state["run_id"]
    else:
        state = load_state(run_id)
        state["run_id"] = run_id

    # Initialize logging
    logger = setup_logging(run_id, verbosity)

    if resume:
        logger.info(f"Resuming run: {run_id} at iteration {state['current_iter']}")
    else:
        logger.info(f"Starting new run: {run_id}")

    # Initialize monitor
    max_iter = config["loop"]["max_iterations"]
    monitor = LoopMonitor(run_id, max_iter, config["cost"]["max_cost_usd"], enabled=live) \
        if HAS_RICH and live else _NoOpMonitor()

    # One session for the full run; client_store_temporary_credential caches
    # the SSO token so browser auth is not triggered on each SDK iteration.
    session = create_session(config)
    try:
        # Ensure all Snowflake objects exist (idempotent)
        monitor.update(phase="infrastructure")
        ensure_infrastructure(session, config)

        session.sql(f"ALTER SESSION SET QUERY_TAG = '{run_id}'").collect()

        # Establish baseline if first run
        if state["baseline_auc"] == 0.0:
            logger.info("Establishing baseline...")
            monitor.update(phase="baseline")
            t_phase = time.time()
            baseline = train_and_evaluate(
                session, "AUTO_FEATURE_ENG.CREDIT_RISK.RAW_CREDIT_DATA", -1, run_id
            )
            state["baseline_auc"] = baseline["auc"]
            state["best_auc"] = baseline["auc"]
            logger.info(f"Baseline AUC: {baseline['auc']:.6f} ({time.time()-t_phase:.1f}s)")
            save_state(state)

        monitor.update(best_auc=state["best_auc"], best_iter=state.get("best_iter", -1))

        logger.info(
            f"LOOP START | baseline={state['baseline_auc']:.6f} "
            f"| max_iter={max_iter} | ceiling=${config['cost']['max_cost_usd']:.2f}"
        )

        monitor.start()

        for i in range(state["current_iter"], max_iter):
            t0 = time.time()
            iter_start_utc = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            sdk_cost = None
            monitor.update(current_iter=i + 1, phase="Ideation (SDK)", iter_start=time.time())

            logger.info(
                f"--- ITERATION {i+1}/{max_iter} | best={state['best_auc']:.6f} "
                f"| stale={state['stale_count']} ---"
            )

            # Phase 1: SDK inference
            t_phase = time.time()
            try:
                feature_spec, sdk_cost = await ideate_features(i, state, config, project_dir)
                n_feats = len(feature_spec.get("features", []))
                strategy = feature_spec.get("strategy", "?")
                logger.info(
                    f"[Phase 1] Ideation complete: {n_feats} features, "
                    f"strategy={strategy} ({time.time()-t_phase:.1f}s)"
                )
            except Exception as e:
                logger.error(f"[Phase 1] CRASH in ideation ({time.time()-t_phase:.1f}s): {e}")
                feature_spec = None

            # Phases 2-6: Use the shared session for SQL operations
            if feature_spec is None:
                log_iteration(session, i, run_id, None, None, "crash", state, "Ideation failed")
                monitor.add_history(i, "crash", 0.0, "failed")
            else:
                try:
                    # 2. DETERMINISTIC: Execute feature CTAS
                    t_phase = time.time()
                    monitor.update(phase="SQL execution")
                    feat_table = execute_features(session, feature_spec, i, config)
                    logger.info(f"[Phase 2] Feature table created ({time.time()-t_phase:.1f}s)")

                    # 3. DETERMINISTIC: Train and evaluate
                    t_phase = time.time()
                    monitor.update(phase="Training")
                    metrics = train_and_evaluate(session, feat_table, i, run_id)
                    delta = metrics["auc"] - state["best_auc"]
                    logger.info(
                        f"[Phase 3] AUC={metrics['auc']:.6f} (delta={delta:+.6f}) ({time.time()-t_phase:.1f}s)"
                    )

                    # 4. DETERMINISTIC: Decision
                    status = decide(metrics, state, config)
                    if status == "keep":
                        state["best_auc"] = metrics["auc"]
                        state["best_iter"] = i
                        state["stale_count"] = 0
                        strategy = feature_spec.get("strategy", "")
                        if strategy and strategy not in state["tried_categories"]:
                            state["tried_categories"].append(strategy)
                        logger.warning(f"KEEP — new best AUC: {metrics['auc']:.6f}")
                        monitor.update(best_auc=metrics["auc"], best_iter=i, stale_count=0)
                    else:
                        state["stale_count"] += 1
                        logger.warning(f"DISCARD — no improvement (stale: {state['stale_count']})")
                        monitor.update(stale_count=state["stale_count"])

                    monitor.add_history(i, status, metrics["auc"], feature_spec.get("strategy", "")[:12])

                    # 5. Log success
                    log_iteration(session, i, run_id, feature_spec, metrics, status, state)

                except Exception as e:
                    logger.error(f"CRASH in phases 2-4: {e}")
                    log_iteration(session, i, run_id, None, None, "crash", state, str(e)[:500])
                    monitor.add_history(i, "crash", 0.0, "error")

            # 6. Log cost (always, including on crash)
            duration = time.time() - t0
            iter_end_utc = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            log_cost(session, i, run_id, sdk_cost, duration, iter_start_utc, iter_end_utc)
            logger.info(f"[Cost] Iteration duration: {duration:.1f}s | SDK: ${sdk_cost['usd']:.4f}" if sdk_cost else f"[Cost] Iteration duration: {duration:.1f}s")

            # Track cumulative cost
            if sdk_cost:
                state["total_cost_usd"] = state.get("total_cost_usd", 0) + sdk_cost["usd"]
            monitor.update(cost_usd=state["total_cost_usd"])

            # 7. Check cost ceiling
            if state["total_cost_usd"] > config["cost"]["max_cost_usd"]:
                logger.warning(
                    f"COST CEILING REACHED (${state['total_cost_usd']:.2f} > "
                    f"${config['cost']['max_cost_usd']:.2f}). Stopping."
                )
                break

            # 8. Persist state
            state["current_iter"] = i + 1
            save_state(state)

        monitor.stop()

        # Summary
        logger.info(
            f"RUN COMPLETE: {run_id} | baseline={state['baseline_auc']:.6f} "
            f"| best={state['best_auc']:.6f} (iter {state['best_iter']}) "
            f"| improvement={state['best_auc'] - state['baseline_auc']:+.6f} "
            f"| cost=${state['total_cost_usd']:.4f}"
        )

        # Finalize: register best model and feature view
        if state["best_iter"] >= 0:
            finalize_run(session, state, config)

        # Attempt cost reconciliation (may be partial due to ACCOUNT_USAGE latency)
        from utils.cost_tracker import reconcile_run
        credit_rate = config["cost"]["credit_rate_usd"]
        logger.info("[Reconcile] Attempting cost reconciliation from ACCOUNT_USAGE...")
        reconcile_run(session, state["run_id"], credit_rate)
        logger.info("[Reconcile] Note: ACCOUNT_USAGE has 45min-3hr latency. Re-run reconciliation later for full data.")

    finally:
        monitor.stop()
        session.close()

    return state


# ---------------------------------------------------------------------------
# Finalization: Feature Store + Model Registry
# ---------------------------------------------------------------------------

def finalize_run(session: Session, state: dict, config: dict):
    """
    Post-loop finalization:
    1. Re-train on best iteration's table with REGISTER_MODEL=TRUE (registers in Model Registry)
    2. Register winning features in Snowflake Feature Store as an external Feature View
    """
    logger = logging.getLogger("auto_fe")
    db = config["snowflake"]["database"]
    schema = config["snowflake"]["schema"]
    run_id = state["run_id"]
    best_iter = state["best_iter"]
    best_table = f"{db}.{schema}.FEATURES_ITER_{best_iter}"

    logger.info(
        f"[Finalize] Starting: iter={best_iter}, AUC={state['best_auc']:.6f}, table={best_table}"
    )

    try:
        session.sql(f"ALTER SESSION SET QUERY_TAG = '{run_id}_finalize'").collect()

        # --- Step 1: Register model via SP with REGISTER_MODEL=TRUE ---
        t_phase = time.time()
        logger.info("[Registry] Training final model and registering in Model Registry...")
        final_metrics = train_and_evaluate(
            session, best_table, best_iter, run_id, register_model=True
        )
        model_version = final_metrics.get("model_version", "unknown")
        logger.info(
            f"[Registry] Model registered: CREDIT_RISK_XGBOOST v{model_version} "
            f"| AUC={final_metrics['auc']:.6f} ({time.time()-t_phase:.1f}s)"
        )

        # --- Step 2: Register winning features in Feature Store ---
        t_phase = time.time()
        logger.info("[Feature Store] Registering winning features...")

        # Ensure feature store schema exists
        session.sql(f"CREATE SCHEMA IF NOT EXISTS {db}.FEATURE_STORE").collect()

        fs = FeatureStore(
            session=session,
            database=db,
            name="FEATURE_STORE",
            default_warehouse=config["snowflake"]["warehouse"],
            creation_mode=CreationMode.CREATE_IF_NOT_EXIST,
        )

        # Register BORROWER entity (idempotent — check if exists first)
        try:
            borrower_entity = fs.get_entity("BORROWER")
        except Exception:
            borrower_entity = Entity(
                name="BORROWER",
                join_keys=["ID"],
                desc="Credit risk borrower, keyed by loan ID",
            )
            fs.register_entity(borrower_entity)

        # Build feature DataFrame from the best iteration's table (exclude target + key)
        feature_df = session.sql(f"""
            SELECT *
            EXCLUDE (SERIOUSDLQIN2YRS)
            FROM {best_table}
        """)

        # Create external Feature View (no refresh — static snapshot)
        fv_version = run_id.replace("-", "_").upper()
        fv = FeatureView(
            name="CREDIT_RISK_BEST_FV",
            entities=[borrower_entity],
            feature_df=feature_df,
            refresh_freq=None,
            desc=f"Best features from {run_id} iter {best_iter}, AUC={state['best_auc']:.6f}",
        )

        registered_fv = fs.register_feature_view(
            feature_view=fv,
            version=fv_version,
            block=True,
        )
        logger.info(
            f"[Feature Store] Registered: CREDIT_RISK_BEST_FV v{fv_version} ({time.time()-t_phase:.1f}s)"
        )

        # --- Summary ---
        logger.info(
            f"[Finalize] COMPLETE | Model: CREDIT_RISK_XGBOOST v{model_version} "
            f"| FV: CREDIT_RISK_BEST_FV v{fv_version}"
        )

    except Exception as e:
        logger.error(f"[Finalize] ERROR: {e}")
        logger.info("The loop results are still valid — finalization can be retried.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Auto Feature Engineering Loop")
    parser.add_argument("--max-iterations", type=int, default=None)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--config", type=str, default="config.yaml")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Show agent reasoning and SQL (DEBUG level)")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="Only show decisions and errors (WARNING level)")
    parser.add_argument("--no-live", action="store_true",
                        help="Disable rich status panel (for CI/pipes/nohup)")
    args = parser.parse_args()

    config = load_config(Path(__file__).parent / args.config)
    if args.max_iterations:
        config["loop"]["max_iterations"] = args.max_iterations

    # Determine verbosity
    if args.verbose:
        verbosity = "verbose"
    elif args.quiet:
        verbosity = "quiet"
    else:
        verbosity = "normal"

    asyncio.run(run_loop(config, resume=args.resume, verbosity=verbosity, live=not args.no_live))


if __name__ == "__main__":
    main()
