import assert from 'node:assert/strict'
import test from 'node:test'

import {
  createNavigationItems,
  defaultAppSection,
  routeForAppSection,
  sectionForPathname,
  navigationItems,
  quickActions,
} from '../src/app/appData.ts'

test('default app section opens project exploration', () => {
  assert.equal(defaultAppSection, 'explore')
})

test('navigation items expose stable ids and active state', () => {
  const items = createNavigationItems('analysis-submissions')

  assert.deepEqual(
    items.map((item) => item.id),
    ['explore', 'analysis-submissions', 'subscription', 'mcp'],
  )
  assert.deepEqual(
    items.map((item) => item.active ?? false),
    [false, true, false, false],
  )
  assert.equal(navigationItems[0].active, undefined)
})

test('navigation sections map to stable route paths', () => {
  assert.equal(routeForAppSection('explore'), '/explore')
  assert.equal(routeForAppSection('analysis-submissions'), '/analysis')
  assert.equal(routeForAppSection('subscription'), '/subscription')
  assert.equal(routeForAppSection('mcp'), '/mcp')
})

test('project quick actions expose navigation targets', () => {
  assert.deepEqual(
    quickActions.map((action) => [action.label, action.href]),
    [
      ['添加仓库', '/analysis'],
      ['DeepDive MCP', '/mcp'],
    ],
  )
})

test('active navigation section is derived from the current pathname', () => {
  assert.equal(sectionForPathname('/'), 'explore')
  assert.equal(sectionForPathname('/analysis'), 'analysis-submissions')
  assert.equal(sectionForPathname('/analysis/analysis-1'), 'analysis-submissions')
  assert.equal(sectionForPathname('/analysis/analysis-1/documents/document-1'), 'analysis-submissions')
  assert.equal(sectionForPathname('/explore'), 'explore')
  assert.equal(sectionForPathname('/subscription'), 'subscription')
  assert.equal(sectionForPathname('/mcp'), 'mcp')
})
