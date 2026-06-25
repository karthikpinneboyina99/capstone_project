import LoadingSpinner from '../components/LoadingSpinner'
import ErrorBanner from '../components/ErrorBanner'
import EquityCurveChart from '../components/EquityCurveChart'
import { usePortfolio, usePositions } from '../api/queries'

export default function Dashboard() {
  const { data: portfolio, isLoading: pLoading, error: pError } = usePortfolio()
  const { data: positions, isLoading: posLoading } = usePositions()

  const pnl = portfolio?.day_pnl ?? 0
  const pnlColor = pnl >= 0 ? 'text-emerald-400' : 'text-red-400'
  const pnlPrefix = pnl >= 0 ? '+' : ''

  // Build an equity curve from the portfolio snapshot.
  // When there is only one data point the chart renders a single dot — acceptable
  // until the backend accumulates a proper history table.
  const equityData = portfolio
    ? [{ date: portfolio.as_of_date ?? 'Today', value: portfolio.total_value }]
    : []

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-bold">Dashboard</h2>

      {pError && (
        <ErrorBanner message="Could not reach the backend. Showing empty state until it's available." />
      )}

      <div className="grid grid-cols-3 gap-4">
        {(['Total Value', 'Cash', 'Day P&L'] as const).map((label, i) => (
          <div key={label} className="bg-slate-800 rounded-xl p-4 border border-slate-700">
            <p className="text-slate-400 text-xs mb-1">{label}</p>
            {pLoading ? (
              <LoadingSpinner message="" />
            ) : (
              <p className={`text-2xl font-bold font-mono ${i === 2 ? pnlColor : ''}`}>
                {i === 0
                  ? `$${(portfolio?.total_value ?? 0).toLocaleString()}`
                  : i === 1
                  ? `$${(portfolio?.cash ?? 0).toLocaleString()}`
                  : `${pnlPrefix}$${Math.abs(pnl).toLocaleString()}`}
              </p>
            )}
          </div>
        ))}
      </div>

      <div className="bg-slate-800 rounded-xl p-4 border border-slate-700">
        <h3 className="text-sm font-semibold mb-3 text-slate-300">Equity Curve</h3>
        <EquityCurveChart data={equityData} />
      </div>

      <div className="bg-slate-800 rounded-xl p-4 border border-slate-700">
        <h3 className="text-sm font-semibold mb-3 text-slate-300">Open Positions</h3>
        {posLoading ? (
          <LoadingSpinner message="Loading positions..." />
        ) : !positions?.length ? (
          <p className="text-slate-500 text-sm py-4 text-center">No open positions.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-slate-400 text-xs border-b border-slate-700">
                {['Symbol', 'Qty', 'Avg Entry', 'Current', 'P&L'].map(h => (
                  <th key={h} className={`py-2 ${h === 'Symbol' ? 'text-left' : 'text-right'}`}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {positions.map(pos => {
                const curr = pos.current_price ?? pos.avg_entry_price
                const rowPnl = (curr - pos.avg_entry_price) * pos.quantity
                return (
                  <tr key={pos.id} className="border-b border-slate-700/40 hover:bg-slate-700/20">
                    <td className="py-2 font-semibold">{pos.symbol}</td>
                    <td className="py-2 text-right font-mono">{pos.quantity}</td>
                    <td className="py-2 text-right font-mono">${pos.avg_entry_price.toFixed(2)}</td>
                    <td className="py-2 text-right font-mono">${curr.toFixed(2)}</td>
                    <td
                      className={`py-2 text-right font-mono ${rowPnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}
                    >
                      {rowPnl >= 0 ? '+' : ''}${rowPnl.toFixed(2)}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
