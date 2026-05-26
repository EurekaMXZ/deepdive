import { CheckCircle2, Circle, ListTodo, LoaderCircle, X } from 'lucide-react'
import { useState } from 'react'

import type { AnalysisTodoItem, AnalysisTodoList } from '../../domain'

type AnalysisTodoDockProps = {
  todo: AnalysisTodoList | null
}

export function AnalysisTodoDock({ todo }: AnalysisTodoDockProps) {
  const [open, setOpen] = useState(getInitialTodoDockOpen)

  if (!todo || todo.items.length === 0) {
    return null
  }

  const completedCount = todo.items.filter((item) => item.status === 'completed').length
  const progressText = `${completedCount}/${todo.items.length}`

  return (
    <aside className="analysis-todo-dock" data-open={open} aria-label="分析 TODO">
      <button
        aria-expanded={open}
        aria-controls="analysis-todo-panel"
        className="analysis-todo-dock__trigger"
        onClick={() => setOpen((current) => !current)}
        type="button"
      >
        <ListTodo size={16} aria-hidden="true" />
        <span>TODO</span>
        <strong>{progressText}</strong>
      </button>
      <section className="analysis-todo-dock__panel" id="analysis-todo-panel">
        <header className="analysis-todo-dock__header">
          <div>
            <span>TODO</span>
            <small>{progressText}</small>
          </div>
          <button
            aria-label="收起 TODO"
            className="analysis-todo-dock__close"
            onClick={() => setOpen(false)}
            type="button"
          >
            <X size={15} aria-hidden="true" />
          </button>
        </header>
        <ol className="analysis-todo-dock__list">
          {todo.items.map((item) => (
            <TodoItem item={item} key={item.id} />
          ))}
        </ol>
        {todo.note ? <p className="analysis-todo-dock__note">{todo.note}</p> : null}
      </section>
    </aside>
  )
}

function getInitialTodoDockOpen() {
  if (typeof window === 'undefined') {
    return true
  }

  const isMobileViewport = window.matchMedia('(max-width: 900px)').matches
  return !isMobileViewport
}

function TodoItem({ item }: { item: AnalysisTodoItem }) {
  return (
    <li className="analysis-todo-dock__item" data-status={item.status}>
      <span className="analysis-todo-dock__status" aria-label={statusLabel(item.status)}>
        {statusIcon(item.status)}
      </span>
      <span className="analysis-todo-dock__title">{item.title}</span>
    </li>
  )
}

function statusIcon(status: AnalysisTodoItem['status']) {
  if (status === 'completed') {
    return <CheckCircle2 size={15} aria-hidden="true" />
  }
  if (status === 'in_progress') {
    return <LoaderCircle size={15} aria-hidden="true" />
  }
  return <Circle size={15} aria-hidden="true" />
}

function statusLabel(status: AnalysisTodoItem['status']): string {
  if (status === 'completed') {
    return '已完成'
  }
  if (status === 'in_progress') {
    return '进行中'
  }
  return '待处理'
}
