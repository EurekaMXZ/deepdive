import { useEffect, useRef, useState } from 'react'

export type TurnstileWidgetProps = {
  className?: string
  siteKey: string | null
  onError?: (message: string) => void
  onTokenChange: (token: string | null) => void
}

type TurnstileApi = {
  render(
    container: HTMLElement,
    options: {
      callback(token: string): void
      'error-callback'(errorCode: string): boolean
      'expired-callback'(): void
      'timeout-callback'(): void
      sitekey: string
      size: 'normal' | 'compact' | 'flexible'
      theme: 'auto' | 'dark' | 'light'
    },
  ): string
  remove(widgetId: string): void
}

declare global {
  interface Window {
    turnstile?: TurnstileApi
  }
}

const TURNSTILE_SCRIPT_SRC = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit'
const TURNSTILE_SCRIPT_ID = 'deepdive-turnstile-script'

let turnstileScriptPromise: Promise<void> | null = null

export function TurnstileWidget({
  className,
  onError,
  onTokenChange,
  siteKey,
}: TurnstileWidgetProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const widgetIdRef = useRef<string | null>(null)
  const [runtimeStatus, setRuntimeStatus] = useState<'idle' | 'ready' | 'error'>('idle')
  const status = siteKey ? runtimeStatus : 'unconfigured'

  useEffect(() => {
    if (!siteKey || !containerRef.current) {
      onTokenChange(null)
      return
    }

    let cancelled = false
    onTokenChange(null)

    loadTurnstileScript()
      .then(() => {
        if (cancelled || !window.turnstile || !containerRef.current) {
          return
        }

        widgetIdRef.current = window.turnstile.render(containerRef.current, {
          sitekey: siteKey,
          theme: 'dark',
          size: 'flexible',
          callback(token) {
            setRuntimeStatus('ready')
            onTokenChange(token)
          },
          'error-callback'(errorCode) {
            setRuntimeStatus('error')
            onTokenChange(null)
            onError?.(`Turnstile error: ${errorCode}`)
            return true
          },
          'expired-callback'() {
            onTokenChange(null)
          },
          'timeout-callback'() {
            onTokenChange(null)
          },
        })
      })
      .catch((error: unknown) => {
        if (cancelled) {
          return
        }
        setRuntimeStatus('error')
        onTokenChange(null)
        onError?.(error instanceof Error ? error.message : String(error))
      })

    return () => {
      cancelled = true
      if (widgetIdRef.current && window.turnstile) {
        window.turnstile.remove(widgetIdRef.current)
        widgetIdRef.current = null
      }
    }
  }, [onError, onTokenChange, siteKey])

  return (
    <div className={className} data-status={status}>
      <div className="turnstile-widget__mount" ref={containerRef} />
      {siteKey ? null : <span className="turnstile-widget__fallback">Turnstile 未配置</span>}
    </div>
  )
}

function loadTurnstileScript(): Promise<void> {
  if (typeof window === 'undefined' || typeof document === 'undefined') {
    return Promise.reject(new Error('Turnstile is only available in the browser.'))
  }
  if (window.turnstile) {
    return Promise.resolve()
  }
  if (turnstileScriptPromise) {
    return turnstileScriptPromise
  }

  turnstileScriptPromise = new Promise((resolve, reject) => {
    const existingScript = document.getElementById(TURNSTILE_SCRIPT_ID) as HTMLScriptElement | null
    if (existingScript) {
      existingScript.addEventListener('load', () => resolve(), { once: true })
      existingScript.addEventListener('error', () => reject(new Error('Turnstile failed to load.')), {
        once: true,
      })
      return
    }

    const script = document.createElement('script')
    script.id = TURNSTILE_SCRIPT_ID
    script.src = TURNSTILE_SCRIPT_SRC
    script.async = true
    script.defer = true
    script.addEventListener('load', () => resolve(), { once: true })
    script.addEventListener('error', () => reject(new Error('Turnstile failed to load.')), {
      once: true,
    })
    document.head.append(script)
  })

  return turnstileScriptPromise
}
