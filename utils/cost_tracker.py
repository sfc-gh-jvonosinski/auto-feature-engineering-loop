"""
Cost Tracking Utilities
=======================
Provides post-run cost reconciliation using ACCOUNT_USAGE metadata views.

The Cortex Code Agent SDK does not report cost at runtime, so actual costs
are backfilled from:
  - CORTEX_CODE_DESKTOP_USAGE_HISTORY: AI/LLM token credits (by time window)
  - WAREHOUSE_METERING_HISTORY: Warehouse compute credits (by time window)

Note: ACCOUNT_USAGE views have 45 min – 3 hour latency. Run reconciliation
after that window for complete data.
"""
import logging
from snowflake.snowpark import Session

logger = logging.getLogger("auto_fe")


def reconcile_run(session: Session, run_id: str, credit_rate_usd: float = 3.0):
    """
    Backfill COST_LOG with actual credits from Snowflake ACCOUNT_USAGE.
    
    Queries:
      1. CORTEX_CODE_DESKTOP_USAGE_HISTORY — AI credits by time window per iteration
      2. QUERY_HISTORY — Warehouse credits by QUERY_TAG per iteration
    
    Updates COST_LOG.SDK_COST_USD, CREDITS_WAREHOUSE, CREDITS_TOTAL, RECONCILED.
    """
    # Get unreconciled iterations for this run that have timestamps
    rows = session.sql(f"""
        SELECT ITERATION_ID, ITER_START_TS, ITER_END_TS
        FROM AUTO_FEATURE_ENG.CREDIT_RISK.COST_LOG
        WHERE RUN_ID = '{run_id}'
          AND RECONCILED = FALSE
          AND ITER_START_TS IS NOT NULL
          AND ITER_END_TS IS NOT NULL
        ORDER BY ITERATION_ID
    """).collect()

    if not rows:
        logger.info(f"[Reconcile] No unreconciled iterations for {run_id}")
        return

    reconciled_count = 0
    for row in rows:
        iter_id = row["ITERATION_ID"]
        start_ts = row["ITER_START_TS"]
        end_ts = row["ITER_END_TS"]

        # 1. AI credits from CORTEX_CODE_DESKTOP_USAGE_HISTORY
        ai_result = session.sql(f"""
            SELECT COALESCE(SUM(TOKEN_CREDITS), 0) AS AI_CREDITS
            FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_DESKTOP_USAGE_HISTORY
            WHERE USAGE_TIME BETWEEN '{start_ts}'::TIMESTAMP_TZ AND '{end_ts}'::TIMESTAMP_TZ
        """).collect()
        ai_credits = float(ai_result[0]["AI_CREDITS"]) if ai_result else 0.0

        # 2. Warehouse credits from QUERY_HISTORY (by QUERY_TAG)
        wh_result = session.sql(f"""
            SELECT COALESCE(SUM(CREDITS_USED_CLOUD_SERVICES), 0) AS WH_CREDITS
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
            WHERE QUERY_TAG = '{run_id}'
              AND START_TIME BETWEEN '{start_ts}'::TIMESTAMP_TZ AND '{end_ts}'::TIMESTAMP_TZ
        """).collect()
        wh_credits = float(wh_result[0]["WH_CREDITS"]) if wh_result else 0.0

        total_credits = ai_credits + wh_credits
        total_usd = total_credits * credit_rate_usd

        # Only mark reconciled if we got non-zero data (otherwise latency hasn't caught up)
        if ai_credits > 0 or wh_credits > 0:
            session.sql(f"""
                UPDATE AUTO_FEATURE_ENG.CREDIT_RISK.COST_LOG
                SET SDK_COST_USD = {total_usd},
                    CREDITS_WAREHOUSE = {wh_credits},
                    CREDITS_TOTAL = {total_credits},
                    RECONCILED = TRUE
                WHERE RUN_ID = '{run_id}' AND ITERATION_ID = {iter_id}
            """).collect()
            reconciled_count += 1
            logger.info(
                f"[Reconcile] iter {iter_id}: AI={ai_credits:.6f} cr, "
                f"WH={wh_credits:.6f} cr, total=${total_usd:.4f}"
            )
        else:
            logger.debug(
                f"[Reconcile] iter {iter_id}: no usage data yet (ACCOUNT_USAGE latency)"
            )

    logger.info(
        f"[Reconcile] {run_id}: {reconciled_count}/{len(rows)} iterations reconciled"
    )


def get_run_cost_summary(session: Session, run_id: str) -> dict:
    """Get cost summary from COST_LOG for a completed run."""
    result = session.sql(f"""
        SELECT
            COUNT(*) as iterations,
            SUM(SDK_COST_USD) as total_sdk_usd,
            SUM(CREDITS_WAREHOUSE) as total_warehouse_credits,
            SUM(CREDITS_TOTAL) as total_credits,
            SUM(SDK_TOKENS_IN) as total_tokens_in,
            SUM(SDK_TOKENS_OUT) as total_tokens_out,
            SUM(DURATION_SEC) as total_duration_sec,
            AVG(SDK_COST_USD) as avg_cost_per_iter,
            AVG(DURATION_SEC) as avg_duration_per_iter,
            SUM(CASE WHEN RECONCILED THEN 1 ELSE 0 END) as reconciled_count
        FROM AUTO_FEATURE_ENG.CREDIT_RISK.COST_LOG
        WHERE RUN_ID = '{run_id}'
    """).collect()

    if not result:
        return {}

    row = result[0]
    return {
        "iterations": int(row["ITERATIONS"]),
        "total_sdk_usd": float(row["TOTAL_SDK_USD"] or 0),
        "total_warehouse_credits": float(row["TOTAL_WAREHOUSE_CREDITS"] or 0),
        "total_credits": float(row["TOTAL_CREDITS"] or 0),
        "total_tokens_in": int(row["TOTAL_TOKENS_IN"] or 0),
        "total_tokens_out": int(row["TOTAL_TOKENS_OUT"] or 0),
        "total_duration_sec": float(row["TOTAL_DURATION_SEC"] or 0),
        "avg_cost_per_iter": float(row["AVG_COST_PER_ITER"] or 0),
        "avg_duration_per_iter": float(row["AVG_DURATION_PER_ITER"] or 0),
        "reconciled_count": int(row["RECONCILED_COUNT"] or 0),
    }
