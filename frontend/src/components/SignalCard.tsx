import { useState } from 'react'
import type { Decision } from '../api/types'

const ACTION_STYLES: Record<Decision['action'], string> = {
  buy: 'bg-emerald-600 text-white',
  sell: 'bg-red-600 text-white',
  hold: 'bg-slate-600 text-white',
}

export default function SignalCard({ decision }: { decision: Decision }) {
  const [expanded, setExpanded] = useState(false)
  const score = decision.signal_score ?? 0
  const scoreColor =
    score > 0.2 ? 'text-emerald-400' : score < -0.2 ? 'text-red-400' : 'text-slate-400'

  return (
    <div className="bg-slate-800 rounded-xl p-4 border border-slate-700 hover:border-slate-600 transition-colors">
      <div className="flex items-center justify-between mb-3">
        <span className="font-bold text-lg">{decision.symbol}</span>
        <span
          className={`text-xs px-2 py-1 rounded-full font-semibold uppercase ${ACTION_STYLES[decision.action]}`}
        >
          {decision.action}
        </span>
      </div>

      <div className="grid grid-cols-3 gap-2 text-sm mb-3">
        <div>
          <p className="text-slate-400 text-xs">Signal</p>
          <p className={`font-mono font-bold ${scoreColor}`}>{(score * 100).toFixed(1)}</p>
        </div>
        <div>
          <p className="text-slate-400 text-xs">Confidence</p>
          <p className="font-mono font-bold">{(decision.confidence * 100).toFixed(0)}%</p>
        </div>
        <div>
          <p className="text-slate-400 text-xs">Size</p>
          <p className="font-mono font-bold">{(decision.position_size_pct * 100).toFixed(0)}%</p>
        </div>
      </div>

      {(decision.risk_flags?.length ?? 0) > 0 && (
        <div className="flex flex-wrap gap-1 mb-2">
          {(decision.risk_flags ?? []).map(flag => (
            <span
              key={flag}
              className="text-xs bg-amber-900/50 text-amber-300 rounded px-2 py-0.5"
            >
              {flag}
            </span>
          ))}
        </div>
      )}

      <button
        onClick={() => setExpanded(!expanded)}
        className="text-xs text-slate-400 hover:text-slate-200 transition-colors"
      >
        {expanded ? '▲ Hide rationale' : '▼ Show rationale'}
      </button>

      {expanded && (
        <p className="mt-2 text-xs text-slate-300 leading-relaxed border-t border-slate-700 pt-2">
          {decision.rationale}
        </p>
      )}
    </div>
  )
}
