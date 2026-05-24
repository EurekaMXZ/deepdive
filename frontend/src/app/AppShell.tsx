import { useState } from 'react'
import { Sidebar } from '../components/Sidebar'
import { ProjectExplorer } from '../features/project-explorer'
import {
  navigationItems,
  quickActions,
  repositorySuggestions,
  signOutAction,
  userMenuActions,
  userProfile,
} from './appData'

export function AppShell() {
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false)

  return (
    <div className={`app-shell${isSidebarCollapsed ? ' app-shell--sidebar-collapsed' : ''}`}>
      <Sidebar
        isCollapsed={isSidebarCollapsed}
        navigationItems={navigationItems}
        onToggleCollapse={() => setIsSidebarCollapsed((isCollapsed) => !isCollapsed)}
        signOutAction={signOutAction}
        userMenuActions={userMenuActions}
        userProfile={userProfile}
      />
      <ProjectExplorer quickActions={quickActions} repositorySuggestions={repositorySuggestions} />
    </div>
  )
}
