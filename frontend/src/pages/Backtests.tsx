import { useState } from 'react'
import LoadingSpinner from '../components/LoadingSpinner'
import ErrorBanner from '../components/ErrorBanner'
import EquityCurveChart from '../components/EquityCurveChart'
import { useBacktestRuns } from '../api/queries'

function fmt(v: number | undefined, pct = false): string {
  if (v == null) return '—'
  return pct ? `${(v * 100).toFixed(2)}%` : v.toFixed(3)
}

export default function Backtests() {
  const { data: runs, isLoading, error } = useBacktestRuns()
  const [selectedId, setSelectedId] = useState<number | null>(null)

  const selected = runs?.find(r => r.id === selectedId)

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-bold">Backtest Results</h2>

      {error && <ErrorBanner message="Backend unavailable." />}
      {isLoading && <LoadingSpinner message="Loading backtest runs..." />}

      {!isLoading && !error && !runs?.length && (
        <div className="text-center text-slate-500 py-20">
          <p className="text-5xl mb-4">📈</p>
          <p className="text-sm">
            No backtest runs yet. Run the backtester from the CLI to generate results.
          </p>
        </div>
      )}

      {!!runs?.length && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="space-y-2">
            {runs.map(r => (
              <button
                key={r.id}
                onClick={() => setSelectedId(r.id)}
                className={`w-full text-left bg-slate-800 rounded-xl p-3 border transition-colors ${
                  selectedId === r.id
                    ? 'border-emerald-500'
                    : 'border-slate-700 hover:border-slate-600'
                }`}
              >
                <p className="text-sm font-semibold">Run #{r.id}</p>
                <p className="text-xs text-slate-400 mt-0.5">
                  {r.date_range_start} → {r.date_range_end}
                </p>
                {r.results?.cagr != null && (
                  <p
                    className={`text-xs font-mono mt-1 ${
                      (r.results.cagr ?? 0) >= 0 ? 'text-emerald-400' : 'text-red-400'
                    }`}
                  >
                    CAGR {fmt(r.results.cagr, true)}
                  </p>
                )}
              </button>
            ))}
          </div>

          <div className="lg:col-span-2">
            {selected ? (
              <div className="bg-slate-800 rounded-xl p-4 border border-slate-700 space-y-4">
                <h3 className="font-semibold">
                  Run #{selected.id} — {selected.date_range_start} to {selected.date_range_end}
                </h3>
                <div className="grid grid-cols-3 gap-3 text-sm">
                  {(
                    [
                      ['CAGR', fmt(selected.results?.cagr, true)],
                      ['Sharpe', fmt(selected.results?.sharpe)],
                      ['Max Drawdown', fmt(selected.results?.max_drawdown, true)],
                      ['Win Rate', fmt(selected.results?.win_rate, true)],
                      ['# Trades', String(selected.results?.num_trades ?? '—')],
                      ['Total Return', fmt(selected.results?.total_return, true)],
                    ] as [string, string][]
                  ).map(([label, value]) => (
                    <div key={label} className="bg-slate-700/50 rounded-lg p-3">
                      <p className="text-slate-400 text-xs">{label}</p>
                      <p className="font-mono font-bold mt-1">{value}</p>
                    </div>
                  ))}
                </div>
                <EquityCurveChart data={[]} />
              </div>
            ) : (
              <div className="h-full flex items-center justify-center text-slate-500 text-sm">
                Select a run to view details
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
