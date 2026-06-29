"""
Cost Tracking Utilities
=======================
Provides post-run cost reconciliation using ACCOUNT_USAGE.METERING_HISTORY.
Real-time cost is tracked in main_loop.py via ResultMessage.total_cost_usd.
"""
from snowflake.snowpark import Session


def reconcile_costs(session: Session, run_id: str, run_start: str, run_end: str) -> dict:
    """
    Query ACCOUNT_USAGE.METERING_HISTORY for actual credit consumption.
    Note: This view has ~3 hour latency, so run this after the loop completes.
    
    Args:
        session: Snowpark session
        run_id: The run identifier  
        run_start: ISO timestamp of run start
        run_end: ISO timestamp of run end
    
    Returns:
        dict with warehouse_credits, ai_credits, total_credits
    """
    result = session.sql(f"""
        SELECT 
            SERVICE_TYPE,
            SUM(CREDITS_USED) as TOTAL_CREDITS
        FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY
        WHERE START_TIME >= '{run_start}'::TIMESTAMP_LTZ
          AND START_TIME <= '{run_end}'::TIMESTAMP_LTZ
          AND (SERVICE_TYPE = 'WAREHOUSE_METERING' OR SERVICE_TYPE = 'AI_SERVICES')
        GROUP BY SERVICE_TYPE
    """).collect()

    costs = {"warehouse_credits": 0.0, "ai_credits": 0.0, "total_credits": 0.0}
    for row in result:
        stype = row["SERVICE_TYPE"]
        credits = float(row["TOTAL_CREDITS"])
        if stype == "WAREHOUSE_METERING":
            costs["warehouse_credits"] = credits
        elif stype == "AI_SERVICES":
            costs["ai_credits"] = credits
    costs["total_credits"] = costs["warehouse_credits"] + costs["ai_credits"]
    return costs


def get_run_cost_summary(session: Session, run_id: str) -> dict:
    """Get cost summary from COST_LOG for a completed run."""
    result = session.sql(f"""
        SELECT
            COUNT(*) as iterations,
            SUM(SDK_COST_USD) as total_sdk_usd,
            SUM(CREDITS_WAREHOUSE) as total_warehouse_credits,
            SUM(SDK_TOKENS_IN) as total_tokens_in,
            SUM(SDK_TOKENS_OUT) as total_tokens_out,
            SUM(DURATION_SEC) as total_duration_sec,
            AVG(SDK_COST_USD) as avg_cost_per_iter,
            AVG(DURATION_SEC) as avg_duration_per_iter
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
        "total_tokens_in": int(row["TOTAL_TOKENS_IN"] or 0),
        "total_tokens_out": int(row["TOTAL_TOKENS_OUT"] or 0),
        "total_duration_sec": float(row["TOTAL_DURATION_SEC"] or 0),
        "avg_cost_per_iter": float(row["AVG_COST_PER_ITER"] or 0),
        "avg_duration_per_iter": float(row["AVG_DURATION_PER_ITER"] or 0),
    }
