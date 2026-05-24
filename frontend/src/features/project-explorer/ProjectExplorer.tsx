import { useMemo, useState, type FormEvent } from 'react'
import type { QuickAction, RepositorySuggestion } from '../../app/types'
import { normalizeRepositoryQuery } from '../../domain/projectSearch'
import { ProjectSearchForm } from './ProjectSearchForm'
import { QuickActions } from './QuickActions'

type ProjectExplorerProps = {
  quickActions: QuickAction[]
  repositorySuggestions: RepositorySuggestion[]
}

export function ProjectExplorer({ quickActions, repositorySuggestions }: ProjectExplorerProps) {
  const [repositoryQuery, setRepositoryQuery] = useState('openai/codex')

  const normalizedRepository = useMemo(
    () => normalizeRepositoryQuery(repositoryQuery),
    [repositoryQuery],
  )

  function handleProjectSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()

    if (!normalizedRepository) {
      return
    }

    setRepositoryQuery(normalizedRepository)
  }

  return (
    <main className="workspace" aria-labelledby="workspace-title">
      <section className="search-stage">
        <h1 id="workspace-title">探索一个代码仓库</h1>

        <ProjectSearchForm
          onQueryChange={setRepositoryQuery}
          onSuggestionSelect={setRepositoryQuery}
          onSubmit={handleProjectSearch}
          repositoryQuery={repositoryQuery}
          suggestions={repositorySuggestions}
        />

        <QuickActions actions={quickActions} />
      </section>
    </main>
  )
}
