import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

export default function LoginPage() {
  const { cloudMode, login, setApiKey, apiKey, apiClient } = useAuth()
  const [tab, setTab] = useState<'login' | 'signup'>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [password2, setPassword2] = useState('')
  const [key, setKey] = useState(apiKey ?? '')
  const [error, setError] = useState('')
  const [info, setInfo] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleAuth(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setInfo('')
    setLoading(true)
    try {
      if (tab === 'login') {
        const res = await apiClient.login(email, password)
        login(res.user_id, res.access_token, res.refresh_token)
      } else {
        if (password !== password2) { setError('Passwords do not match'); return }
        const res = await apiClient.signup(email, password)
        setInfo(res.message)
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setLoading(false)
    }
  }

  function handleKeySubmit(e: React.FormEvent) {
    e.preventDefault()
    if (key.trim()) setApiKey(key.trim())
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="w-full max-w-md space-y-6">
        {/* Cloud auth */}
        {cloudMode && (
          <div className="card">
            <h1 className="text-xl font-semibold mb-4">Submissions Advisor</h1>
            <div className="flex border-b border-gray-200 mb-4">
              {(['login', 'signup'] as const).map((t) => (
                <button
                  key={t}
                  onClick={() => setTab(t)}
                  className={`px-4 py-2 text-sm font-medium capitalize transition-colors border-b-2 -mb-px ${
                    tab === t ? 'border-indigo-600 text-indigo-600' : 'border-transparent text-gray-500 hover:text-gray-700'
                  }`}
                >
                  {t === 'login' ? 'Log in' : 'Sign up'}
                </button>
              ))}
            </div>
            <form onSubmit={handleAuth} className="space-y-3">
              <div>
                <label className="label">Email</label>
                <input className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
              </div>
              <div>
                <label className="label">Password</label>
                <input className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
              </div>
              {tab === 'signup' && (
                <div>
                  <label className="label">Confirm password</label>
                  <input className="input" type="password" value={password2} onChange={(e) => setPassword2(e.target.value)} required />
                </div>
              )}
              {error && <p className="text-sm text-red-600">{error}</p>}
              {info && <p className="text-sm text-green-600">{info}</p>}
              <button type="submit" className="btn-primary w-full justify-center" disabled={loading}>
                {loading ? 'Please wait…' : tab === 'login' ? 'Log in' : 'Create account'}
              </button>
            </form>
          </div>
        )}

        {/* API key */}
        <div className="card">
          <h2 className="text-base font-semibold mb-1">Anthropic API Key</h2>
          <p className="text-xs text-gray-500 mb-3">
            Stored in session only — cleared when you close the tab. Never written to the database.
          </p>
          <form onSubmit={handleKeySubmit} className="flex gap-2">
            <input
              className="input flex-1"
              type="password"
              placeholder="sk-ant-…"
              value={key}
              onChange={(e) => setKey(e.target.value)}
            />
            <button type="submit" className="btn-primary" disabled={!key.trim()}>
              {apiKey ? 'Update' : 'Set key'}
            </button>
          </form>
          {apiKey && <p className="text-xs text-green-600 mt-1">✓ API key set</p>}
        </div>

        {!cloudMode && apiKey && (
          <p className="text-center text-sm text-gray-500">
            Running in local mode — your data stays on this machine.
          </p>
        )}

        <p className="text-center text-xs text-gray-400">
          <Link to="/privacy" className="hover:underline">Privacy policy</Link>
        </p>
      </div>
    </div>
  )
}
