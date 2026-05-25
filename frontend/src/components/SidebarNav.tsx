import { NavLink } from 'react-router'

import type { NavigationItem } from '../app/types'
import { IconTooltip } from './IconTooltip'

type SidebarNavProps = {
  items: NavigationItem[]
  onNavigate?: () => void
}

export function SidebarNav({ items, onNavigate }: SidebarNavProps) {
  return (
    <nav className="sidebar__nav" aria-label="Primary">
      {items.map((item) => {
        const Icon = item.icon

        return (
          <IconTooltip key={item.label} content={item.description}>
            <NavLink
              className={`nav-item${item.active ? ' nav-item--active' : ''}`}
              to={item.href}
              aria-current={item.active ? 'page' : undefined}
              onClick={onNavigate}
            >
              <Icon size={21} aria-hidden="true" />
              <span>{item.label}</span>
            </NavLink>
          </IconTooltip>
        )
      })}
    </nav>
  )
}
