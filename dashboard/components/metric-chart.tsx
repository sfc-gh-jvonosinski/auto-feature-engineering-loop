"use client"

import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine, ResponsiveContainer } from "recharts"

interface Props {
  iterations: Record<string, any>[]
  baseline: Record<string, any> | null
  champion: Record<string, any> | null
}

export function MetricChart({ iterations, baseline, champion }: Props) {
  const experiments = iterations
    .filter((i) => i.ITERATION_ID >= 0 && i.AUC > 0)
    .map((i) => ({
      iter: i.ITERATION_ID,
      AUC: i.AUC,
      KS: i.KS_STAT,
      Gini: i.GINI,
      status: i.STATUS,
    }))

  const baselineAuc = baseline?.AUC || 0

  if (experiments.length === 0) {
    return (
      <div className="h-64 flex items-center justify-center bg-[var(--color-card)] rounded-lg border border-[var(--color-border)] text-sm text-[var(--color-muted-foreground)]">
        No experiment data yet
      </div>
    )
  }

  return (
    <div className="bg-[var(--color-card)] rounded-lg border border-[var(--color-border)] p-4">
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={experiments} margin={{ top: 10, right: 30, left: 10, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
          <XAxis
            dataKey="iter"
            tick={{ fontSize: 11, fill: "#94a3b8" }}
            label={{ value: "Experiment", position: "bottom", fontSize: 11, fill: "#64748b" }}
          />
          <YAxis
            domain={["dataMin - 0.005", "dataMax + 0.005"]}
            tick={{ fontSize: 11, fill: "#94a3b8" }}
            tickFormatter={(v: number) => v.toFixed(3)}
          />
          <Tooltip
            contentStyle={{ background: "#1e293b", border: "1px solid #334155", borderRadius: 8 }}
            labelStyle={{ color: "#94a3b8" }}
            formatter={(value: number, name: string) => [value.toFixed(5), name]}
            labelFormatter={(label) => `Experiment #${label}`}
          />
          {baselineAuc > 0 && (
            <ReferenceLine
              y={baselineAuc}
              stroke="#ef4444"
              strokeDasharray="5 5"
              label={{ value: "Baseline", position: "right", fontSize: 10, fill: "#ef4444" }}
            />
          )}
          {champion && (
            <ReferenceLine
              y={champion.AUC}
              stroke="#8b5cf6"
              strokeDasharray="3 3"
              label={{ value: "Champion", position: "right", fontSize: 10, fill: "#8b5cf6" }}
            />
          )}
          <Line type="monotone" dataKey="AUC" stroke="#3b82f6" strokeWidth={2} dot={{ r: 3 }} activeDot={{ r: 5 }} />
          <Line type="monotone" dataKey="KS" stroke="#10b981" strokeWidth={1.5} dot={false} strokeDasharray="4 2" />
          <Line type="monotone" dataKey="Gini" stroke="#f59e0b" strokeWidth={1.5} dot={false} strokeDasharray="2 2" />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
