import * as Dialog from '@radix-ui/react-dialog'
import { LoaderCircle, LockKeyhole, Mail } from 'lucide-react'
import { useMemo, useState, type FormEvent } from 'react'
import { siGithub } from 'simple-icons'
import type { SimpleIcon } from 'simple-icons'

import {
  createGitHubLoginUrl,
  createReturnToPath,
  normalizeEmailLoginInput,
  validateEmailLoginDraft,
} from '../../domain/authLogin.ts'
import type { LoginInput } from '../../domain/auth.ts'
import { TurnstileWidget } from './TurnstileWidget.tsx'

export type LoginDialogProps = {
  apiBaseUrl?: string
  error?: string | null
  githubAuthUrl?: string
  isSubmitting?: boolean
  onEmailLogin: (input: LoginInput) => Promise<void> | void
  onGitHubLogin?: (url: string) => void
  turnstileEnabled?: boolean
  turnstileSiteKey?: string | null
}

type SimpleIconMarkProps = {
  className?: string
  icon: SimpleIcon
  size?: number
}

function SimpleIconMark({ className, icon, size = 18 }: SimpleIconMarkProps) {
  return (
    <svg
      aria-hidden="true"
      className={className}
      fill="currentColor"
      height={size}
      viewBox="0 0 24 24"
      width={size}
      xmlns="http://www.w3.org/2000/svg"
    >
      <path d={icon.path} />
    </svg>
  )
}

export function LoginDialog({
  apiBaseUrl = '/api',
  error,
  githubAuthUrl,
  isSubmitting = false,
  onEmailLogin,
  onGitHubLogin,
  turnstileEnabled = false,
  turnstileSiteKey = null,
}: LoginDialogProps) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [turnstileToken, setTurnstileToken] = useState<string | null>(null)
  const [localError, setLocalError] = useState<string | null>(null)

  const validation = validateEmailLoginDraft({
    email,
    password,
    turnstileToken,
    turnstileRequired: turnstileEnabled,
    isSubmitting,
  })
  const visibleError = localError ?? error
  const githubUrl = useMemo(
    () =>
      createGitHubLoginUrl({
        apiBaseUrl,
        githubAuthUrl,
        returnTo: typeof window === 'undefined' ? '/' : createReturnToPath(window.location),
      }),
    [apiBaseUrl, githubAuthUrl],
  )

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setLocalError(null)

    if (!validation.canSubmit || (turnstileEnabled && !turnstileToken)) {
      setLocalError('请完成登录校验')
      return
    }

    await onEmailLogin(
      normalizeEmailLoginInput({
        email,
        password,
        turnstileToken: turnstileEnabled ? turnstileToken : undefined,
      }),
    )
  }

  function handleGitHubLogin() {
    onGitHubLogin?.(githubUrl)
  }

  return (
    <Dialog.Root open modal>
      <Dialog.Portal>
        <Dialog.Overlay className="login-page" />
        <Dialog.Content
          aria-describedby={undefined}
          className="login-dialog"
          onEscapeKeyDown={(event) => event.preventDefault()}
          onInteractOutside={(event) => event.preventDefault()}
          onOpenAutoFocus={(event) => {
            event.preventDefault()
            document.getElementById('deepdive-login-email')?.focus()
          }}
        >
          <Dialog.Title className="login-dialog__title">DeepDive</Dialog.Title>

          <button className="login-dialog__github" type="button" onClick={handleGitHubLogin}>
            <SimpleIconMark icon={siGithub} className="login-dialog__github-mark" size={18} />
            使用 GitHub 登录
          </button>

          <div className="login-dialog__divider" role="separator">
            <span>或</span>
          </div>

          <form className="login-form" onSubmit={handleSubmit}>
            <label className="login-field" htmlFor="deepdive-login-email">
              <Mail size={17} aria-hidden="true" />
              <input
                autoComplete="email"
                id="deepdive-login-email"
                inputMode="email"
                name="email"
                onChange={(event) => setEmail(event.target.value)}
                placeholder="邮箱"
                type="email"
                value={email}
              />
            </label>

            <label className="login-field" htmlFor="deepdive-login-password">
              <LockKeyhole size={17} aria-hidden="true" />
              <input
                autoComplete="current-password"
                id="deepdive-login-password"
                name="password"
                onChange={(event) => setPassword(event.target.value)}
                placeholder="密码"
                type="password"
                value={password}
              />
            </label>

            {turnstileEnabled ? (
              <TurnstileWidget
                className="turnstile-widget"
                onError={setLocalError}
                onTokenChange={setTurnstileToken}
                siteKey={turnstileSiteKey}
              />
            ) : null}

            {visibleError ? <p className="login-dialog__error">{visibleError}</p> : null}

            <button className="login-dialog__submit" disabled={!validation.canSubmit} type="submit">
              {isSubmitting ? (
                <LoaderCircle className="login-dialog__spinner" size={17} aria-hidden="true" />
              ) : null}
              继续
            </button>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
