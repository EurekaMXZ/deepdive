import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import { ChevronRight, Settings, UserRound } from 'lucide-react'
import type { UserMenuAction, UserProfile } from '../app/types'

type UserMenuProps = {
  actions: UserMenuAction[]
  isCollapsed: boolean
  profile: UserProfile
  signOutAction: UserMenuAction
}

export function UserMenu({ actions, isCollapsed, profile, signOutAction }: UserMenuProps) {
  const SignOutIcon = signOutAction.icon

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button className="user-menu-trigger" type="button" aria-label="打开用户管理">
          {isCollapsed ? (
            <UserRound size={19} aria-hidden="true" />
          ) : (
            <>
              <span className="avatar" aria-hidden="true">
                {profile.initials}
              </span>
              <span className="user-menu-trigger__text">
                <span className="user-menu-trigger__name">{profile.name}</span>
                <span className="user-menu-trigger__plan">{profile.plan}</span>
              </span>
              <Settings className="user-menu-trigger__icon" size={18} aria-hidden="true" />
            </>
          )}
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="end"
          className="user-menu-content"
          collisionPadding={10}
          side="right"
          sideOffset={14}
        >
          <DropdownMenu.Label className="user-menu-label">
            <span className="avatar avatar--menu" aria-hidden="true">
              {profile.initials}
            </span>
            <span>
              <strong>{profile.name}</strong>
              <small>{profile.managementLabel}</small>
            </span>
          </DropdownMenu.Label>
          <DropdownMenu.Separator className="user-menu-separator" />
          {actions.map((action) => {
            const Icon = action.icon

            return (
              <DropdownMenu.Item className="user-menu-item" key={action.label}>
                <Icon size={16} aria-hidden="true" />
                {action.label}
                <ChevronRight size={14} aria-hidden="true" />
              </DropdownMenu.Item>
            )
          })}
          <DropdownMenu.Separator className="user-menu-separator" />
          <DropdownMenu.Item className="user-menu-item user-menu-item--danger">
            <SignOutIcon size={16} aria-hidden="true" />
            {signOutAction.label}
          </DropdownMenu.Item>
          <DropdownMenu.Arrow className="user-menu-arrow" />
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  )
}
