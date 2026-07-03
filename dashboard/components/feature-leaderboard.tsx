"use client"

import { useMemo } from "react"

interface Props {
  iterations: Record<string, any>[]
}

interface FeatureEntry {
  name: string
  rationale: string
  strategy: string
  iteration: number
  delta_auc: number
  status: string
}

export function FeatureLeaderboard({ iterations }: Props) {
  const features = useMemo(() => {
    const entries: FeatureEntry[] = []
    for (const iter of iterations) {
      if (iter.ITERATION_ID < 0) continue
      let feats: any[] = []
      try {
        feats = typeof iter.FEATURES_ADDED === "string"
          ? JSON.parse(iter.FEATURES_ADDED)
          : iter.FEATURES_ADDED || []
      } catch { /* skip parse errors */ }
      for (const f of feats) {
        entries.push({
          name: f.name || "Unknown",
          rationale: f.rationale || "",
          strategy: iter.STRATEGY || "",
          iteration: iter.ITERATION_ID,
          delta_auc: iter.DELTA_AUC || 0,
          status: iter.STATUS,
        })
      }
    }
    return entries.sort((a, b) => b.delta_auc - a.delta_auc)
  }, [iterations])

  if (features.length === 0) {
    return (
      <div className="p-6 bg-[var(--color-card)] rounded-lg border border-[var(--color-border)] text-sm text-[var(--color-muted-foreground)]">
        No signals discovered yet
      </div>
    )
  }

  return (
    <div className="bg-[var(--color-card)] rounded-lg border border-[var(--color-border)] overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[var(--color-border)] text-[10px] uppercase tracking-wider text-[var(--color-muted-foreground)]">
              <th className="px-4 py-3 text-left">#</th>
              <th className="px-4 py-3 text-left">Signal Name</th>
              <th className="px-4 py-3 text-left">Family</th>
              <th className="px-4 py-3 text-left">Rationale</th>
              <th className="px-4 py-3 text-right">Experiment</th>
              <th className="px-4 py-3 text-right">AUC Delta</th>
              <th className="px-4 py-3 text-center">Decision</th>
            </tr>
          </thead>
          <tbody>
            {features.slice(0, 30).map((f, idx) => (
              <tr key={`${f.iteration}-${f.name}`} className="border-b border-[var(--color-border)] hover:bg-[var(--color-muted)]">
                <td className="px-4 py-2 text-[var(--color-muted-foreground)]">{idx + 1}</td>
                <td className="px-4 py-2 font-mono text-xs">{f.name}</td>
                <td className="px-4 py-2 text-[var(--color-muted-foreground)]">{f.strategy}</td>
                <td className="px-4 py-2 text-xs text-[var(--color-muted-foreground)] max-w-[200px] truncate">{f.rationale}</td>
                <td className="px-4 py-2 text-right">#{f.iteration}</td>
                <td className="px-4 py-2 text-right font-mono">
                  <span style={{ color: f.delta_auc > 0 ? "var(--color-success)" : "var(--color-muted-foreground)" }}>
                    {f.delta_auc > 0 ? "+" : ""}{f.delta_auc.toFixed(4)}
                  </span>
                </td>
                <td className="px-4 py-2 text-center">
                  <span className={`inline-block px-2 py-0.5 rounded text-[10px] font-medium ${
                    f.status === "keep" ? "bg-emerald-900/40 text-emerald-300" :
                    f.status === "crash" ? "bg-red-900/40 text-red-300" :
                    "bg-gray-800 text-gray-400"
                  }`}>
                    {f.status === "keep" ? "Accepted" : f.status === "crash" ? "Failed" : "Rejected"}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
