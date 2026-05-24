import { PanelLeft } from 'lucide-react'
import type { NavigationItem, UserMenuAction, UserProfile } from '../app/types'
import { IconTooltip } from './IconTooltip'
import { SidebarNav } from './SidebarNav'
import { UserMenu } from './UserMenu'

type SidebarProps = {
  isCollapsed: boolean
  navigationItems: NavigationItem[]
  onToggleCollapse: () => void
  userMenuActions: UserMenuAction[]
  userProfile: UserProfile
  signOutAction: UserMenuAction
}

export function Sidebar({
  isCollapsed,
  navigationItems,
  onToggleCollapse,
  signOutAction,
  userMenuActions,
  userProfile,
}: SidebarProps) {
  return (
    <aside
      className={`sidebar${isCollapsed ? ' sidebar--collapsed' : ''}`}
      aria-label="DeepDive navigation"
    >
      <div className="sidebar__header">
        {isCollapsed ? null : (
          <a className="brand" href="/" aria-label="DeepDive home">
            DeepDive
          </a>
        )}
        <IconTooltip content={isCollapsed ? '展开侧边栏' : '隐藏侧边栏'}>
          <button
            className="icon-button sidebar-toggle"
            type="button"
            aria-label={isCollapsed ? '展开侧边栏' : '隐藏侧边栏'}
            aria-pressed={isCollapsed}
            onClick={onToggleCollapse}
          >
            <PanelLeft size={19} aria-hidden="true" />
          </button>
        </IconTooltip>
      </div>

      <SidebarNav items={navigationItems} />

      <UserMenu
        actions={userMenuActions}
        isCollapsed={isCollapsed}
        profile={userProfile}
        signOutAction={signOutAction}
      />
    </aside>
  )
}
