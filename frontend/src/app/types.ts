import type { LucideIcon } from 'lucide-react'

export type AppSection = 'explore' | 'analysis-submissions' | 'subscription' | 'mcp'

export type NavigationItem = {
  id: AppSection
  label: string
  description: string
  href: string
  icon: LucideIcon
  active?: boolean
}

export type QuickAction = {
  label: string
  icon: LucideIcon
  href: string
}

export type RepositorySuggestion = {
  analysisId?: string
  documentsHref?: string | null
  label: string
  statusLabel?: string
  value: string
}

export type UserProfile = {
  initials: string
  name: string
  plan: string
  managementLabel: string
}

export type UserMenuAction = {
  label: string
  icon: LucideIcon
  danger?: boolean
}
