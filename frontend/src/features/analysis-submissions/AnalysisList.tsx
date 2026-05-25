import { Link, useNavigate } from 'react-router'

import type { AnalysisSubmissionRow } from '../../domain'
import { AnalysisStatusBadge } from './AnalysisStatusBadge'

type AnalysisListProps = {
  cancellingAnalysisIds?: ReadonlySet<string>
  error?: Error | null
  loading?: boolean
  onCancelRow?: (analysisId: string) => void
  onToggleAllSelection?: (selected: boolean) => void
  onToggleRowSelection?: (analysisId: string, selected: boolean) => void
  rows: AnalysisSubmissionRow[]
  selectedAnalysisIds?: ReadonlySet<string>
}

export function AnalysisList({
  cancellingAnalysisIds = new Set<string>(),
  error = null,
  loading = false,
  onCancelRow,
  onToggleAllSelection,
  onToggleRowSelection,
  rows,
  selectedAnalysisIds = new Set<string>(),
}: AnalysisListProps) {
  const navigate = useNavigate()
  const selectableRows = rows.filter((row) => row.canCancel)
  const selectedSelectableCount = selectableRows.filter((row) =>
    selectedAnalysisIds.has(row.analysisId),
  ).length
  const allSelectableSelected =
    selectableRows.length > 0 && selectedSelectableCount === selectableRows.length
  const someSelectableSelected = selectedSelectableCount > 0 && !allSelectableSelected

  function handleRowKeyDown(event: React.KeyboardEvent<HTMLDivElement>, href: string) {
    if (event.key !== 'Enter' && event.key !== ' ') {
      return
    }
    event.preventDefault()
    navigate(href)
  }

  function handleSelectAllChange(event: React.ChangeEvent<HTMLInputElement>) {
    onToggleAllSelection?.(event.currentTarget.checked)
  }

  function handleRowSelectionClick(event: React.MouseEvent<HTMLInputElement>) {
    event.stopPropagation()
  }

  function handleNestedKeyDown(event: React.KeyboardEvent) {
    event.stopPropagation()
  }

  function handleRowSelectionChange(
    event: React.ChangeEvent<HTMLInputElement>,
    analysisId: string,
  ) {
    onToggleRowSelection?.(analysisId, event.currentTarget.checked)
  }

  function handleCancelClick(
    event: React.MouseEvent<HTMLButtonElement>,
    analysisId: string,
  ) {
    event.stopPropagation()
    onCancelRow?.(analysisId)
  }

  if (loading && rows.length === 0) {
    return <div className="analysis-list-state">加载中</div>
  }

  if (error) {
    return <div className="analysis-list-state analysis-list-state--error">{error.message}</div>
  }

  if (rows.length === 0) {
    return <div className="analysis-list-state">暂无任务</div>
  }

  return (
    <div className="analysis-list" role="table" aria-label="分析任务">
      <div className="analysis-list__head" role="row">
        <span className="analysis-list__select" role="columnheader">
          <input
            aria-checked={someSelectableSelected ? 'mixed' : allSelectableSelected}
            aria-label="选择全部可取消任务"
            checked={allSelectableSelected}
            className="analysis-list__checkbox"
            disabled={selectableRows.length === 0}
            onChange={handleSelectAllChange}
            onKeyDown={handleNestedKeyDown}
            type="checkbox"
          />
        </span>
        <span role="columnheader">Repo</span>
        <span role="columnheader">Ref</span>
        <span role="columnheader">状态</span>
        <span role="columnheader">时间</span>
        <span role="columnheader">文档</span>
        <span role="columnheader">操作</span>
      </div>
      <div className="analysis-list__body">
        {rows.map((row) => {
          const isSelected = selectedAnalysisIds.has(row.analysisId)
          const isCancelling = cancellingAnalysisIds.has(row.analysisId)

          return (
            <div
              aria-label={`打开 ${row.repositoryLabel} 的分析对话`}
              className="analysis-list__row"
              data-selected={isSelected}
              key={row.analysisId}
              onClick={() => navigate(row.analysisHref)}
              onKeyDown={(event) => handleRowKeyDown(event, row.analysisHref)}
              role="row"
              tabIndex={0}
            >
              <span className="analysis-list__select" role="cell">
                <input
                  aria-label={`选择 ${row.repositoryLabel} 的分析任务`}
                  checked={isSelected}
                  className="analysis-list__checkbox"
                  disabled={!row.canCancel || isCancelling}
                  onChange={(event) => handleRowSelectionChange(event, row.analysisId)}
                  onClick={handleRowSelectionClick}
                  onKeyDown={handleNestedKeyDown}
                  type="checkbox"
                />
              </span>
              <span className="analysis-list__repo" role="cell">
                <strong>{row.repositoryLabel}</strong>
                <small>{row.repositoryUrl}</small>
              </span>
              <span className="analysis-list__ref" role="cell">
                {row.requestedRef}
              </span>
              <span role="cell">
                <AnalysisStatusBadge label={row.statusLabel} phase={row.statusPhase} />
              </span>
              <span className="analysis-list__updated" role="cell">
                {row.updatedAtLabel}
              </span>
              <span className="analysis-list__actions" role="cell">
                {row.documentsHref ? (
                  <Link
                  className="analysis-list__open"
                  onClick={(event) => event.stopPropagation()}
                  onKeyDown={handleNestedKeyDown}
                  to={row.documentsHref}
                >
                    文档
                  </Link>
                ) : null}
              </span>
              <span className="analysis-list__actions" role="cell">
                <button
                  aria-label={`取消 ${row.repositoryLabel} 的分析任务`}
                  className="analysis-list__cancel"
                  disabled={!row.canCancel || isCancelling}
                  onClick={(event) => handleCancelClick(event, row.analysisId)}
                  onKeyDown={handleNestedKeyDown}
                  type="button"
                >
                  {isCancelling ? '取消中' : '取消'}
                </button>
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
