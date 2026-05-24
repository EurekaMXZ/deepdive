import {
  BadgeCheck,
  Cable,
  FolderSearch,
  LogOut,
  Plus,
  Settings,
  UserRound,
  WalletCards,
} from 'lucide-react'
import type {
  NavigationItem,
  QuickAction,
  RepositorySuggestion,
  UserMenuAction,
  UserProfile,
} from './types'

export const navigationItems: NavigationItem[] = [
  {
    label: '探索项目',
    description: '搜索并分析公开 Git 仓库',
    icon: FolderSearch,
    active: true,
  },
  {
    label: '订阅',
    description: '管理分析额度与团队计划',
    icon: WalletCards,
  },
  {
    label: 'MCP',
    description: '连接上下文服务与工具源',
    icon: Cable,
  },
]

export const quickActions: QuickAction[] = [
  {
    label: '添加仓库',
    icon: Plus,
  },
  {
    label: 'DeepDive MCP',
    icon: Cable,
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
