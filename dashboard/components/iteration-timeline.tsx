"use client"

interface Props {
  iterations: Record<string, any>[]
  champion: Record<string, any> | null
  onSelect: (id: number) => void
  selected: number | null
}

export function IterationTimeline({ iterations, champion, onSelect, selected }: Props) {
  const experiments = iterations.filter((i) => i.ITERATION_ID >= 0)

  function dotClass(iter: Record<string, any>) {
    if (champion && iter.ITERATION_ID === champion.ITERATION_ID) return "dot-champion"
    if (iter.STATUS === "keep") return "dot-keep"
    if (iter.STATUS === "crash") return "dot-crash"
    return "dot-discard"
  }

  return (
    <div className="flex flex-wrap gap-2 p-4 bg-[var(--color-card)] rounded-lg border border-[var(--color-border)]">
      {experiments.length === 0 && (
        <p className="text-sm text-[var(--color-muted-foreground)]">No experiments yet</p>
      )}
      {experiments.map((iter) => (
        <div
          key={iter.ITERATION_ID}
          className={`iteration-dot ${dotClass(iter)} ${selected === iter.ITERATION_ID ? "ring-2 ring-white" : ""}`}
          onClick={() => onSelect(iter.ITERATION_ID)}
          title={`#${iter.ITERATION_ID} | ${iter.STATUS} | AUC: ${iter.AUC?.toFixed(4) || "?"} | Δ: ${iter.DELTA_AUC?.toFixed(4) || "0"}`}
        >
          {iter.ITERATION_ID}
        </div>
      ))}
      <div className="flex items-center gap-4 ml-auto text-[10px] text-[var(--color-muted-foreground)]">
        <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-full bg-[var(--color-champion)]"></span>Champion</span>
        <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-full bg-[var(--color-success)]"></span>Accepted</span>
        <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-full bg-[#374151]"></span>Rejected</span>
        <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-full bg-[var(--color-destructive)]"></span>Failed</span>
      </div>
    </div>
  )
}
