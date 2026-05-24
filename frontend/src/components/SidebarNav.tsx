import type { NavigationItem } from '../app/types'
import { IconTooltip } from './IconTooltip'

type SidebarNavProps = {
  items: NavigationItem[]
}

export function SidebarNav({ items }: SidebarNavProps) {
  return (
    <nav className="sidebar__nav" aria-label="Primary">
      {items.map((item) => {
        const Icon = item.icon

        return (
          <IconTooltip key={item.label} content={item.description}>
            <button
              className={`nav-item${item.active ? ' nav-item--active' : ''}`}
              type="button"
              aria-current={item.active ? 'page' : undefined}
            >
              <Icon size={21} aria-hidden="true" />
              <span>{item.label}</span>
            </button>
          </IconTooltip>
        )
      })}
    </nav>
  )
}
