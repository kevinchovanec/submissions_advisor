import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

export default function SettingsPage() {
  const { cloudMode, apiKey, setApiKey, apiClient, logout } = useAuth()
  const [newKey, setNewKey] = useState(apiKey ?? '')
  const [keyMsg, setKeyMsg] = useState('')

  const [delConfirm, setDelConfirm] = useState('')
  const [delError, setDelError] = useState('')
  const [deleting, setDeleting] = useState(false)

  function handleUpdateKey(e: React.FormEvent) {
    e.preventDefault()
    const trimmed = newKey.trim()
    if (trimmed) {
      setApiKey(trimmed)
      setKeyMsg('API key updated.')
      setTimeout(() => setKeyMsg(''), 3000)
    }
  }

  async function handleDownload() {
    const res = await apiClient.exportData()
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'submissions_advisor_data.zip'
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  async function handleDeleteAccount() {
    if (delConfirm !== 'DELETE') return
    setDeleting(true)
    setDelError('')
    try {
      await apiClient.deleteAccount()
      logout()
    } catch (err: unknown) {
      setDelError(err instanceof Error ? err.message : 'Unknown error')
      setDeleting(false)
    }
  }

  return (
    <div className="max-w-xl mx-auto px-6 py-10 space-y-8">
      <h1 className="text-2xl font-semibold">Settings</h1>

      {/* API Key */}
      <section className="card space-y-3">
        <h2 className="text-base font-semibold">Anthropic API Key</h2>
        <p className="text-xs text-gray-500">
          Stored in session only — cleared when you close the tab. Never written to the database.
        </p>
        <form onSubmit={handleUpdateKey} className="flex gap-2">
          <input
            className="input flex-1"
            type="password"
            placeholder="sk-ant-…"
            value={newKey}
            onChange={(e) => setNewKey(e.target.value)}
          />
          <button type="submit" className="btn-primary" disabled={!newKey.trim()}>
            {apiKey ? 'Update' : 'Set key'}
          </button>
        </form>
        {apiKey && <p className="text-xs text-green-600">Current key: set</p>}
        {keyMsg && <p className="text-xs text-green-600">{keyMsg}</p>}
      </section>

      {/* Download data */}
      <section className="card space-y-3">
        <h2 className="text-base font-semibold">Download Your Data</h2>
        <p className="text-sm text-gray-600">
          Export all your stories, submission history, templates, and feedback as a ZIP archive.
        </p>
        <button onClick={handleDownload} className="btn-secondary">
          Download data (.zip)
        </button>
      </section>

      {/* Delete account — cloud only */}
      {cloudMode && (
        <section className="card space-y-3 border-red-200">
          <h2 className="text-base font-semibold text-red-700">Delete Account</h2>
          <p className="text-sm text-gray-600">
            Permanently deletes all your stories, submissions, templates, feedback, and chat
            history. This cannot be undone. Type <strong>DELETE</strong> to confirm.
          </p>
          <input
            className="input"
            type="text"
            placeholder="Type DELETE to confirm"
            value={delConfirm}
            onChange={(e) => setDelConfirm(e.target.value)}
          />
          {delError && <p className="text-sm text-red-600">{delError}</p>}
          <button
            className="btn-danger"
            disabled={delConfirm !== 'DELETE' || deleting}
            onClick={handleDeleteAccount}
          >
            {deleting ? 'Deleting…' : 'Delete my account'}
          </button>
        </section>
      )}

      <p className="text-xs text-gray-400">
        <Link to="/privacy" className="hover:underline">Privacy policy</Link>
      </p>
    </div>
  )
}
