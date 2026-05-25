import {
  BadgeCheck,
  Cable,
  ClipboardList,
  FolderSearch,
  LogOut,
  Plus,
  Settings,
  UserRound,
  WalletCards,
} from 'lucide-react'
import type {
  AppSection,
  NavigationItem,
  QuickAction,
  RepositorySuggestion,
  UserMenuAction,
  UserProfile,
} from './types'

export const defaultAppSection: AppSection = 'explore'

export const navigationItems: NavigationItem[] = [
  {
    id: 'explore',
    label: '探索项目',
    description: '搜索公开 Git 仓库',
    href: '/explore',
    icon: FolderSearch,
  },
  {
    id: 'analysis-submissions',
    label: '提交分析',
    description: '查看和提交分析任务',
    href: '/analysis',
    icon: ClipboardList,
  },
  {
    id: 'subscription',
    label: '订阅',
    description: '管理分析额度与团队计划',
    href: '/subscription',
    icon: WalletCards,
  },
  {
    id: 'mcp',
    label: 'MCP',
    description: '连接上下文服务与工具源',
    href: '/mcp',
    icon: Cable,
  },
]

export const quickActions: QuickAction[] = [
  {
    label: '添加仓库',
    icon: Plus,
    href: '/analysis',
  },
  {
    label: 'DeepDive MCP',
    icon: Cable,
    href: '/mcp',
  },
]

export const repositorySuggestions: RepositorySuggestion[] = [
  {
    label: 'openai/codex',
    value: 'openai/codex',
  },
  {
    label: 'vercel/next.js',
    value: 'vercel/next.js',
  },
  {
    label: 'facebook/react',
    value: 'facebook/react',
  },
]

export const userProfile: UserProfile = {
  initials: 'DW',
  name: 'Doris Wang',
  plan: 'Pro workspace',
  managementLabel: '管理 DeepDive 账户',
}

export const userMenuActions: UserMenuAction[] = [
  {
    label: '用户资料',
    icon: UserRound,
  },
  {
    label: '订阅与额度',
    icon: BadgeCheck,
  },
  {
    label: '偏好设置',
    icon: Settings,
  },
]

export const signOutAction: UserMenuAction = {
  label: '退出登录',
  icon: LogOut,
  danger: true,
}

export function createNavigationItems(activeSection: AppSection): NavigationItem[] {
  return navigationItems.map((item) => ({
    ...item,
    active: item.id === activeSection,
  }))
}

export function routeForAppSection(section: AppSection): string {
  return navigationItems.find((item) => item.id === section)?.href ?? '/analysis'
}

export function sectionForPathname(pathname: string): AppSection {
  if (pathname === '/') {
    return 'explore'
  }
  if (pathname === '/explore' || pathname.startsWith('/explore/')) {
    return 'explore'
  }
  if (pathname === '/subscription' || pathname.startsWith('/subscription/')) {
    return 'subscription'
  }
  if (pathname === '/mcp' || pathname.startsWith('/mcp/')) {
    return 'mcp'
  }
  return 'analysis-submissions'
}
