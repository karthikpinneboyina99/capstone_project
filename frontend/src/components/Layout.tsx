import { Link, useLocation, Outlet } from 'react-router-dom'

const NAV = [
  { to: '/market', label: 'Live Market', icon: '📡' },
  { to: '/sim-portfolio', label: 'Sim Portfolio', icon: '💼' },
  { to: '/', label: 'Dashboard', icon: '📊' },
  { to: '/signals', label: 'Signals', icon: '🎯' },
  { to: '/trades', label: 'Trades', icon: '📋' },
  { to: '/backtests', label: 'Backtests', icon: '📈' },
  { to: '/settings', label: 'Settings', icon: '⚙️' },
]

export default function Layout() {
  const { pathname } = useLocation()
  return (
    <div className="flex h-screen bg-slate-900 text-slate-100 overflow-hidden">
      <aside className="w-56 bg-slate-800 flex flex-col shrink-0 border-r border-slate-700">
        <div className="p-4 border-b border-slate-700">
          <h1 className="text-base font-bold text-emerald-400">AI Trading</h1>
          <p className="text-xs text-slate-400 mt-0.5">Paper trading workstation</p>
        </div>
        <nav className="flex-1 p-2 space-y-0.5">
          {NAV.map(({ to, label, icon }) => (
            <Link
              key={to}
              to={to}
              className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors ${
                pathname === to
                  ? 'bg-emerald-600 text-white font-medium'
                  : 'text-slate-300 hover:bg-slate-700'
              }`}
            >
              <span className="text-base leading-none">{icon}</span>
              {label}
            </Link>
          ))}
        </nav>
        <div className="p-3 text-xs text-slate-500 border-t border-slate-700">
          v0.1.0 · paper mode
        </div>
      </aside>

      <div className="flex-1 flex flex-col overflow-hidden">
        <div className="bg-amber-500 text-amber-950 text-xs text-center py-1.5 font-medium shrink-0">
          ⚠ Paper trading only — not financial advice. Simulated account only.
        </div>
        <main className="flex-1 overflow-auto p-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
