import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import test from 'node:test'

const analysisList = readFileSync(
  resolve('src/features/analysis-submissions/AnalysisList.tsx'),
  'utf8',
)
const analysisSubmissionsPage = readFileSync(
  resolve('src/features/analysis-submissions/AnalysisSubmissionsPage.tsx'),
  'utf8',
)
const analysisPreview = readFileSync(
  resolve('src/features/analysis-preview/AnalysisPreview.tsx'),
  'utf8',
)
const appCss = readFileSync(resolve('src/App.css'), 'utf8').replace(/\r\n/g, '\n')

test('analysis submissions table supports row navigation, selection, and cancel actions', () => {
  assert.match(analysisList, /aria-label="选择全部可取消任务"/)
  assert.match(analysisList, /aria-label=\{`选择 \$\{row\.repositoryLabel\} 的分析任务`\}/)
  assert.match(analysisList, /role="columnheader">Repo<\/span>/)
  assert.match(analysisList, /role="columnheader">时间<\/span>/)
  assert.match(analysisList, /role="columnheader">文档<\/span>/)
  assert.match(analysisList, /role="columnheader">操作<\/span>/)
  assert.doesNotMatch(analysisList, /role="columnheader">仓库<\/span>/)
  assert.doesNotMatch(analysisList, /role="columnheader">更新时间<\/span>/)
  assert.doesNotMatch(analysisList, />打开<\/span>/)
  assert.match(analysisList, /aria-label=\{`取消 \$\{row\.repositoryLabel\} 的分析任务`\}/)
  assert.match(analysisList, /data-selected=\{isSelected\}/)
  assert.match(analysisList, /onClick=\{\(\) => navigate\(row\.analysisHref\)\}/)
  assert.match(analysisList, /onKeyDown=\{\(event\) => handleRowKeyDown\(event, row\.analysisHref\)\}/)
  assert.match(analysisList, /onClick=\{\(event\) => event\.stopPropagation\(\)\}/)
  assert.match(appCss, /\.analysis-list__row:hover,\n\.analysis-list__row:focus-visible/)
})

test('analysis pages expose single-task and bulk cancellation handlers', () => {
  assert.match(analysisSubmissionsPage, /selectedAnalysisIds/)
  assert.match(analysisSubmissionsPage, /handleCancelSelectedAnalyses/)
  assert.match(analysisSubmissionsPage, /取消选中任务/)
  assert.match(analysisSubmissionsPage, /cancelAnalysis\(analysisId\)/)
  assert.match(analysisPreview, /aria-label="取消分析任务"/)
  assert.match(analysisPreview, /analysis-preview__cancel/)
})
