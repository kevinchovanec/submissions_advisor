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

  useEffect(() => {
    fetch('/api/health')
      .then((r) => r.json())
      .then((d) => {
        setCloudMode(d.cloud_mode ?? false)
        setServerHasKey(d.has_api_key ?? false)
      })
      .catch(() => {})
      .finally(() => setIsReady(true))
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
