import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router'
import type { QuickAction, RepositorySuggestion } from '../../app/types'
import { WorkspaceTopbar } from '../../components/WorkspaceTopbar'
import {
  documentHrefForAnalysisSuggestion,
  getAnalysisStatusMeta,
  getTimeAwareGreeting,
  normalizeRepositoryQuery,
  type AnalysisSuggestion,
} from '../../domain'
import { useAnalysisSuggestions } from '../../hooks'
import { ProjectSearchForm } from './ProjectSearchForm'
import { QuickActions } from './QuickActions'

type ProjectExplorerProps = {
  accessToken?: string | (() => string | null | undefined)
  apiBaseUrl?: string
  quickActions: QuickAction[]
  repositorySuggestions: RepositorySuggestion[]
}

export function ProjectExplorer({
  accessToken,
  apiBaseUrl,
  quickActions,
  repositorySuggestions,
}: ProjectExplorerProps) {
  const navigate = useNavigate()
  const [repositoryQuery, setRepositoryQuery] = useState('')
  const greeting = useMemo(() => getTimeAwareGreeting(), [])
  const suggestionsState = useAnalysisSuggestions({ accessToken, baseUrl: apiBaseUrl })
  const { loadSuggestions } = suggestionsState
  const suggestions = useMemo(
    () =>
      analysisSuggestionsToRepositorySuggestions(
        suggestionsState.data?.items,
        repositorySuggestions,
      ),
    [repositorySuggestions, suggestionsState.data?.items],
  )

  useEffect(() => {
    const trimmedQuery = repositoryQuery.trim()
    if (trimmedQuery.length === 0) {
      return
    }

    const timeoutId = window.setTimeout(() => {
      void loadSuggestions({
        repositoryQuery: trimmedQuery,
        limit: 6,
      }).catch(() => undefined)
    }, 160)

    return () => window.clearTimeout(timeoutId)
  }, [loadSuggestions, repositoryQuery])

  async function handleProjectSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const normalizedRepository = normalizeRepositoryQuery(repositoryQuery)
    if (normalizedRepository) {
      setRepositoryQuery(normalizedRepository)
    }
  }

  function handleSuggestionSelect(suggestion: RepositorySuggestion) {
    if (suggestion.documentsHref) {
      navigate(suggestion.documentsHref)
      return
    }

    setRepositoryQuery(suggestion.value)
  }

  return (
    <main className="workspace workspace--explore" aria-labelledby="workspace-title">
      <WorkspaceTopbar title="探索项目" />
      <section className="workspace-body workspace-body--centered">
        <div className="search-stage" aria-labelledby="workspace-title">
          <h2 className="sr-only" id="workspace-title">
            搜索项目
          </h2>
          <p className="search-stage__greeting">{greeting}</p>

          <ProjectSearchForm
            onQueryChange={setRepositoryQuery}
            onSuggestionSelect={handleSuggestionSelect}
            onSubmit={handleProjectSearch}
            repositoryQuery={repositoryQuery}
            suggestions={suggestions}
          />

          <QuickActions actions={quickActions} />
        </div>
      </section>
    </main>
  )
}

function analysisSuggestionsToRepositorySuggestions(
  analysisSuggestions: AnalysisSuggestion[] | undefined,
  fallbackSuggestions: RepositorySuggestion[],
): RepositorySuggestion[] {
  if (!analysisSuggestions || analysisSuggestions.length === 0) {
    return fallbackSuggestions
  }

  return analysisSuggestions.map((suggestion) => ({
    analysisId: suggestion.analysisId,
    documentsHref: documentHrefForAnalysisSuggestion(suggestion),
    label: suggestion.repositoryLabel,
    statusLabel: getAnalysisStatusMeta(suggestion.status).label,
    value: suggestion.repositoryLabel || suggestion.repositoryUrl,
  }))
}
