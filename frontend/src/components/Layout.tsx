import { NavLink, Outlet } from 'react-router-dom'

const navItems = [
  { to: '/', label: 'Dashboard' },
  { to: '/models', label: 'Modelos' },
  { to: '/simulations', label: 'Simulaciones' },
  { to: '/snapshots', label: 'Snapshots' },
  { to: '/calibration', label: 'Calibración' },
  { to: '/jobs', label: 'Jobs' },
]

export default function Layout() {
  return (
    <div className="flex min-h-screen bg-gray-950 text-gray-100">
      {/* Sidebar */}
      <nav className="w-56 shrink-0 border-r border-gray-800 bg-gray-900 flex flex-col">
        <div className="px-4 py-5 border-b border-gray-800">
          <h1 className="text-sm font-bold text-blue-400 leading-tight">
            Oráculo<br />Mundial 2026
          </h1>
        </div>
        <ul className="mt-4 flex flex-col gap-1 px-2">
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
      </nav>

      {/* Main content */}
      <main className="flex-1 overflow-auto">
        <Outlet />
      </main>
    </div>
  )
}
