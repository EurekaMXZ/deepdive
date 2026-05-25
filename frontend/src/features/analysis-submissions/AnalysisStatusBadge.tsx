import type { AnalysisPhase } from '../../domain'

type AnalysisStatusBadgeProps = {
  label: string
  phase: AnalysisPhase
}

export function AnalysisStatusBadge({ label, phase }: AnalysisStatusBadgeProps) {
  return (
    <span className="analysis-status-badge" data-phase={phase}>
      {label}
    </span>
  )
}
