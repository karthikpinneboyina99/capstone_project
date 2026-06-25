import { useState } from 'react'
import SignalCard from '../components/SignalCard'
import LoadingSpinner from '../components/LoadingSpinner'
import ErrorBanner from '../components/ErrorBanner'
import { useDecisions } from '../api/queries'
import type { Decision } from '../api/types'

const FILTERS: Array<'all' | Decision['action']> = ['all', 'buy', 'sell', 'hold']

export default function Signals() {
  const { data: decisions, isLoading, error } = useDecisions()
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>('all')

  const visible = (decisions ?? []).filter(d => filter === 'all' || d.action === filter)

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h2 className="text-xl font-bold">Today's Signals</h2>
        <div className="flex gap-2">
          {FILTERS.map(f => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`text-xs px-3 py-1.5 rounded-full font-medium transition-colors ${
                filter === f
                  ? 'bg-emerald-600 text-white'
                  : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
              }`}
            >
              {f.charAt(0).toUpperCase() + f.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {error && <ErrorBanner message="Backend unavailable — signals not loaded." />}
      {isLoading && <LoadingSpinner message="Loading signals..." />}

      {!isLoading && !error && visible.length === 0 && (
        <div className="text-center text-slate-500 py-20">
          <p className="text-5xl mb-4">🎯</p>
          <p className="text-sm">
            No signals yet for today. Run the daily pipeline to generate them.
          </p>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {visible.map(d => (
          <SignalCard key={d.id} decision={d} />
        ))}
      </div>
    </div>
  )
}
