import { querySnowflake } from "@/lib/snowflake"
import { DB, SCHEMA } from "@/lib/constants"

export const dynamic = "force-dynamic"

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url)
  const runId = searchParams.get("run_id")

  try {
    const whereClause = runId ? `WHERE RUN_ID = '${runId}'` : ""

    const [iterations, costs, runs] = await Promise.all([
      querySnowflake(`
        SELECT
          ITERATION_ID,
          RUN_ID,
          TS,
          FEATURE_TABLE,
          FEATURES_ADDED,
          NUM_FEATURES,
          AUC,
          KS_STAT,
          GINI,
          DELTA_AUC,
          STATUS,
          STRATEGY,
          REASONING,
          ERROR_MSG
        FROM ${DB}.${SCHEMA}.FEATURE_LOG
        ${whereClause}
        ORDER BY RUN_ID, ITERATION_ID
      `),
      querySnowflake(`
        SELECT
          ITERATION_ID,
          RUN_ID,
          TS,
          PHASE,
          SDK_COST_USD,
          CREDITS_WAREHOUSE,
          CREDITS_TOTAL,
          SDK_TOKENS_IN,
          SDK_TOKENS_OUT,
          DURATION_SEC
        FROM ${DB}.${SCHEMA}.COST_LOG
        ${whereClause}
        ORDER BY RUN_ID, ITERATION_ID
      `),
      querySnowflake(`
        SELECT DISTINCT RUN_ID
        FROM ${DB}.${SCHEMA}.FEATURE_LOG
        ORDER BY RUN_ID DESC
      `),
    ])

    return Response.json({ iterations, costs, runs })
  } catch (e) {
    console.error(new Date().toISOString(), "[api/research]", e)
    return Response.json(
      { error: e instanceof Error ? e.message : "Failed to fetch research data" },
      { status: 500 }
    )
  }
}
