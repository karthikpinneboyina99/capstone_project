import { useState } from 'react'
import LoadingSpinner from '../components/LoadingSpinner'
import ErrorBanner from '../components/ErrorBanner'
import { useTrades } from '../api/queries'

export default function Trades() {
  const [symbol, setSymbol] = useState('')
  const { data: trades, isLoading, error } = useTrades(symbol || undefined)

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h2 className="text-xl font-bold">Trade History</h2>
        <input
          value={symbol}
          onChange={e => setSymbol(e.target.value.toUpperCase())}
          placeholder="Filter by symbol…"
          className="bg-slate-700 border border-slate-600 rounded-lg px-3 py-1.5 text-sm text-slate-200 placeholder-slate-400 focus:outline-none focus:border-emerald-500 w-36"
        />
      </div>

      {error && <ErrorBanner message="Backend unavailable — trades not loaded." />}
      {isLoading && <LoadingSpinner message="Loading trades..." />}

      {!isLoading && !error && !trades?.length && (
        <div className="text-center text-slate-500 py-20">
          <p className="text-5xl mb-4">📋</p>
          <p className="text-sm">No trades recorded yet.</p>
        </div>
      )}

      {!!trades?.length && (
        <div className="bg-slate-800 rounded-xl overflow-hidden border border-slate-700">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-slate-400 text-xs bg-slate-900/40 border-b border-slate-700">
                {['Symbol', 'Side', 'Qty', 'Price', 'Total', 'Executed', 'Mode'].map(h => (
                  <th key={h} className="text-left px-4 py-3 font-medium">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {trades.map(t => (
                <tr
                  key={t.id}
                  className="border-b border-slate-700/40 hover:bg-slate-700/20 transition-colors"
                >
                  <td className="px-4 py-2 font-semibold">{t.symbol}</td>
                  <td
                    className={`px-4 py-2 font-semibold text-xs uppercase ${
                      t.side === 'buy' ? 'text-emerald-400' : 'text-red-400'
                    }`}
                  >
                    {t.side}
                  </td>
                  <td className="px-4 py-2 font-mono">{t.quantity}</td>
                  <td className="px-4 py-2 font-mono">${t.price.toFixed(2)}</td>
                  <td className="px-4 py-2 font-mono">${(t.quantity * t.price).toFixed(2)}</td>
                  <td className="px-4 py-2 text-slate-400 text-xs">
                    {new Date(t.executed_at).toLocaleString()}
                  </td>
                  <td className="px-4 py-2">
                    <span className="text-xs bg-slate-700 rounded-full px-2 py-0.5">{t.mode}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
