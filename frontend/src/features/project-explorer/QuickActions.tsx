import type { QuickAction } from '../../app/types'

type QuickActionsProps = {
  actions: QuickAction[]
}

export function QuickActions({ actions }: QuickActionsProps) {
  return (
    <div className="quick-actions" aria-label="Project shortcuts">
      {actions.map((action) => {
        const Icon = action.icon

        return (
          <button className="quick-action" type="button" key={action.label}>
            <Icon size={18} aria-hidden="true" />
            <span>{action.label}</span>
          </button>
        )
      })}
    </div>
  )
}
