"use client"

interface Props {
  iterations: Record<string, any>[]
  champion: Record<string, any> | null
  baseline: Record<string, any> | null
  totalCost: number
  models: Record<string, any>[]
}

export function KpiStrip({ iterations, champion, baseline, totalCost, models }: Props) {
  const experimentIters = iterations.filter((i) => i.ITERATION_ID >= 0)
  const accepted = experimentIters.filter((i) => i.STATUS === "keep")
  const baselineAuc = baseline?.AUC || 0
  const championAuc = champion?.AUC || baselineAuc
  const improvement = championAuc - baselineAuc
  const costPerImprovement = improvement > 0 ? totalCost / improvement : 0
  const latestModel = models[0]

  const kpis = [
    {
      label: "Champion AUC",
      value: championAuc.toFixed(4),
      color: "var(--color-champion)",
    },
    {
      label: "Improvement",
      value: improvement > 0 ? `+${improvement.toFixed(4)}` : "0.0000",
      color: improvement > 0 ? "var(--color-success)" : "var(--color-muted-foreground)",
    },
    {
      label: "Champion KS",
      value: (champion?.KS_STAT || 0).toFixed(4),
      color: "var(--color-accent)",
    },
    {
      label: "Experiments",
      value: experimentIters.length.toString(),
      color: "var(--color-foreground)",
    },
    {
      label: "Signals Accepted",
      value: accepted.length.toString(),
      color: "var(--color-success)",
    },
    {
      label: "Total Cost",
      value: `$${totalCost.toFixed(2)}`,
      color: "var(--color-warning)",
    },
    {
      label: "Cost / +0.001 AUC",
      value: improvement > 0 ? `$${(costPerImprovement * 0.001).toFixed(2)}` : "N/A",
      color: "var(--color-muted-foreground)",
    },
    {
      label: "Champion Model",
      value: latestModel?.VERSION_NAME?.slice(0, 16) || "None",
      color: "var(--color-champion)",
      small: true,
    },
  ]

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-8 gap-3">
      {kpis.map((kpi) => (
        <div key={kpi.label} className="kpi-card">
          <div className="text-[10px] uppercase tracking-wider text-[var(--color-muted-foreground)] mb-1">
            {kpi.label}
          </div>
          <div
            className={`kpi-value ${kpi.small ? "!text-sm" : ""}`}
            style={{ color: kpi.color }}
          >
            {kpi.value}
          </div>
        </div>
      ))}
    </div>
  )
}
