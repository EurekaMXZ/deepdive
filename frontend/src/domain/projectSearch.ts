const GITHUB_SHORTHAND_PATTERN = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/

export function normalizeRepositoryQuery(query: string): string {
  const trimmedQuery = query.trim()

  if (GITHUB_SHORTHAND_PATTERN.test(trimmedQuery)) {
    return `https://github.com/${trimmedQuery}.git`
  }

  return trimmedQuery
}
