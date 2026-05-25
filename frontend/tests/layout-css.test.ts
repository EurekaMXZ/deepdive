import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import test from 'node:test'

const appCss = readFileSync(resolve('src/App.css'), 'utf8')

test('analysis detail layout uses a single stream column without a right activity timeline', () => {
  assertCssRule('.app-shell', ['height: 100svh', 'min-height: 0', 'overflow: hidden'])
  assertCssRule('.sidebar', ['height: 100svh', 'min-height: 0', 'overflow: hidden'])
  assertCssRule('.workspace', ['height: 100svh', 'min-height: 0', 'overflow: hidden'])
  assertCssRule('.workspace--analysis-detail', ['align-content: stretch'])
  assertCssRule('.workspace-body--full', ['width: 100%', 'height: 100%', 'padding: 0'])
  assertCssRule('.workspace--analysis-detail .workspace-topbar__inner,\n.workspace--documents .workspace-topbar__inner', [
    'width: 100%',
  ])
  assertCssRule('.analysis-preview', ['height: 100%', 'min-height: 0', 'overflow: hidden'])
  assertCssRule('.analysis-preview__conversation', ['min-height: 0', 'overflow: hidden'])
  assertCssRule('.analysis-preview__thread', ['min-height: 0', 'overflow: auto'])
  assert.doesNotMatch(appCss, /\.analysis-activity\b/)
  assertCssRule('.analysis-event-stream', ['min-height: 0', 'display: grid'])
  assertCssRule('.analysis-stream-item', ['min-width: 0'])
})

test('analysis todo dock floats beside the stream and collapses on mobile', () => {
  assertCssRule('.analysis-preview', ['position: relative'])
  assertCssRule('.analysis-todo-dock', [
    'position: absolute',
    'top: 50%',
    'right: 16px',
    'transform: translateY(-50%)',
  ])
  assertCssRule('.analysis-todo-dock__trigger', ['display: none'])
  assertCssRule('.analysis-todo-dock__item[data-status=\'completed\'] .analysis-todo-dock__title', [
    'text-decoration: line-through',
  ])
  assertCssRuleInMedia('@media (max-width: 900px)', '.analysis-todo-dock', [
    'right: 14px',
    'bottom: 14px',
    'transform: none',
  ])
  assertCssRuleInMedia('@media (max-width: 900px)', '.analysis-todo-dock__trigger', [
    'display: inline-flex',
  ])
  assertCssRuleInMedia('@media (max-width: 900px)', '.analysis-todo-dock__panel', [
    'display: none',
  ])
  assertCssRuleInMedia('@media (max-width: 900px)', '.analysis-todo-dock[data-open=\'true\'] .analysis-todo-dock__panel', [
    'display: grid',
  ])
})

test('analysis cancellation controls use compact table and header affordances', () => {
  assertCssRule('.analysis-submissions__toolbar', ['justify-content: space-between'])
  assertCssRule('.analysis-submissions__selection', ['display: inline-flex'])
  assertCssRule('.analysis-bulk-cancel-button', ['min-height: 34px'])
  assertCssRule('.analysis-list__head,\n.analysis-list__row', [
    'grid-template-columns: 34px minmax(220px, 1.65fr) minmax(82px, 0.42fr) minmax(108px, 0.52fr) minmax(138px, 0.68fr) 72px 86px',
  ])
  assertCssRule('.analysis-list__select', ['display: inline-flex'])
  assertCssRule('.analysis-list__checkbox', ['width: 18px', 'height: 18px'])
  assertCssRule('.analysis-list__row[data-selected=\'true\']', ['background: #141414'])
  assertCssRule('.analysis-list__cancel', ['min-height: 32px'])
  assertCssRule('.analysis-preview__actions', ['display: inline-flex'])
  assertCssRule('.analysis-preview__cancel', ['min-height: 32px'])
})

test('sidebar navigation links do not render browser default underlines', () => {
  assertCssRule('.nav-item', ['text-decoration: none'])
  assertCssRule('.nav-item:hover,\n.nav-item:focus-visible,\n.nav-item--active', [
    'text-decoration: none',
  ])
})

test('document preview layout gives markdown panes their own scroll containers', () => {
  assertCssRule('.workspace--documents', [
    'justify-items: stretch',
    'min-height: 0',
    'overflow: hidden',
    'padding: 0',
  ])
  assertCssRule('.workspace-body--full', ['width: 100%', 'height: 100%', 'padding: 0'])
  assertCssRule('.workspace--documents .markdown-viewer', [
    'width: 100%',
    'height: 100%',
    'min-height: 0',
    'max-height: none',
    'align-self: stretch',
    'justify-self: stretch',
    'border-radius: 0',
  ])
  assertCssRule('.markdown-viewer__sidebar,\n.markdown-viewer__outline', [
    'min-height: 0',
    'overflow: auto',
  ])
  assertCssRule('.markdown-viewer__main', ['min-height: 0'])
  assertCssRule('.markdown-preview', ['min-height: 0', 'overflow: auto'])
})

test('streamdown code blocks preserve multiline formatting in analysis and document markdown', () => {
  assertCssRule('.analysis-stream-markdown [data-streamdown=\'code-block-body\'] code', [
    'display: block',
    'white-space: pre',
  ])
  assertCssRule('.analysis-stream-markdown [data-streamdown=\'code-block-body\'] code > span', [
    'display: block',
  ])
  assertCssRule('.analysis-stream-markdown [data-streamdown=\'code-block-body\'] pre', [
    'white-space: pre',
  ])
  assertCssRule('.markdown-preview__content [data-streamdown=\'code-block-body\'] code', [
    'display: block',
    'white-space: pre',
  ])
  assertCssRule('.markdown-preview__content [data-streamdown=\'code-block-body\'] code > span', [
    'display: block',
  ])
  assertCssRule('.markdown-preview__content [data-streamdown=\'code-block-body\'] pre', [
    'white-space: pre',
  ])
})

test('explore workspace centers the search stage independently from document and analysis layouts', () => {
  assertCssRule('.workspace--explore', ['justify-items: center', 'align-content: stretch'])
  assertCssRule('.workspace--explore .workspace-body', ['overflow: visible'])
  assertCssRule('.workspace--explore .search-stage', ['margin-top: -7vh'])
  assertCssRuleInMedia('@media (max-width: 900px)', '.workspace--explore .workspace-body--centered', [
    'place-items: center',
    'overflow: visible',
  ])
  assertCssRuleInMedia('@media (max-width: 900px)', '.workspace--explore .search-stage', [
    'margin-top: 0',
  ])
  assertCssRuleInMedia('@media (max-width: 560px)', '.workspace--explore', [
    'place-items: stretch center',
  ])
})

test('mobile layout hides the sidebar behind a menu button while keeping workspace topbar visible', () => {
  assertCssRule('.mobile-sidebar-toggle', ['display: none'])
  assertCssRuleInMedia('@media (max-width: 900px)', '.app-shell,\n  .app-shell--sidebar-collapsed', [
    'grid-template-columns: 1fr',
  ])
  assertCssRuleInMedia('@media (max-width: 900px)', '.mobile-sidebar-toggle', [
    'display: inline-flex',
    'position: fixed',
  ])
  assertCssRuleInMedia('@media (max-width: 900px)', '.mobile-sidebar-toggle[aria-expanded=\'true\']', [
    'display: none',
  ])
  assertCssRuleInMedia('@media (max-width: 900px)', '.sidebar,\n  .sidebar--collapsed', [
    'position: fixed',
    'transform: translateX(-100%)',
  ])
  assertCssRuleInMedia('@media (max-width: 900px)', '.sidebar,\n  .sidebar--collapsed', [
    'align-items: stretch',
  ])
  assertCssRuleInMedia('@media (max-width: 900px)', '.sidebar--mobile-open', [
    'transform: translateX(0)',
  ])
  assertCssRuleAbsentInMedia('@media (max-width: 900px)', '.sidebar-toggle')
  assert.doesNotMatch(appCss, /mobile-sidebar-close/)
  assertCssRuleInMedia('@media (max-width: 900px)', '.sidebar--collapsed .sidebar__nav', [
    'justify-items: stretch',
  ])
  assertCssRuleInMedia('@media (max-width: 900px)', '.workspace', [
    'height: 100svh',
    'min-height: 100svh',
  ])
  assertCssRuleInMedia('@media (max-width: 900px)', '.workspace-topbar__inner', [
    'padding-left: calc(var(--workspace-topbar-padding-x) + 42px)',
  ])
  assertCssRuleAbsentInMedia('@media (max-width: 560px)', '.sidebar__nav')
})

test('workspace pages share the same content rail', () => {
  assertCssRule('.app-shell', [
    '--workspace-page-width: 1120px',
    '--workspace-page-padding-x: clamp(20px, 3vw, 40px)',
    '--workspace-topbar-padding-x: clamp(8px, 1.2vw, 16px)',
  ])
  assertCssRule('.workspace', [
    'grid-template-rows: 58px minmax(0, 1fr)',
    'align-content: stretch',
    'padding: 0',
  ])
  assertCssRule('.workspace-topbar', [
    'width: 100%',
    'justify-self: center',
    'padding: 0',
  ])
  assertCssRule('.workspace-topbar__inner', [
    'width: 100%',
    'min-height: 100%',
    'padding: 0 var(--workspace-topbar-padding-x)',
  ])
  assertCssRule('.workspace--analysis-detail .workspace-topbar__inner,\n.workspace--documents .workspace-topbar__inner', [
    'width: 100%',
  ])
  assertCssRule('.workspace-body', [
    'width: min(var(--workspace-page-width), 100%)',
    'justify-self: center',
    'min-height: 0',
    'padding: 28px var(--workspace-page-padding-x) 32px',
  ])
})

test('core app type scale stays compact for workspace UI', () => {
  assertCssRule('.brand', ['font-size: 21px'])
  assertCssRule('.nav-item span', ['font-size: 14px'])
  assertCssRule('.workspace-topbar h1', ['font-size: 15px'])
  assertCssRule('.project-search input', ['font-size: 15px'])
  assertCssRule('.search-stage__greeting', ['font-size: clamp(28px, 5vw, 44px)'])
  assertCssRule('.analysis-submissions__toolbar', ['min-height: 34px'])
})

function assertCssRule(selector: string, declarations: string[]) {
  const body = cssRuleBody(selector)
  for (const declaration of declarations) {
    assert.match(body, cssDeclarationPattern(declaration), `${selector} should include ${declaration}`)
  }
}

function cssRuleBody(selector: string): string {
  const escapedSelector = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const match = appCss.match(new RegExp(`${escapedSelector}\\s*\\{([^}]*)\\}`))
  assert.ok(match, `${selector} rule should exist`)
  return match[1]
}

function assertCssRuleInMedia(mediaQuery: string, selector: string, declarations: string[]) {
  const body = cssRuleBodyInMedia(mediaQuery, selector)
  for (const declaration of declarations) {
    assert.match(
      body,
      cssDeclarationPattern(declaration),
      `${selector} inside ${mediaQuery} should include ${declaration}`,
    )
  }
}

function cssRuleBodyInMedia(mediaQuery: string, selector: string): string {
  const mediaStart = appCss.indexOf(`${mediaQuery} {`)
  assert.notEqual(mediaStart, -1, `${mediaQuery} block should exist`)

  let depth = 0
  let mediaEnd = -1
  for (let index = mediaStart; index < appCss.length; index += 1) {
    const character = appCss[index]
    if (character === '{') {
      depth += 1
    }
    if (character === '}') {
      depth -= 1
      if (depth === 0) {
        mediaEnd = index
        break
      }
    }
  }

  assert.notEqual(mediaEnd, -1, `${mediaQuery} block should close`)
  const mediaBody = appCss.slice(mediaStart, mediaEnd + 1)
  const escapedSelector = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const match = mediaBody.match(new RegExp(`${escapedSelector}\\s*\\{([^}]*)\\}`))
  assert.ok(match, `${selector} rule should exist inside ${mediaQuery}`)
  return match[1]
}

function assertCssRuleAbsentInMedia(mediaQuery: string, selector: string) {
  const mediaBody = cssMediaBody(mediaQuery)
  const escapedSelector = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  assert.doesNotMatch(
    mediaBody,
    new RegExp(`${escapedSelector}\\s*\\{`),
    `${selector} rule should not exist inside ${mediaQuery}`,
  )
}

function cssMediaBody(mediaQuery: string): string {
  const mediaStart = appCss.indexOf(`${mediaQuery} {`)
  assert.notEqual(mediaStart, -1, `${mediaQuery} block should exist`)

  let depth = 0
  let mediaEnd = -1
  for (let index = mediaStart; index < appCss.length; index += 1) {
    const character = appCss[index]
    if (character === '{') {
      depth += 1
    }
    if (character === '}') {
      depth -= 1
      if (depth === 0) {
        mediaEnd = index
        break
      }
    }
  }

  assert.notEqual(mediaEnd, -1, `${mediaQuery} block should close`)
  return appCss.slice(mediaStart, mediaEnd + 1)
}

function cssDeclarationPattern(declaration: string): RegExp {
  const [property, value] = declaration.split(':').map((part) => part.trim())
  return new RegExp(`${property}\\s*:\\s*${value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s*;`)
}
