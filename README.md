# Auto Feature Engineering Loop

An autonomous agentic research loop that uses the **Cortex Code Agent SDK** to iteratively discover, test, and improve engineered features for a sub-prime credit risk ML model — running entirely on Snowflake.

## How It Works

```
┌─────────────────────────────────────────────────────────────────┐
│  main_loop.py (deterministic Python controller)                 │
│                                                                 │
│  for iteration in range(max_iterations):                        │
│    1. AGENT SDK → ideate features (structured JSON output)      │
│    2. EXECUTE  → CREATE TABLE with new features (SQL)           │
│    3. TRAIN    → Call stored procedure (XGBoost)                │
│    4. DECIDE   → threshold comparison (keep/discard)            │
│    5. LOG      → FEATURE_LOG + COST_LOG tables                  │
└─────────────────────────────────────────────────────────────────┘
```

The **Cortex Code Agent SDK** handles the creative/judgment step — it can autonomously run SQL to explore data statistics, read past iteration results, and reason about what features to try next. Everything else is deterministic Python/SQL.

## Key Design Principles

- **LLM only where judgment is needed**: The SDK agent is invoked once per iteration for feature ideation. Training, evaluation, and decisions are scripted.
- **Cost-aware**: Every iteration logs SDK cost (`ResultMessage.total_cost_usd`) and warehouse credits. A configurable cost ceiling auto-stops the loop.
- **Snowflake-native**: Model Registry for versioning, stored procedures for training, `INFORMATION_SCHEMA.QUERY_HISTORY` for cost attribution.
- **Repeatable**: Fixed random seeds, deterministic train/test splits, versioned feature tables per iteration.

## Results

Starting from a **baseline AUC of 0.862** on 10 raw features, the loop explores ratio features, bucketed variables, interaction terms, and domain composites to improve the model.

## Quickstart

### Prerequisites

- Python 3.10+
- [Cortex Code CLI](https://docs.snowflake.com/en/user-guide/cortex-code-agent-sdk/cortex-code-agent-sdk) installed
- Snowflake account with a connection configured in `~/.snowflake/connections.toml`

### Run (one command)

```bash
# 1. Install dependencies
pip install cortex-code-agent-sdk snowflake-snowpark-python snowflake-ml-python pyyaml matplotlib

# 2. Configure your Snowflake connection in config.yaml
#    (update connection_name, warehouse, role as needed)

# 3. Run — everything else is automatic
python main_loop.py --max-iterations 20
```

On first run, `main_loop.py` automatically:
1. Creates the database, schemas, tables, stage, and stored procedure (idempotent)
2. Loads the bundled sample data (`data/cs-training.csv`) into Snowflake
3. Establishes a baseline model
4. Runs the feature engineering loop
5. Registers the best model in **Snowflake Model Registry**
6. Registers winning features in **Snowflake Feature Store**

No manual SQL setup needed — just run the script.

### Configuration

All parameters are in `config.yaml`:

```yaml
snowflake:
  connection_name: "DEMO_ACCT"
  database: "AUTO_FEATURE_ENG"
  schema: "CREDIT_RISK"
  warehouse: "AICOLLEGE"
  role: "ACCOUNTADMIN"

agent:
  model: "auto"          # or "claude-sonnet-4-6", "claude-opus-4-6"
  max_turns: 10          # limit agent exploration per iteration

loop:
  max_iterations: 20
  improvement_threshold: 0.001
  pivot_threshold: 3     # stale iterations before forced category change

cost:
  max_cost_usd: 15.0     # total budget for the run
```

### View Results

```bash
# Text summary + chart
python rollup.py

# Or with Streamlit (interactive)
pip install streamlit
streamlit run rollup.py
```

## Project Structure

```
├── main_loop.py              # Orchestrator (Cortex Code Agent SDK + deterministic loop)
├── program.md                # Agent system prompt (domain context, SQL rules)
├── config.yaml               # All tunable parameters
├── rollup.py                 # Visual results summary
├── setup/
│   ├── create_schema.sql     # DDL reference (auto-applied by main_loop.py)
│   ├── create_procedures.sql # SP reference (auto-applied by main_loop.py)
│   └── create_feature_store.sql # Feature Store schema (auto-applied)
├── data/
│   └── cs-training.csv       # Give Me Some Credit dataset (bundled, auto-loaded)
├── utils/
│   └── cost_tracker.py       # Post-run cost reconciliation
├── pyproject.toml            # Python dependencies
└── state.json                # Loop state for resume (gitignored)
```

## How the Agent Works

Each iteration, `main_loop.py` calls the Cortex Code Agent SDK with:
- A prompt containing iteration context (stale count, best AUC, past categories tried)
- `output_format` set to a JSON schema requiring `{features, strategy, reasoning}`
- `max_turns=10` to limit exploration cost

The agent autonomously:
1. Runs SQL against `FEATURE_LOG` to see what was tried before
2. Runs SQL against `RAW_CREDIT_DATA` for relevant statistics
3. Reasons about what feature category to explore
4. Returns structured JSON with 2-4 new feature definitions

The orchestrator then deterministically:
1. Executes a `CREATE TABLE AS SELECT` with the new features
2. Calls the `TRAIN_AND_EVALUATE` stored procedure
3. Compares AUC to the current best (threshold = 0.001)
4. Logs results and costs
5. Keeps or discards the iteration

## Snowflake Capabilities Used

| Capability | Purpose |
|-----------|---------|
| Cortex Code Agent SDK | Feature ideation with autonomous SQL exploration |
| Structured Output | Validated JSON responses from the agent |
| Model Registry | Version and serve the best model |
| Feature Store | Managed feature views with lineage and versioning |
| Stored Procedures | Fixed XGBoost training harness |
| Query Tagging | Cost attribution per iteration |
| ACCOUNT_USAGE views | Post-run cost reconciliation |

## Dataset

**Give Me Some Credit** (Kaggle) — 150,000 borrowers with:
- Target: `SeriousDlqin2yrs` (serious delinquency within 2 years, ~6.7% positive rate)
- 10 features: revolving utilization, age, past-due counts, debt ratio, income, etc.

This is real sub-prime credit lending data — not synthetic.

## Adapting for Your Use Case

To use this framework for a different ML problem:

1. **Replace the data**: Load your own table into `RAW_CREDIT_DATA` (or rename)
2. **Update `program.md`**: Change column descriptions, domain context, and feature categories
3. **Update the SP**: Modify `TRAIN_AND_EVALUATE` for your model type and metrics
4. **Update `config.yaml`**: Point to your database/schema/warehouse

The orchestration pattern (SDK for ideation, deterministic execution, cost tracking) generalizes to any iterative ML improvement task.

## License

MIT
