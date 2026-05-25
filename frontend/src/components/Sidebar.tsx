import { PanelLeft } from 'lucide-react'
import { Link } from 'react-router'
import type { NavigationItem, UserMenuAction, UserProfile } from '../app/types'
import { IconTooltip } from './IconTooltip'
import { SidebarNav } from './SidebarNav'
import { UserMenu } from './UserMenu'

type SidebarProps = {
  isCollapsed: boolean
  isMobileOpen?: boolean
  navigationItems: NavigationItem[]
  onCloseMobile?: () => void
  onNavigate?: () => void
  onSignOut?: () => void
  onToggleCollapse: () => void
  userMenuActions: UserMenuAction[]
  userProfile: UserProfile
  signOutAction: UserMenuAction
}

export function Sidebar({
  isCollapsed,
  isMobileOpen = false,
  navigationItems,
  onCloseMobile,
  onNavigate,
  onSignOut,
  onToggleCollapse,
  signOutAction,
  userMenuActions,
  userProfile,
}: SidebarProps) {
  function handleToggleClick() {
    if (isMobileOpen) {
      onCloseMobile?.()
      return
    }

    onToggleCollapse()
  }

  return (
    <aside
      className={`sidebar${isCollapsed ? ' sidebar--collapsed' : ''}${
        isMobileOpen ? ' sidebar--mobile-open' : ''
      }`}
      aria-label="DeepDive navigation"
    >
      <div className="sidebar__header">
        {isCollapsed ? null : (
          <Link className="brand" to="/explore" aria-label="DeepDive home" onClick={onNavigate}>
            DeepDive
          </Link>
        )}
        <IconTooltip content={isCollapsed ? '展开侧边栏' : '隐藏侧边栏'}>
          <button
            className="icon-button sidebar-toggle"
            type="button"
            aria-label={isCollapsed ? '展开侧边栏' : '隐藏侧边栏'}
            aria-pressed={isCollapsed}
            onClick={handleToggleClick}
          >
            <PanelLeft size={19} aria-hidden="true" />
          </button>
        </IconTooltip>
      </div>

      <SidebarNav items={navigationItems} onNavigate={onNavigate} />

      <UserMenu
        actions={userMenuActions}
        isCollapsed={isCollapsed}
        onSignOut={onSignOut}
        profile={userProfile}
        signOutAction={signOutAction}
      />
    </aside>
  )
}
