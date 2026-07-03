import { querySnowflake } from "@/lib/snowflake"
import { DB, SCHEMA } from "@/lib/constants"
import { Dashboard } from "@/components/dashboard"

export const dynamic = "force-dynamic"

async function getResearchData() {
  const [iterations, costs, runs] = await Promise.all([
    querySnowflake(`
      SELECT ITERATION_ID, RUN_ID, TS, FEATURE_TABLE, FEATURES_ADDED,
             NUM_FEATURES, AUC, KS_STAT, GINI, DELTA_AUC, STATUS,
             STRATEGY, REASONING, ERROR_MSG
      FROM ${DB}.${SCHEMA}.FEATURE_LOG
      ORDER BY RUN_ID DESC, ITERATION_ID
    `),
    querySnowflake(`
      SELECT ITERATION_ID, RUN_ID, TS, PHASE, SDK_COST_USD,
             CREDITS_WAREHOUSE, CREDITS_TOTAL, SDK_TOKENS_IN,
             SDK_TOKENS_OUT, DURATION_SEC
      FROM ${DB}.${SCHEMA}.COST_LOG
      ORDER BY RUN_ID DESC, ITERATION_ID
    `),
    querySnowflake(`
      SELECT DISTINCT RUN_ID FROM ${DB}.${SCHEMA}.FEATURE_LOG ORDER BY RUN_ID DESC
    `),
  ])

  let models: Record<string, any>[] = []
  try {
    models = await querySnowflake(`
      SELECT MODEL_NAME, MODEL_VERSION_NAME AS VERSION_NAME, COMMENT, CREATED_ON
      FROM ${DB}.INFORMATION_SCHEMA.MODEL_VERSIONS
      WHERE MODEL_NAME = 'CREDIT_RISK_XGBOOST'
      ORDER BY CREATED_ON DESC LIMIT 10
    `)
  } catch {
    // Model registry may not have entries yet
  }

  return { iterations, costs, runs, models }
}

export default async function Page() {
  const data = await getResearchData()
  return <Dashboard data={data} />
}
