import * as Dialog from '@radix-ui/react-dialog'
import { LoaderCircle, Plus, X } from 'lucide-react'
import { useMemo, useState, type FormEvent } from 'react'

import {
  normalizeCreateAnalysisDraft,
  validateCreateAnalysisDraft,
  type CreateAnalysisDraft,
  type NormalizedCreateAnalysisDraft,
} from '../../domain'

type CreateAnalysisDialogProps = {
  error?: Error | null
  loading?: boolean
  onOpenChange: (open: boolean) => void
  onSubmit: (draft: NormalizedCreateAnalysisDraft) => Promise<void> | void
  open: boolean
}

const DEFAULT_DRAFT: CreateAnalysisDraft = {
  repository: '',
  ref: 'main',
}

export function CreateAnalysisDialog({
  error = null,
  loading = false,
  onOpenChange,
  onSubmit,
  open,
}: CreateAnalysisDialogProps) {
  const [draft, setDraft] = useState<CreateAnalysisDraft>(DEFAULT_DRAFT)
  const validation = useMemo(() => validateCreateAnalysisDraft(draft), [draft])

  function handleOpenChange(nextOpen: boolean) {
    onOpenChange(nextOpen)
    if (!nextOpen) {
      setDraft(DEFAULT_DRAFT)
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()

    if (!validation.canSubmit || loading) {
      return
    }

    await onSubmit(normalizeCreateAnalysisDraft(draft))
  }

  return (
    <Dialog.Root open={open} onOpenChange={handleOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="create-analysis-dialog-overlay" />
        <Dialog.Content className="create-analysis-dialog">
          <div className="create-analysis-dialog__header">
            <Dialog.Title className="create-analysis-dialog__title">提交分析</Dialog.Title>
            <Dialog.Close className="create-analysis-dialog__close" aria-label="关闭" type="button">
              <X size={18} aria-hidden="true" />
            </Dialog.Close>
          </div>

          <form className="create-analysis-form" onSubmit={handleSubmit}>
            <label className="create-analysis-field" htmlFor="analysis-repository">
              <span>仓库</span>
              <input
                autoComplete="off"
                id="analysis-repository"
                name="repository"
                onChange={(event) =>
                  setDraft((current) => ({ ...current, repository: event.target.value }))
                }
                placeholder="openai/codex"
                spellCheck={false}
                value={draft.repository}
              />
            </label>

            <label className="create-analysis-field" htmlFor="analysis-ref">
              <span>Ref</span>
              <input
                autoComplete="off"
                id="analysis-ref"
                name="ref"
                onChange={(event) => setDraft((current) => ({ ...current, ref: event.target.value }))}
                placeholder="main"
                spellCheck={false}
                value={draft.ref}
              />
            </label>

            {validation.repositoryError ? (
              <p className="create-analysis-form__error">{validation.repositoryError}</p>
            ) : null}
            {error ? <p className="create-analysis-form__error">{error.message}</p> : null}

            <div className="create-analysis-form__actions">
              <Dialog.Close className="create-analysis-form__secondary" type="button">
                取消
              </Dialog.Close>
              <button
                className="analysis-submit-button"
                disabled={!validation.canSubmit || loading}
                type="submit"
              >
                {loading ? (
                  <LoaderCircle className="create-analysis-form__spinner" size={17} aria-hidden="true" />
                ) : (
                  <Plus size={17} aria-hidden="true" />
                )}
                <span>{loading ? '提交中' : '提交'}</span>
              </button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
