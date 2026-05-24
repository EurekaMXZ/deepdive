import type { LucideIcon } from 'lucide-react'

export type NavigationItem = {
  label: string
  description: string
  icon: LucideIcon
  active?: boolean
}

export type QuickAction = {
  label: string
  icon: LucideIcon
}

export type RepositorySuggestion = {
  label: string
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
