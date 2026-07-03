"use client"

interface Props {
  iteration: Record<string, any> | null | undefined
  cost: Record<string, any> | null | undefined
  onClose: () => void
}

export function IterationDrawer({ iteration, cost, onClose }: Props) {
  if (!iteration) return null

  let features: any[] = []
  try {
    features = typeof iteration.FEATURES_ADDED === "string"
      ? JSON.parse(iteration.FEATURES_ADDED)
      : iteration.FEATURES_ADDED || []
  } catch { /* skip */ }

  return (
    <>
      <div className="fixed inset-0 bg-black/40 z-40" onClick={onClose} />
      <div className="detail-drawer open">
        <div className="flex items-center justify-between mb-6">
          <h3 className="text-lg font-semibold">Experiment #{iteration.ITERATION_ID}</h3>
          <button onClick={onClose} className="text-[var(--color-muted-foreground)] hover:text-white text-xl">
            &times;
          </button>
        </div>

        <div className="space-y-5 text-sm">
          <Section label="Status">
            <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${
              iteration.STATUS === "keep" ? "bg-emerald-900/40 text-emerald-300" :
              iteration.STATUS === "crash" ? "bg-red-900/40 text-red-300" :
              "bg-gray-800 text-gray-400"
            }`}>
              {iteration.STATUS === "keep" ? "Accepted" : iteration.STATUS === "crash" ? "Failed" : "Rejected"}
            </span>
          </Section>

          <Section label="Strategy / Hypothesis">
            <p className="text-[var(--color-muted-foreground)]">{iteration.STRATEGY || "N/A"}</p>
          </Section>

          <Section label="Reasoning">
            <p className="text-[var(--color-muted-foreground)] text-xs leading-relaxed">
              {iteration.REASONING || "N/A"}
            </p>
          </Section>

          <Section label="Metrics">
            <div className="grid grid-cols-3 gap-3">
              <Metric label="AUC" value={iteration.AUC?.toFixed(5)} />
              <Metric label="KS" value={iteration.KS_STAT?.toFixed(5)} />
              <Metric label="Gini" value={iteration.GINI?.toFixed(5)} />
              <Metric label="Delta AUC" value={iteration.DELTA_AUC?.toFixed(5)} highlight={iteration.DELTA_AUC > 0} />
              <Metric label="Features" value={iteration.NUM_FEATURES} />
            </div>
          </Section>

          <Section label="Generated Signals">
            {features.length === 0 ? (
              <p className="text-[var(--color-muted-foreground)]">None</p>
            ) : (
              <div className="space-y-2">
                {features.map((f: any, i: number) => (
                  <div key={i} className="bg-[var(--color-muted)] rounded p-2">
                    <div className="font-mono text-xs font-medium">{f.name}</div>
                    <div className="text-[10px] text-[var(--color-muted-foreground)] mt-0.5">{f.rationale}</div>
                    {f.sql_expression && (
                      <pre className="text-[10px] mt-1 bg-black/30 rounded px-2 py-1 overflow-x-auto">
                        {f.sql_expression}
                      </pre>
                    )}
                  </div>
                ))}
              </div>
            )}
          </Section>

          {cost && (
            <Section label="Cost">
              <div className="grid grid-cols-2 gap-3">
                <Metric label="SDK Cost" value={`$${(cost.SDK_COST_USD || 0).toFixed(4)}`} />
                <Metric label="Duration" value={`${(cost.DURATION_SEC || 0).toFixed(1)}s`} />
                <Metric label="Tokens In" value={(cost.SDK_TOKENS_IN || 0).toLocaleString()} />
                <Metric label="Tokens Out" value={(cost.SDK_TOKENS_OUT || 0).toLocaleString()} />
              </div>
            </Section>
          )}

          {iteration.ERROR_MSG && (
            <Section label="Error">
              <pre className="text-xs text-red-400 bg-red-900/20 rounded p-2 whitespace-pre-wrap">
                {iteration.ERROR_MSG}
              </pre>
            </Section>
          )}
        </div>
      </div>
    </>
  )
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-[var(--color-muted-foreground)] mb-1.5">{label}</div>
      {children}
    </div>
  )
}

function Metric({ label, value, highlight }: { label: string; value: any; highlight?: boolean }) {
  return (
    <div className="bg-[var(--color-muted)] rounded px-2 py-1.5">
      <div className="text-[10px] text-[var(--color-muted-foreground)]">{label}</div>
      <div className={`font-mono text-xs ${highlight ? "text-[var(--color-success)]" : ""}`}>{value ?? "N/A"}</div>
    </div>
  )
}
