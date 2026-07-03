"use client"

import { BarChart, Bar, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ComposedChart } from "recharts"

interface Props {
  costs: Record<string, any>[]
  iterations: Record<string, any>[]
}

export function CostChart({ costs, iterations }: Props) {
  let cumulative = 0
  const data = costs
    .filter((c) => c.ITERATION_ID >= 0)
    .map((c) => {
      cumulative += c.SDK_COST_USD || 0
      const iter = iterations.find((i) => i.ITERATION_ID === c.ITERATION_ID)
      return {
        iter: c.ITERATION_ID,
        cost: c.SDK_COST_USD || 0,
        cumulative: cumulative,
        duration: c.DURATION_SEC || 0,
        status: iter?.STATUS || "unknown",
      }
    })

  if (data.length === 0) {
    return (
      <div className="h-64 flex items-center justify-center bg-[var(--color-card)] rounded-lg border border-[var(--color-border)] text-sm text-[var(--color-muted-foreground)]">
        No cost data yet
      </div>
    )
  }

  return (
    <div className="bg-[var(--color-card)] rounded-lg border border-[var(--color-border)] p-4">
      <ResponsiveContainer width="100%" height={280}>
        <ComposedChart data={data} margin={{ top: 10, right: 30, left: 10, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
          <XAxis
            dataKey="iter"
            tick={{ fontSize: 11, fill: "#94a3b8" }}
            label={{ value: "Experiment", position: "bottom", fontSize: 11, fill: "#64748b" }}
          />
          <YAxis
            yAxisId="left"
            tick={{ fontSize: 11, fill: "#94a3b8" }}
            tickFormatter={(v: number) => `$${v.toFixed(2)}`}
          />
          <YAxis
            yAxisId="right"
            orientation="right"
            tick={{ fontSize: 11, fill: "#94a3b8" }}
            tickFormatter={(v: number) => `$${v.toFixed(2)}`}
          />
          <Tooltip
            contentStyle={{ background: "#1e293b", border: "1px solid #334155", borderRadius: 8 }}
            labelStyle={{ color: "#94a3b8" }}
            formatter={(value: number, name: string) => [`$${value.toFixed(4)}`, name]}
            labelFormatter={(label) => `Experiment #${label}`}
          />
          <Bar yAxisId="left" dataKey="cost" fill="#3b82f6" opacity={0.7} name="Cost" />
          <Line yAxisId="right" type="monotone" dataKey="cumulative" stroke="#f59e0b" strokeWidth={2} dot={false} name="Cumulative" />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}
