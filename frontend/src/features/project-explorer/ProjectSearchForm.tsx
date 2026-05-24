import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import { Search } from 'lucide-react'
import type { FormEvent } from 'react'
import type { RepositorySuggestion } from '../../app/types'

type ProjectSearchFormProps = {
  onQueryChange: (value: string) => void
  onSuggestionSelect: (value: string) => void
  onSubmit: (event: FormEvent<HTMLFormElement>) => void
  repositoryQuery: string
  suggestions: RepositorySuggestion[]
}

export function ProjectSearchForm({
  onQueryChange,
  onSuggestionSelect,
  onSubmit,
  repositoryQuery,
  suggestions,
}: ProjectSearchFormProps) {
  return (
    <DropdownMenu.Root>
      <form className="project-search" onSubmit={onSubmit}>
        <DropdownMenu.Trigger asChild>
          <div className="project-search__field">
            <Search className="project-search__icon" size={20} aria-hidden="true" />
            <label className="sr-only" htmlFor="repository-search">
              搜索项目
            </label>
            <input
              autoComplete="off"
              id="repository-search"
              name="repository"
              onChange={(event) => onQueryChange(event.target.value)}
              placeholder="搜索项目，例如 openai/codex"
              spellCheck={false}
              value={repositoryQuery}
            />
          </div>
        </DropdownMenu.Trigger>
      </form>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="start"
          className="search-menu-content"
          collisionPadding={16}
          sideOffset={10}
        >
          {suggestions.map((suggestion) => (
            <DropdownMenu.Item
              className="search-menu-item"
              key={suggestion.value}
              onSelect={() => onSuggestionSelect(suggestion.value)}
            >
              <Search size={15} aria-hidden="true" />
              <span>{suggestion.label}</span>
            </DropdownMenu.Item>
          ))}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  )
}
