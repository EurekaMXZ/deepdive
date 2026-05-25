import { Link } from 'react-router'
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
          <Link className="quick-action" to={action.href} key={action.label}>
            <Icon size={18} aria-hidden="true" />
            <span>{action.label}</span>
          </Link>
        )
      })}
    </div>
  )
}
