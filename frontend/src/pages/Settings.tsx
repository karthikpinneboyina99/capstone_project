import { useInstruments } from '../api/queries'
import LoadingSpinner from '../components/LoadingSpinner'

const RISK_PARAMS = [
  {
    label: 'Max Position Size',
    value: '10%',
    description: 'Maximum allocation per symbol (MAX_POSITION_PCT)',
  },
  {
    label: 'Max Positions',
    value: '8',
    description: 'Maximum concurrent open positions (MAX_POSITIONS)',
  },
  {
    label: 'Daily Loss Limit',
    value: '3%',
    description: 'Pause new buys if day loss exceeds this (DAILY_LOSS_LIMIT_PCT)',
  },
]

export default function Settings() {
  const { data: instruments, isLoading } = useInstruments()

  return (
    <div className="space-y-6 max-w-2xl">
      <div>
        <h2 className="text-xl font-bold">Settings</h2>
        <p className="text-slate-400 text-sm mt-1">
          Read-only view of runtime configuration. Change values in{' '}
          <code className="bg-slate-700 px-1.5 py-0.5 rounded text-xs">.env</code> and restart the
          backend.
        </p>
      </div>

      <div className="bg-slate-800 rounded-xl p-4 border border-slate-700">
        <h3 className="font-semibold mb-3 text-slate-300">Watchlist</h3>
        {isLoading ? (
          <LoadingSpinner />
        ) : instruments?.length ? (
          <div className="flex flex-wrap gap-2">
            {instruments.filter(i => i.is_active).map(i => (
              <span
                key={i.symbol}
                className="bg-slate-700 text-slate-200 text-sm rounded-lg px-3 py-1 font-mono border border-slate-600"
              >
                {i.symbol}
              </span>
            ))}
          </div>
        ) : (
          <p className="text-slate-500 text-sm">Backend offline — connect to see watchlist.</p>
        )}
      </div>

      <div className="bg-slate-800 rounded-xl p-4 border border-slate-700">
        <h3 className="font-semibold mb-3 text-slate-300">Risk Parameters</h3>
        <div className="divide-y divide-slate-700">
          {RISK_PARAMS.map(({ label, value, description }) => (
            <div key={label} className="flex items-center justify-between py-3 first:pt-0 last:pb-0">
              <div>
                <p className="text-sm font-medium">{label}</p>
                <p className="text-xs text-slate-400 mt-0.5">{description}</p>
              </div>
              <span className="font-mono text-emerald-400 font-bold ml-4 shrink-0">{value}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
