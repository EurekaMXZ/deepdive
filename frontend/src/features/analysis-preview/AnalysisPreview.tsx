import { useEffect, useRef } from 'react'
import { ArrowLeft, CircleDot, XCircle } from 'lucide-react'

import {
  createAnalysisStreamItems,
  getAnalysisStatusMeta,
  type AnalysisId,
  type AnalysisStreamState,
} from '../../domain'
import { AnalysisEventStream } from './AnalysisEventStream'
import { isAnalysisThreadAtBottom } from './analysisScroll'
import { AnalysisTodoDock } from './AnalysisTodoDock'

type AnalysisPreviewProps = {
  analysisId: AnalysisId | null
  canCancel?: boolean
  createError?: Error | null
  isCancelling?: boolean
  isCreating?: boolean
  onBack?: () => void
  onCancel?: () => Promise<unknown> | void
  repositoryUrl: string
  stream: AnalysisStreamState
}

export function AnalysisPreview({
  analysisId,
  canCancel = false,
  createError = null,
  isCancelling = false,
  isCreating = false,
  onBack,
  onCancel,
  repositoryUrl,
  stream,
}: AnalysisPreviewProps) {
  const streamItems = createAnalysisStreamItems(stream)
  const statusLabel = stream.status ? getAnalysisStatusMeta(stream.status).label : '已提交'
  const errorMessage = createError?.message ?? stream.error?.message ?? null
  const threadRef = useRef<HTMLDivElement>(null)
  const shouldStickToBottomRef = useRef(true)
  const streamUpdateKey = streamItems
    .map((item) =>
      item.type === 'tool'
        ? `${item.id}:tool:${item.replayId ?? ''}`
        : `${item.id}:${item.type}:${item.markdown.length}:${item.streaming}:${item.replayId ?? ''}`,
    )
    .join('|')

  useEffect(() => {
    if (!shouldStickToBottomRef.current) {
      return
    }
    const thread = threadRef.current
    if (!thread) {
      return
    }
    thread.scrollTo({ top: thread.scrollHeight })
  }, [streamUpdateKey, errorMessage])

  function handleThreadScroll(event: React.UIEvent<HTMLDivElement>) {
    shouldStickToBottomRef.current = isAnalysisThreadAtBottom(event.currentTarget)
  }

  function handleCancelClick() {
    if (!canCancel || isCancelling || isCreating) {
      return
    }

    void onCancel?.()
  }

  return (
    <section className="analysis-preview" aria-label="分析预览">
      <div className="analysis-preview__conversation">
        <header className="analysis-preview__header">
          {onBack ? (
            <button
              aria-label="返回搜索"
              className="analysis-preview__back"
              onClick={onBack}
              type="button"
            >
              <ArrowLeft size={18} aria-hidden="true" />
            </button>
          ) : null}
          <div className="analysis-preview__title">
            <span>{repositoryUrl}</span>
            <small>{analysisId ?? 'creating'}</small>
          </div>
          <div className="analysis-preview__actions">
            <span className="analysis-preview__status" data-terminal={stream.isTerminal}>
              <CircleDot size={12} aria-hidden="true" />
              {isCreating ? '创建中' : statusLabel}
            </span>
            {onCancel && (canCancel || isCancelling) ? (
              <button
                aria-label="取消分析任务"
                className="analysis-preview__cancel"
                disabled={!canCancel || isCancelling || isCreating}
                onClick={handleCancelClick}
                type="button"
              >
                <XCircle size={16} aria-hidden="true" />
                <span>{isCancelling ? '取消中' : '取消任务'}</span>
              </button>
            ) : null}
          </div>
        </header>

        <div className="analysis-preview__thread" onScroll={handleThreadScroll} ref={threadRef}>
          <div className="analysis-preview__message analysis-preview__message--user">
            {repositoryUrl}
          </div>
          <div className="analysis-preview__message analysis-preview__message--assistant">
            <AnalysisEventStream items={streamItems} streaming={!stream.isTerminal} />
          </div>
          {errorMessage ? <div className="analysis-preview__error">{errorMessage}</div> : null}
        </div>
      </div>
      <AnalysisTodoDock todo={stream.todo} />
    </section>
  )
}
