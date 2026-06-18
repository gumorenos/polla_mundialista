import { useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { useTheme, type Theme } from '../hooks/useTheme'
import { api } from '../api/client'
import { usePasswordChanged } from '../api/hooks'
import ChatWidget from './ChatWidget'

const navItems = [
  { to: '/', label: 'Dashboard' },
  { to: '/models', label: 'Modelos' },
  { to: '/simulations', label: 'Simulaciones' },
  { to: '/snapshots', label: 'Snapshots' },
  { to: '/calibration', label: 'Calibración' },
  { to: '/jobs', label: 'Jobs' },
  { to: '/news', label: 'Noticias' },
  { to: '/config', label: '⚙ Configuración' },
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
  const [mobileOpen, setMobileOpen] = useState(false)

  return (
    <div
      className="flex min-h-screen"
      style={{ background: 'var(--color-bg)', color: 'var(--color-text)' }}
    >
      {/* Mobile top bar — only visible below md */}
      <div
        className="fixed top-0 left-0 right-0 z-40 flex items-center justify-between px-4 h-14 md:hidden"
        style={{ background: 'var(--color-surface)', borderBottom: '1px solid var(--color-border)' }}
      >
        <h1 className="text-sm font-bold text-blue-400">Oráculo Mundial 2026</h1>
        <button
          onClick={() => setMobileOpen(true)}
          className="p-2 rounded min-w-[44px] min-h-[44px] flex items-center justify-center"
          style={{ color: 'var(--color-muted)' }}
          aria-label="Abrir menú"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="3" y1="6" x2="21" y2="6" />
            <line x1="3" y1="12" x2="21" y2="12" />
            <line x1="3" y1="18" x2="21" y2="18" />
          </svg>
        </button>
      </div>

      {/* Mobile overlay */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/60 md:hidden"
          onClick={() => setMobileOpen(false)}
        />
      )}

      {/* Sidebar */}
      <nav
        className={`
          fixed inset-y-0 left-0 z-50 w-56 flex flex-col
          transition-transform duration-200
          md:static md:translate-x-0 md:transition-none
          ${mobileOpen ? 'translate-x-0' : '-translate-x-full'}
        `}
        style={{
          background: 'var(--color-surface)',
          borderRight: '1px solid var(--color-border)',
        }}
      >
        <div
          className="flex items-center justify-between px-4 py-5 border-b"
          style={{ borderColor: 'var(--color-border)' }}
        >
          <div>
            <h1 className="text-sm font-bold text-blue-400 leading-tight">
              Oráculo<br />Mundial 2026
            </h1>
            {showFirstLoginBadge && (
              <span className="mt-3 inline-flex rounded bg-yellow-900/60 px-2 py-1 text-xs font-medium text-yellow-300">
                Primer login
              </span>
            )}
          </div>
          <button
            onClick={() => setMobileOpen(false)}
            className="md:hidden p-1 rounded min-w-[32px] min-h-[32px] flex items-center justify-center"
            style={{ color: 'var(--color-muted)' }}
            aria-label="Cerrar menú"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        <ul className="mt-4 flex flex-col gap-1 px-2 flex-1">
          {navItems.map(({ to, label }) => (
            <li key={to}>
              <NavLink
                to={to}
                end={to === '/'}
                onClick={() => setMobileOpen(false)}
                className={({ isActive }) =>
                  `block rounded px-3 py-2.5 text-sm transition-colors ${
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

      {/* Main content — top padding on mobile for the fixed top bar */}
      <main className="flex-1 overflow-auto pt-14 md:pt-0">
        <Outlet />
      </main>

      <ChatWidget />
    </div>
  )
}
