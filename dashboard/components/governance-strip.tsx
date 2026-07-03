"use client"

import { CheckCircle2, AlertCircle, Clock, XCircle } from "lucide-react"

interface Props {
  champion: Record<string, any> | null
  models: Record<string, any>[]
}

export function GovernanceStrip({ champion, models }: Props) {
  const hasModel = models.length > 0
  const hasChampion = champion !== null

  const checks = [
    {
      label: "Model Registered",
      status: hasModel ? "pass" : "pending",
      detail: hasModel ? models[0]?.VERSION_NAME : "No model in registry",
    },
    {
      label: "Validation Complete",
      status: hasChampion ? "pass" : "pending",
      detail: hasChampion ? `AUC ${champion.AUC?.toFixed(4)}` : "Awaiting champion",
    },
    {
      label: "Leakage Check",
      status: "pending",
      detail: "Manual review required",
    },
    {
      label: "Fairness Review",
      status: "pending",
      detail: "Not yet assessed",
    },
    {
      label: "Stability / Drift",
      status: "pending",
      detail: "Not yet monitored",
    },
    {
      label: "Human Approval",
      status: "blocked",
      detail: "Required before production",
    },
  ]

  function StatusIcon({ status }: { status: string }) {
    switch (status) {
      case "pass":
        return <CheckCircle2 size={14} className="text-[var(--color-success)]" />
      case "fail":
        return <XCircle size={14} className="text-[var(--color-destructive)]" />
      case "blocked":
        return <AlertCircle size={14} className="text-[var(--color-warning)]" />
      default:
        return <Clock size={14} className="text-[var(--color-muted-foreground)]" />
    }
  }

  return (
    <div className="bg-[var(--color-card)] rounded-lg border border-[var(--color-border)] p-4">
      <h3 className="text-[10px] uppercase tracking-wider text-[var(--color-muted-foreground)] mb-3">
        Governance & Compliance
      </h3>
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        {checks.map((check) => (
          <div key={check.label} className="flex items-start gap-2">
            <StatusIcon status={check.status} />
            <div>
              <div className="text-xs font-medium">{check.label}</div>
              <div className="text-[10px] text-[var(--color-muted-foreground)]">{check.detail}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
