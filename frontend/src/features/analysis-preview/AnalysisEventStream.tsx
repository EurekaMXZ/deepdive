import { Brain, CheckCircle2, Wrench, XCircle } from 'lucide-react'

import type { AnalysisStreamItem } from '../../domain'
import { StreamingMarkdown } from './StreamingMarkdown'

type AnalysisEventStreamProps = {
  items: AnalysisStreamItem[]
  streaming: boolean
}

export function AnalysisEventStream({ items, streaming }: AnalysisEventStreamProps) {
  if (items.length === 0) {
    return (
      <div className="analysis-event-stream analysis-event-stream--empty" aria-live="polite">
        <div className="analysis-stream-empty">
          <span className="analysis-stream-empty__pulse" aria-hidden="true" />
          正在等待模型开始输出
        </div>
      </div>
    )
  }

  return (
    <div className="analysis-event-stream" aria-live={streaming ? 'polite' : 'off'}>
      {items.map((item) => {
        if (item.type === 'reasoning') {
          return <ReasoningItem item={item} key={item.id} />
        }
        if (item.type === 'output') {
          return <OutputItem item={item} key={item.id} />
        }
        return <ToolItem item={item} key={item.id} />
      })}
    </div>
  )
}

function ReasoningItem({ item }: { item: Extract<AnalysisStreamItem, { type: 'reasoning' }> }) {
  return (
    <article className="analysis-stream-item analysis-stream-item--reasoning">
      <div className="analysis-stream-item__header">
        <Brain size={15} aria-hidden="true" />
        <span>模型思考</span>
      </div>
      <StreamingMarkdown
        className="analysis-stream-markdown analysis-stream-markdown--reasoning"
        fallbackClassName="analysis-stream-markdown__fallback"
        streaming={item.streaming}
        value={item.markdown}
      />
    </article>
  )
}

function OutputItem({ item }: { item: Extract<AnalysisStreamItem, { type: 'output' }> }) {
  return (
    <article className="analysis-stream-item analysis-stream-item--output">
      <div className="analysis-stream-item__header">
        <CheckCircle2 size={15} aria-hidden="true" />
        <span>模型输出</span>
      </div>
      <StreamingMarkdown
        animated
        className="analysis-stream-markdown analysis-stream-markdown--output"
        fallbackClassName="analysis-stream-markdown__fallback"
        streaming={item.streaming}
        value={item.markdown}
      />
    </article>
  )
}

function ToolItem({ item }: { item: Extract<AnalysisStreamItem, { type: 'tool' }> }) {
  const failed = item.ok === false || item.error !== undefined
  const resultSummary = summarizeToolResult(item.result, item.error)

  return (
    <article className="analysis-stream-item analysis-stream-item--tool" data-state={failed ? 'failed' : 'done'}>
      <div className="analysis-stream-item__header">
        {failed ? <XCircle size={15} aria-hidden="true" /> : <Wrench size={15} aria-hidden="true" />}
        <span>{titleForToolName(item.toolName)}</span>
      </div>
      <div className="analysis-tool-body">
        <div className="analysis-tool-body__meta">
          <span>{item.toolName}</span>
          {item.truncated ? <span>已截断</span> : null}
          {item.resultRef ? <span>{item.resultRef}</span> : null}
        </div>
        <div className="analysis-tool-body__summary">{resultSummary}</div>
        <details className="analysis-tool-details">
          <summary>查看工具细节</summary>
          <pre>{stableStringify(toolDetailPayload(item))}</pre>
        </details>
      </div>
    </article>
  )
}

function titleForToolName(toolName: string): string {
  if (toolName === 'read_file') {
    return '读取文件'
  }
  if (toolName === 'search_text') {
    return '搜索源码'
  }
  if (toolName === 'search_file') {
    return '查找文件'
  }
  if (toolName === 'list_files') {
    return '列出文件'
  }
  if (toolName.startsWith('document_')) {
    return '更新文档'
  }
  return '工具调用'
}

function summarizeToolResult(result: unknown, error: unknown): string {
  if (error !== undefined && error !== null) {
    return summarizeUnknown(error)
  }
  if (result !== undefined && result !== null) {
    return summarizeUnknown(result)
  }
  return '等待工具结果'
}

function summarizeUnknown(value: unknown): string {
  if (typeof value === 'string') {
    return compactText(value)
  }
  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value)
  }
  if (Array.isArray(value)) {
    return `${value.length} items`
  }
  if (typeof value === 'object' && value !== null) {
    const record = value as Record<string, unknown>
    const message = record.message
    if (typeof message === 'string' && message.trim()) {
      return compactText(message)
    }
    const keys = Object.keys(record)
    return keys.length > 0 ? keys.slice(0, 4).join(', ') : '{}'
  }
  return String(value)
}

function compactText(value: string): string {
  const normalized = value.replace(/\s+/g, ' ').trim()
  return normalized.length > 180 ? `${normalized.slice(0, 177)}...` : normalized
}

function toolDetailPayload(item: Extract<AnalysisStreamItem, { type: 'tool' }>): Record<string, unknown> {
  return {
    toolCallId: item.toolCallId,
    toolName: item.toolName,
    arguments: item.arguments,
    ok: item.ok,
    result: item.result,
    error: item.error,
    resultRef: item.resultRef,
    evidenceIds: item.evidenceIds,
    truncated: item.truncated,
    nextCursor: item.nextCursor,
  }
}

function stableStringify(value: unknown): string {
  return JSON.stringify(value, null, 2)
}
