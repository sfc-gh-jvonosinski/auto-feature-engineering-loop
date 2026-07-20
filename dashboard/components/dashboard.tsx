"use client"

import { useState, useMemo } from "react"
import { KpiStrip } from "./kpi-strip"
import { MetricChart } from "./metric-chart"
import { CostChart } from "./cost-chart"
import { IterationTimeline } from "./iteration-timeline"
import { FeatureLeaderboard } from "./feature-leaderboard"
import { IterationDrawer } from "./iteration-drawer"
import { GovernanceStrip } from "./governance-strip"

interface ResearchData {
  iterations: Record<string, any>[]
  costs: Record<string, any>[]
  runs: Record<string, any>[]
  models: Record<string, any>[]
}

export function Dashboard({ data }: { data: ResearchData }) {
  const [selectedRun, setSelectedRun] = useState<string>(
    data.runs[0]?.RUN_ID || ""
  )
  const [selectedIteration, setSelectedIteration] = useState<number | null>(null)

  const filteredIterations = useMemo(
    () => data.iterations.filter((i) => i.RUN_ID === selectedRun),
    [data.iterations, selectedRun]
  )

  const filteredCosts = useMemo(
    () => data.costs.filter((c) => c.RUN_ID === selectedRun),
    [data.costs, selectedRun]
  )

  const champion = useMemo(() => {
    const kept = filteredIterations.filter((i) => i.STATUS === "keep")
    if (kept.length === 0) return null
    return kept.reduce((best, cur) => (cur.AUC > best.AUC ? cur : best), kept[0])
  }, [filteredIterations])

  const baseline = useMemo(() => {
    const bl = filteredIterations.find((i) => i.ITERATION_ID === -1)
    return bl || null
  }, [filteredIterations])

  const totalCost = useMemo(
    () => filteredCosts.reduce((sum, c) => sum + (c.SDK_COST_USD || 0), 0),
    [filteredCosts]
  )

  const selectedIterData = useMemo(
    () =>
      selectedIteration !== null
        ? filteredIterations.find((i) => i.ITERATION_ID === selectedIteration)
        : null,
    [filteredIterations, selectedIteration]
  )

  const selectedIterCost = useMemo(
    () =>
      selectedIteration !== null
        ? filteredCosts.find((c) => c.ITERATION_ID === selectedIteration)
        : null,
    [filteredCosts, selectedIteration]
  )

  return (
    <div className="max-w-[1600px] mx-auto px-6 py-6">
      {/* Cost latency disclaimer */}
      <div className="mb-4 px-4 py-2 bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-800 rounded text-xs text-amber-800 dark:text-amber-200">
        Cost data is sourced from Snowflake ACCOUNT_USAGE metadata and may be delayed up to 3 hours after a run completes.
      </div>

      {/* Header */}
      <header className="mb-8">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">
              AI Credit Model Research Cockpit
            </h1>
            <p className="text-[var(--color-muted-foreground)] text-sm mt-1">
              Autonomous feature discovery and XGBoost training progress
            </p>
          </div>
          <div className="flex items-center gap-3">
            <label className="text-xs text-[var(--color-muted-foreground)]">Run:</label>
            <select
              value={selectedRun}
              onChange={(e) => {
                setSelectedRun(e.target.value)
                setSelectedIteration(null)
              }}
              className="bg-[var(--color-muted)] border border-[var(--color-border)] rounded px-3 py-1.5 text-sm"
            >
              {data.runs.map((r) => (
                <option key={r.RUN_ID} value={r.RUN_ID}>
                  {r.RUN_ID}
                </option>
              ))}
            </select>
          </div>
        </div>
      </header>

      {/* KPI Strip */}
      <KpiStrip
        iterations={filteredIterations}
        champion={champion}
        baseline={baseline}
        totalCost={totalCost}
        models={data.models}
      />

      {/* Iteration Timeline */}
      <section className="mt-8">
        <h2 className="text-sm font-semibold text-[var(--color-muted-foreground)] uppercase tracking-wider mb-3">
          Experiment Timeline
        </h2>
        <IterationTimeline
          iterations={filteredIterations}
          champion={champion}
          onSelect={setSelectedIteration}
          selected={selectedIteration}
        />
      </section>

      {/* Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mt-8">
        <section>
          <h2 className="text-sm font-semibold text-[var(--color-muted-foreground)] uppercase tracking-wider mb-3">
            Model Performance
          </h2>
          <MetricChart
            iterations={filteredIterations}
            baseline={baseline}
            champion={champion}
          />
        </section>
        <section>
          <h2 className="text-sm font-semibold text-[var(--color-muted-foreground)] uppercase tracking-wider mb-3">
            Cost Accumulation
          </h2>
          <CostChart costs={filteredCosts} iterations={filteredIterations} />
        </section>
      </div>

      {/* Feature Signal Leaderboard */}
      <section className="mt-8">
        <h2 className="text-sm font-semibold text-[var(--color-muted-foreground)] uppercase tracking-wider mb-3">
          Signal Leaderboard
        </h2>
        <FeatureLeaderboard iterations={filteredIterations} />
      </section>

      {/* Governance Strip */}
      <section className="mt-8">
        <GovernanceStrip champion={champion} models={data.models} />
      </section>

      {/* Iteration Detail Drawer */}
      <IterationDrawer
        iteration={selectedIterData}
        cost={selectedIterCost}
        onClose={() => setSelectedIteration(null)}
      />
    </div>
  )
}
