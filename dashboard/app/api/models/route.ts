import { querySnowflake } from "@/lib/snowflake"
import { DB, SCHEMA } from "@/lib/constants"

export const dynamic = "force-dynamic"

export async function GET() {
  try {
    const rows = await querySnowflake(`
      SELECT
        MODEL_NAME,
        MODEL_VERSION_NAME AS VERSION_NAME,
        COMMENT,
        CREATED_ON
      FROM ${DB}.INFORMATION_SCHEMA.MODEL_VERSIONS
      WHERE MODEL_NAME = 'CREDIT_RISK_XGBOOST'
      ORDER BY CREATED_ON DESC
      LIMIT 10
    `)
    return Response.json({ models: rows })
  } catch (e) {
    console.error(new Date().toISOString(), "[api/models]", e)
    return Response.json({ models: [] })
  }
}
