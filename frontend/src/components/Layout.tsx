import { NavLink, Outlet } from 'react-router-dom'
import { useTheme, type Theme } from '../hooks/useTheme'
import { api } from '../api/client'
import { usePasswordChanged } from '../api/hooks'

const navItems = [
  { to: '/', label: 'Dashboard' },
  { to: '/models', label: 'Modelos' },
  { to: '/simulations', label: 'Simulaciones' },
  { to: '/snapshots', label: 'Snapshots' },
  { to: '/calibration', label: 'Calibración' },
  { to: '/jobs', label: 'Jobs' },
  { to: '/news', label: 'Noticias' },
]

const themeOptions: { value: Theme; label: string; icon: string; title: string }[] = [
  { value: 'light', label: 'Light', icon: '☀', title: 'Tema claro' },
  { value: 'dark',  label: 'Dark',  icon: '🌙', title: 'Tema oscuro' },
  { value: 'black', label: 'Black', icon: '⬛', title: 'AMOLED negro' },
]

function ThemeSwitcher() {
  const { theme, setTheme } = useTheme()

  return (
    <div
      className="px-3 py-3 border-t"
      style={{ borderColor: 'var(--color-border)' }}
    >
      <p
        className="text-xs font-semibold uppercase tracking-wider mb-2"
        style={{ color: 'var(--color-muted)' }}
      >
        Tema
      </p>
      <div className="flex gap-1">
        {themeOptions.map((opt) => (
          <button
            key={opt.value}
            title={opt.title}
            onClick={() => setTheme(opt.value)}
            className="flex-1 flex flex-col items-center gap-0.5 rounded py-1.5 text-xs transition-colors"
            style={{
              background: theme === opt.value ? 'var(--color-accent)' : 'var(--color-surface2)',
              color: theme === opt.value ? '#ffffff' : 'var(--color-muted)',
            }}
          >
            <span className="text-base leading-none">{opt.icon}</span>
            <span>{opt.label}</span>
          </button>
        ))}
      </div>
    </div>
  )
}

function LogoutButton() {
  const handleLogout = async () => {
    await api.post('/api/auth/logout', {})
    window.location.href = '/login'
  }
  return (
    <div
      className="px-3 py-2 border-t"
      style={{ borderColor: 'var(--color-border)' }}
    >
      <button
        onClick={handleLogout}
        className="w-full rounded py-1.5 text-xs transition-colors"
        style={{ background: 'var(--color-surface2)', color: 'var(--color-muted)' }}
      >
        Cerrar sesión
      </button>
    </div>
  )
}

export default function Layout() {
  const { data: passwordState } = usePasswordChanged()
  const showFirstLoginBadge = passwordState?.password_changed === false

  return (
    <div
      className="flex min-h-screen"
      style={{ background: 'var(--color-bg)', color: 'var(--color-text)' }}
    >
      {/* Sidebar */}
      <nav
        className="w-56 shrink-0 border-r flex flex-col"
        style={{
          background: 'var(--color-surface)',
          borderColor: 'var(--color-border)',
        }}
      >
        <div
          className="px-4 py-5 border-b"
          style={{ borderColor: 'var(--color-border)' }}
        >
          <h1 className="text-sm font-bold text-blue-400 leading-tight">
            Oráculo<br />Mundial 2026
          </h1>
          {showFirstLoginBadge && (
            <span className="mt-3 inline-flex rounded bg-yellow-900/60 px-2 py-1 text-xs font-medium text-yellow-300">
              Primer login
            </span>
          )}
        </div>

        <ul className="mt-4 flex flex-col gap-1 px-2 flex-1">
          {navItems.map(({ to, label }) => (
            <li key={to}>
              <NavLink
                to={to}
                end={to === '/'}
                className={({ isActive }) =>
                  `block rounded px-3 py-2 text-sm transition-colors ${
                    isActive
                      ? 'bg-blue-600 text-white'
                      : 'text-gray-400 hover:bg-gray-800 hover:text-gray-100'
                  }`
                }
              >
                {label}
              </NavLink>
            </li>
          ))}
        </ul>

        <ThemeSwitcher />
        <LogoutButton />
      </nav>

      {/* Main content */}
      <main className="flex-1 overflow-auto">
        <Outlet />
      </main>
    </div>
  )
}
