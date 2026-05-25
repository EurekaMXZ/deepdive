import { useEffect, useMemo, useState } from 'react'
import { Menu } from 'lucide-react'
import { Navigate, Route, Routes, useLocation } from 'react-router'
import { createDeepDiveApiClient } from '../api'
import { Sidebar } from '../components/Sidebar'
import { WorkspaceTopbar } from '../components/WorkspaceTopbar'
import {
  createAuthSession,
  createBrowserTokenStore,
  createMemoryTokenStore,
  type AuthSession,
  type AuthSessionState,
  type LoginInput,
  type TokenStore,
  type User,
} from '../domain'
import { LoginDialog } from '../features/auth'
import { AnalysisDetailPage } from '../features/analysis-preview'
import { AnalysisSubmissionsPage } from '../features/analysis-submissions'
import { AnalysisDocumentsPage } from '../features/documents'
import { ProjectExplorer } from '../features/project-explorer'
import {
  createNavigationItems,
  quickActions,
  repositorySuggestions,
  sectionForPathname,
  signOutAction,
  userMenuActions,
} from './appData'
import type { UserProfile } from './types'

export function AppShell() {
  const location = useLocation()
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false)
  const [isMobileSidebarOpen, setIsMobileSidebarOpen] = useState(false)
  const [authError, setAuthError] = useState<string | null>(null)
  const [isAuthRestoring, setIsAuthRestoring] = useState(true)
  const [isAuthSubmitting, setIsAuthSubmitting] = useState(false)
  const authSession = useMemo(() => createDefaultAuthSession(), [])
  const getAccessToken = useMemo(() => () => authSession.getAccessToken(), [authSession])
  const [authState, setAuthState] = useState<AuthSessionState>(() => authSession.getState())

  useEffect(() => {
    let active = true

    authSession
      .restore()
      .then((state) => {
        if (active) {
          setAuthState(state)
        }
      })
      .catch((error) => {
        if (active) {
          setAuthError(error instanceof Error ? error.message : String(error))
          setAuthState(authSession.getState())
        }
      })
      .finally(() => {
        if (active) {
          setIsAuthRestoring(false)
        }
      })

    return () => {
      active = false
    }
  }, [authSession])

  async function handleEmailLogin(input: LoginInput) {
    setAuthError(null)
    setIsAuthSubmitting(true)
    try {
      setAuthState(await authSession.login(input))
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : String(error))
    } finally {
      setIsAuthSubmitting(false)
    }
  }

  async function handleSignOut() {
    setAuthError(null)
    try {
      await authSession.logout()
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : String(error))
    } finally {
      setAuthState(authSession.getState())
    }
  }

  if (isAuthRestoring) {
    return (
      <div className="auth-restore" role="status" aria-live="polite">
        正在恢复登录
      </div>
    )
  }

  if (authState.status !== 'authenticated') {
    const turnstileEnabled = isTurnstileEnabled()

    return (
      <LoginDialog
        apiBaseUrl={import.meta.env.VITE_API_BASE_URL ?? '/api'}
        error={authError}
        githubAuthUrl={import.meta.env.VITE_GITHUB_AUTH_URL}
        isSubmitting={isAuthSubmitting}
        onEmailLogin={handleEmailLogin}
        onGitHubLogin={(url) => window.location.assign(url)}
        turnstileEnabled={turnstileEnabled}
        turnstileSiteKey={turnstileEnabled ? import.meta.env.VITE_TURNSTILE_SITE_KEY ?? null : null}
      />
    )
  }

  const authenticatedUserProfile = userProfileFromUser(authState.user)
  const activeSection = sectionForPathname(location.pathname)
  const activeNavigationItems = createNavigationItems(activeSection)
  const routeContext = {
    accessToken: getAccessToken,
    apiBaseUrl: import.meta.env.VITE_API_BASE_URL ?? '/api',
  }

  function handleMobileSidebarToggle() {
    setIsMobileSidebarOpen((isOpen) => !isOpen)
  }

  function handleMobileSidebarClose() {
    setIsMobileSidebarOpen(false)
  }

  function handleSidebarNavigate() {
    setIsMobileSidebarOpen(false)
  }

  return (
    <div className={`app-shell${isSidebarCollapsed ? ' app-shell--sidebar-collapsed' : ''}`}>
      <button
        className="mobile-sidebar-toggle"
        type="button"
        aria-label="展开侧边栏"
        aria-expanded={isMobileSidebarOpen}
        onClick={handleMobileSidebarToggle}
      >
        <Menu size={20} aria-hidden="true" />
      </button>
      <Sidebar
        isCollapsed={isSidebarCollapsed}
        isMobileOpen={isMobileSidebarOpen}
        navigationItems={activeNavigationItems}
        onCloseMobile={handleMobileSidebarClose}
        onNavigate={handleSidebarNavigate}
        onSignOut={handleSignOut}
        onToggleCollapse={() => setIsSidebarCollapsed((isCollapsed) => !isCollapsed)}
        signOutAction={signOutAction}
        userMenuActions={userMenuActions}
        userProfile={authenticatedUserProfile}
      />
      <Routes>
        <Route path="/" element={<Navigate to="/explore" replace />} />
        <Route
          path="/analysis"
          element={
            <AnalysisSubmissionsPage
              accessToken={routeContext.accessToken}
              apiBaseUrl={routeContext.apiBaseUrl}
            />
          }
        />
        <Route
          path="/analysis/:analysisId"
          element={
            <AnalysisDetailPage
              accessToken={routeContext.accessToken}
              apiBaseUrl={routeContext.apiBaseUrl}
            />
          }
        />
        <Route
          path="/analysis/:analysisId/documents"
          element={
            <AnalysisDocumentsPage
              accessToken={routeContext.accessToken}
              apiBaseUrl={routeContext.apiBaseUrl}
            />
          }
        />
        <Route
          path="/analysis/:analysisId/documents/:documentId"
          element={
            <AnalysisDocumentsPage
              accessToken={routeContext.accessToken}
              apiBaseUrl={routeContext.apiBaseUrl}
            />
          }
        />
        <Route
          path="/explore"
          element={
            <ProjectExplorer
              accessToken={routeContext.accessToken}
              apiBaseUrl={routeContext.apiBaseUrl}
              quickActions={quickActions}
              repositorySuggestions={repositorySuggestions}
            />
          }
        />
        <Route path="/subscription" element={<PlaceholderPage label="订阅" />} />
        <Route path="/mcp" element={<PlaceholderPage label="MCP" />} />
        <Route path="*" element={<Navigate to="/analysis" replace />} />
      </Routes>
    </div>
  )
}

function PlaceholderPage({ label }: { label: string }) {
  return (
    <main className="workspace workspace--placeholder" aria-label={label}>
      <WorkspaceTopbar title={label} />
      <section className="workspace-body">
        <div className="placeholder-panel" />
      </section>
    </main>
  )
}

function createDefaultAuthSession(): AuthSession {
  const tokenStore = createDefaultTokenStore()
  const client = createDeepDiveApiClient({
    accessToken: () => tokenStore.getAccessToken(),
    baseUrl: import.meta.env.VITE_API_BASE_URL ?? '/api',
  })

  return createAuthSession({
    client,
    tokenStore,
  })
}

function createDefaultTokenStore(): TokenStore {
  if (typeof window === 'undefined') {
    return createMemoryTokenStore()
  }

  return createBrowserTokenStore(window.localStorage)
}

function isTurnstileEnabled(): boolean {
  return import.meta.env.VITE_TURNSTILE_ENABLED === 'true'
}

function userProfileFromUser(user: User): UserProfile {
  const displayName = user.displayName?.trim() || user.email
  return {
    initials: initialsFor(displayName),
    name: displayName,
    plan: user.email,
    managementLabel: '管理 DeepDive 账户',
  }
}

function initialsFor(value: string): string {
  const parts = value
    .split(/[\s._@-]+/)
    .map((part) => part.trim())
    .filter(Boolean)

  return parts
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join('')
    .padEnd(1, 'D')
}
