import { Languages, Share2, SunMoon } from 'lucide-react'

type WorkspaceTopbarProps = {
  title: string
}

export function WorkspaceTopbar({ title }: WorkspaceTopbarProps) {
  return (
    <header className="workspace-topbar">
      <div className="workspace-topbar__inner">
        <h1>{title}</h1>
        <div className="workspace-topbar__actions" aria-label="Workspace actions">
          <button aria-label="切换亮暗色" className="workspace-topbar__action" type="button">
            <SunMoon size={16} aria-hidden="true" />
          </button>
          <button aria-label="翻译" className="workspace-topbar__action" type="button">
            <Languages size={16} aria-hidden="true" />
          </button>
          <button aria-label="分享" className="workspace-topbar__action" type="button">
            <Share2 size={16} aria-hidden="true" />
          </button>
        </div>
      </div>
    </header>
  )
}
