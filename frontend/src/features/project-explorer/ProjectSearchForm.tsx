import { Search } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import type { RepositorySuggestion } from '../../app/types'

type ProjectSearchFormProps = {
  disabled?: boolean
  onQueryChange: (value: string) => void
  onSuggestionSelect: (suggestion: RepositorySuggestion) => void
  onSubmit: (event: FormEvent<HTMLFormElement>) => void
  repositoryQuery: string
  suggestions: RepositorySuggestion[]
}

export function ProjectSearchForm({
  disabled = false,
  onQueryChange,
  onSuggestionSelect,
  onSubmit,
  repositoryQuery,
  suggestions,
}: ProjectSearchFormProps) {
  const [isSuggestionsOpen, setIsSuggestionsOpen] = useState(false)
  const visibleSuggestions = isSuggestionsOpen ? suggestions : []

  function handleSuggestionSelect(suggestion: RepositorySuggestion) {
    onSuggestionSelect(suggestion)
    setIsSuggestionsOpen(false)
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    onSubmit(event)
    setIsSuggestionsOpen(false)
  }

  return (
    <form className="project-search" onSubmit={handleSubmit}>
      <div className="project-search__field">
        <Search className="project-search__icon" size={20} aria-hidden="true" />
        <label className="sr-only" htmlFor="repository-search">
          搜索项目
        </label>
        <input
          aria-controls="repository-search-suggestions"
          aria-expanded={isSuggestionsOpen}
          autoComplete="off"
          disabled={disabled}
          id="repository-search"
          name="repository"
          onBlur={() => {
            window.setTimeout(() => setIsSuggestionsOpen(false), 120)
          }}
          onChange={(event) => {
            onQueryChange(event.target.value)
            setIsSuggestionsOpen(true)
          }}
          onFocus={() => setIsSuggestionsOpen(true)}
          placeholder="搜索项目，例如 openai/codex"
          role="combobox"
          spellCheck={false}
          value={repositoryQuery}
        />
      </div>
      {visibleSuggestions.length > 0 ? (
        <div
          className="search-menu-content"
          id="repository-search-suggestions"
          role="listbox"
        >
          {visibleSuggestions.map((suggestion) => (
            <button
              className="search-menu-item"
              key={suggestion.value}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => handleSuggestionSelect(suggestion)}
              role="option"
              type="button"
            >
              <Search size={15} aria-hidden="true" />
              <span className="search-menu-item__text">
                <span>{suggestion.label}</span>
                {suggestion.statusLabel ? <small>{suggestion.statusLabel}</small> : null}
              </span>
            </button>
          ))}
        </div>
      ) : null}
    </form>
  )
}
