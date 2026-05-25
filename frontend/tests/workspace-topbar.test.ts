import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import test from 'node:test'

const workspaceTopbar = readFileSync(resolve('src/components/WorkspaceTopbar.tsx'), 'utf8')
const projectExplorer = readFileSync(
  resolve('src/features/project-explorer/ProjectExplorer.tsx'),
  'utf8',
)
const analysisSubmissionsPage = readFileSync(
  resolve('src/features/analysis-submissions/AnalysisSubmissionsPage.tsx'),
  'utf8',
)
const analysisDetailPage = readFileSync(
  resolve('src/features/analysis-preview/AnalysisDetailPage.tsx'),
  'utf8',
)
const analysisDocumentsPage = readFileSync(
  resolve('src/features/documents/AnalysisDocumentsPage.tsx'),
  'utf8',
)
const appShell = readFileSync(resolve('src/app/AppShell.tsx'), 'utf8')
const sidebar = readFileSync(resolve('src/components/Sidebar.tsx'), 'utf8')

test('workspace topbar exposes title and the shared action buttons', () => {
  assert.match(workspaceTopbar, /className="workspace-topbar"/)
  assert.match(workspaceTopbar, /className="workspace-topbar__inner"/)
  assert.match(workspaceTopbar, /className="workspace-topbar__actions"/)
  assert.match(workspaceTopbar, /SunMoon/)
  assert.match(workspaceTopbar, /Languages/)
  assert.match(workspaceTopbar, /Share2/)
  assert.match(workspaceTopbar, /aria-label="切换亮暗色"/)
  assert.match(workspaceTopbar, /aria-label="翻译"/)
  assert.match(workspaceTopbar, /aria-label="分享"/)
})

test('ordinary workspaces use the shared topbar and body regions', () => {
  assert.match(projectExplorer, /<WorkspaceTopbar title="探索项目" \/>/)
  assert.match(projectExplorer, /className="workspace-body workspace-body--centered"/)
  assert.match(projectExplorer, /className="search-stage__greeting"/)
  assert.match(projectExplorer, /getTimeAwareGreeting/)
  assert.match(analysisSubmissionsPage, /<WorkspaceTopbar title="提交分析" \/>/)
  assert.match(analysisSubmissionsPage, /className="workspace-body"/)
  assert.match(analysisDetailPage, /<WorkspaceTopbar title="分析对话" \/>/)
  assert.match(analysisDetailPage, /className="workspace-body workspace-body--full"/)
  assert.match(analysisDocumentsPage, /<WorkspaceTopbar title="文档预览" \/>/)
  assert.match(analysisDocumentsPage, /className="workspace-body workspace-body--full"/)
  assert.match(appShell, /<WorkspaceTopbar title=\{label\} \/>/)
  assert.match(appShell, /className="workspace-body"/)
})

test('project explorer starts with an empty search input', () => {
  assert.match(projectExplorer, /useState\(''\)/)
  assert.doesNotMatch(projectExplorer, /useState\('openai\/codex'\)/)
})

test('analysis submissions keep page title in the shared topbar only', () => {
  assert.doesNotMatch(analysisSubmissionsPage, /<h1 id="analysis-submissions-title">/)
  assert.match(analysisSubmissionsPage, /className="analysis-submissions__toolbar"/)
})

test('sidebar keeps the original toggle as the only drawer control', () => {
  assert.match(appShell, /onCloseMobile=\{handleMobileSidebarClose\}/)
  assert.doesNotMatch(sidebar, /,\s*X\s*}/)
  assert.doesNotMatch(sidebar, /mobile-sidebar-close/)
  assert.match(sidebar, /className="icon-button sidebar-toggle"/)
  assert.match(sidebar, /to="\/explore"/)
  assert.match(sidebar, /onClick=\{handleToggleClick\}/)
  assert.match(sidebar, /if \(isMobileOpen\)/)
  assert.match(sidebar, /onCloseMobile\?\.\(\)/)
  assert.match(sidebar, /onToggleCollapse\(\)/)
})
