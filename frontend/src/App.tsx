import { Navigate, Route, Routes } from 'react-router-dom'
import { useAuth } from './context/AuthContext'
import Layout from './components/Layout'
import LoginPage from './pages/LoginPage'
import MatcherPage from './pages/MatcherPage'
import StoriesPage from './pages/StoriesPage'
import DiscussPage from './pages/DiscussPage'
import NotesPage from './pages/NotesPage'
import PrivacyPage from './pages/PrivacyPage'
import SettingsPage from './pages/SettingsPage'

export default function App() {
  const { cloudMode, serverHasKey, userId, apiKey, isReady } = useAuth()

  if (!isReady) {
    return (
      <div className="min-h-screen flex items-center justify-center text-gray-400 text-sm">
        Loading…
      </div>
    )
  }

  // Privacy page is always accessible (no auth required)
  // We handle this inside the Routes block below.

  // Cloud mode: require login (except for /privacy)
  if (cloudMode && !userId) {
    return (
      <Routes>
        <Route path="/privacy" element={<PrivacyPage />} />
        <Route path="*" element={<LoginPage />} />
      </Routes>
    )
  }

  // Require API key unless the server already has one in .env
  if (!apiKey && !serverHasKey) {
    return (
      <Routes>
        <Route path="/privacy" element={<PrivacyPage />} />
        <Route path="*" element={<LoginPage />} />
      </Routes>
    )
  }

  return (
    <Routes>
      <Route path="/privacy" element={<PrivacyPage />} />
      <Route element={<Layout />}>
        <Route path="/" element={<MatcherPage />} />
        <Route path="/stories" element={<StoriesPage />} />
        <Route path="/discuss" element={<DiscussPage />} />
        <Route path="/notes" element={<NotesPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
