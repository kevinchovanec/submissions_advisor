import { createContext, useContext, useEffect, useMemo, useState } from 'react'
import { createApiClient, type ApiClient } from '../api/client'

interface AuthState {
  cloudMode: boolean
  serverHasKey: boolean   // ANTHROPIC_API_KEY set in server .env
  userId: string | null
  accessToken: string | null
  apiKey: string | null
  apiClient: ApiClient
  login(userId: string, accessToken: string, refreshToken: string): void
  logout(): void
  setApiKey(key: string): void
  isReady: boolean   // true once /api/health has been checked
}

const AuthContext = createContext<AuthState | null>(null)

const SESSION_TOKEN_KEY = 'sa_token'
const SESSION_REFRESH_KEY = 'sa_refresh'
const SESSION_USER_KEY = 'sa_user'
const SESSION_APIKEY_KEY = 'sa_apikey'

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [cloudMode, setCloudMode] = useState(false)
  const [serverHasKey, setServerHasKey] = useState(false)
  const [isReady, setIsReady] = useState(false)
  const [userId, setUserId] = useState<string | null>(() => sessionStorage.getItem(SESSION_USER_KEY))
  const [accessToken, setAccessToken] = useState<string | null>(() => sessionStorage.getItem(SESSION_TOKEN_KEY))
  const [apiKey, setApiKeyState] = useState<string | null>(() => sessionStorage.getItem(SESSION_APIKEY_KEY))

  // On mount: check health and attempt token refresh if a refresh token is stored
  useEffect(() => {
    const storedRefresh = sessionStorage.getItem(SESSION_REFRESH_KEY)

    fetch('/api/health')
      .then((r) => r.json())
      .then(async (d) => {
        setCloudMode(d.cloud_mode ?? false)
        setServerHasKey(d.has_api_key ?? false)

        if (d.cloud_mode && storedRefresh) {
          try {
            const res = await fetch('/api/auth/refresh', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ refresh_token: storedRefresh }),
            })
            if (res.ok) {
              const data = await res.json()
              sessionStorage.setItem(SESSION_TOKEN_KEY, data.access_token)
              sessionStorage.setItem(SESSION_REFRESH_KEY, data.refresh_token)
              sessionStorage.setItem(SESSION_USER_KEY, data.user_id)
              setAccessToken(data.access_token)
              setUserId(data.user_id)
            }
          } catch { /* ignore — user will need to log in manually */ }
        }
      })
      .catch(() => {})
      .finally(() => setIsReady(true))
  }, [])

  // Refresh token every 50 minutes to prevent expiry mid-session
  useEffect(() => {
    const interval = setInterval(async () => {
      const storedRefresh = sessionStorage.getItem(SESSION_REFRESH_KEY)
      if (!storedRefresh) return
      try {
        const res = await fetch('/api/auth/refresh', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh_token: storedRefresh }),
        })
        if (res.ok) {
          const data = await res.json()
          sessionStorage.setItem(SESSION_TOKEN_KEY, data.access_token)
          sessionStorage.setItem(SESSION_REFRESH_KEY, data.refresh_token)
          setAccessToken(data.access_token)
        }
      } catch { /* ignore */ }
    }, 50 * 60 * 1000)
    return () => clearInterval(interval)
  }, [])

  function login(uid: string, token: string, refresh: string) {
    sessionStorage.setItem(SESSION_USER_KEY, uid)
    sessionStorage.setItem(SESSION_TOKEN_KEY, token)
    sessionStorage.setItem(SESSION_REFRESH_KEY, refresh)
    setUserId(uid)
    setAccessToken(token)
  }

  function logout() {
    sessionStorage.removeItem(SESSION_USER_KEY)
    sessionStorage.removeItem(SESSION_TOKEN_KEY)
    sessionStorage.removeItem(SESSION_REFRESH_KEY)
    setUserId(null)
    setAccessToken(null)
  }

  function setApiKey(key: string) {
    sessionStorage.setItem(SESSION_APIKEY_KEY, key)
    setApiKeyState(key)
  }

  const apiClient = useMemo(() => createApiClient(accessToken, apiKey), [accessToken, apiKey])

  return (
    <AuthContext.Provider value={{ cloudMode, serverHasKey, userId, accessToken, apiKey, apiClient, login, logout, setApiKey, isReady }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}
