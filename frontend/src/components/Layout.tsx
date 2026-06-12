import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

const navItems = [
  { to: '/', label: 'Matcher', icon: '🔍' },
  { to: '/stories', label: 'Stories', icon: '📝' },
  { to: '/tracker', label: 'Tracker', icon: '📋' },
  { to: '/discuss', label: 'Discuss', icon: '💬' },
  { to: '/notes', label: 'Editor Notes', icon: '✉️' },
  { to: '/settings', label: 'Settings', icon: '⚙️' },
]

export default function Layout() {
  const { cloudMode, serverHasKey, userId, apiKey, logout, apiClient } = useAuth()

  function handleLogout() {
    if (cloudMode) apiClient.logout().catch(() => {})
    logout()
  }

  return (
    <div className="flex h-screen overflow-hidden bg-gray-50">
      {/* Sidebar */}
      <aside className="w-48 flex-shrink-0 bg-gray-900 text-gray-100 flex flex-col">
        <div className="px-4 py-5">
          <span className="text-sm font-semibold tracking-wide text-gray-300 uppercase">
            Submissions Advisor
          </span>
        </div>
        <nav className="flex-1 px-2 space-y-0.5">
          {navItems.map(({ to, label, icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                `flex items-center gap-2.5 px-3 py-2 rounded text-sm transition-colors ${
                  isActive
                    ? 'bg-indigo-600 text-white'
                    : 'text-gray-300 hover:bg-gray-800 hover:text-white'
                }`
              }
            >
              <span>{icon}</span>
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="px-4 py-4 border-t border-gray-700 space-y-2">
          {cloudMode && userId && (
            <button onClick={handleLogout} className="w-full text-left text-xs text-gray-400 hover:text-gray-200 transition-colors">
              Sign out
            </button>
          )}
          {!apiKey && !serverHasKey && (
            <p className="text-xs text-yellow-400">⚠ API key not set</p>
          )}
          <NavLink to="/privacy" className="block text-xs text-gray-500 hover:text-gray-300 transition-colors">
            Privacy
          </NavLink>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  )
}
