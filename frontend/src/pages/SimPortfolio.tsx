import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Treemap, Tooltip, ResponsiveContainer } from 'recharts';
import {
  getAccount,
  getPositions,
  closePosition,
  resetSimulation,
  aiSuggest,
  aiBuild,
  buyStock,
  sellStock,
} from '../api/simulation';

interface AccountData {
  cash: number;
  equity: number;
  total_value: number;
  return_pct: number;
  pnl: number;
  trade_count: number;
}

interface Position {
  symbol: string;
  quantity: number;
  avg_entry_price: number;
  current_price: number;
  current_value: number;
  pnl: number;
  pnl_pct: number;
}

interface AiSuggestion {
  action: string;
  symbol: string;
  quantity: number;
  reason: string;
}

interface AiBuildResult {
  trades_executed: number;
  portfolio_after: unknown;
  message: string;
}

interface Toast {
  id: number;
  message: string;
  type: 'success' | 'error';
}

function heatColor(pnlPct: number): string {
  if (pnlPct > 0.05) return '#16a34a';
  if (pnlPct > 0.02) return '#22c55e';
  if (pnlPct > 0) return '#4ade80';
  if (pnlPct > -0.02) return '#f87171';
  if (pnlPct > -0.05) return '#ef4444';
  return '#dc2626';
}

function fmtMoney(v: number): string {
  return v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

let _toastId = 0;

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function TreemapContent(props: any) {
  const { x, y, width, height, name, pnlPct } = props as {
    x: number; y: number; width: number; height: number; name: string; pnlPct: number;
  };
  const color = heatColor(pnlPct ?? 0);
  const pct = typeof pnlPct === 'number' ? pnlPct * 100 : 0;
  const showLabel = width > 50 && height > 30;
  return (
    <g>
      <rect x={x} y={y} width={width} height={height} fill={color} stroke="#1e293b" strokeWidth={2} rx={4} />
      {showLabel && (
        <>
          <text x={x + width / 2} y={y + height / 2 - 6} textAnchor="middle" fill="#fff" fontSize={12} fontWeight="bold">
            {name}
          </text>
          <text x={x + width / 2} y={y + height / 2 + 10} textAnchor="middle" fill="#fff" fontSize={10} opacity={0.85}>
            {pct >= 0 ? '+' : ''}{pct.toFixed(1)}%
          </text>
        </>
      )}
    </g>
  );
}

export default function SimPortfolio() {
  const queryClient = useQueryClient();
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [suggestions, setSuggestions] = useState<AiSuggestion[]>([]);
  const [aiBuildResult, setAiBuildResult] = useState<AiBuildResult | null>(null);

  function addToast(message: string, type: 'success' | 'error') {
    const id = ++_toastId;
    setToasts(prev => [...prev, { id, message, type }]);
    setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), 4000);
  }

  function invalidate() {
    void queryClient.invalidateQueries({ queryKey: ['simulation-account'] });
    void queryClient.invalidateQueries({ queryKey: ['simulation-positions'] });
  }

  const { data: account, isLoading: accountLoading } = useQuery<AccountData>({
    queryKey: ['simulation-account'],
    queryFn: getAccount,
    refetchInterval: 3000,
  });

  const { data: positions = [], isLoading: positionsLoading } = useQuery<Position[]>({
    queryKey: ['simulation-positions'],
    queryFn: getPositions,
    refetchInterval: 5000,
  });

  const closeMutation = useMutation({
    mutationFn: (symbol: string) => closePosition(symbol),
    onSuccess: (_data, symbol) => {
      addToast(`Closed position: ${symbol}`, 'success');
      invalidate();
    },
    onError: () => addToast('Failed to close position.', 'error'),
  });

  const resetMutation = useMutation({
    mutationFn: resetSimulation,
    onSuccess: () => {
      addToast('Simulation reset to $100,000', 'success');
      setSuggestions([]);
      setAiBuildResult(null);
      invalidate();
    },
    onError: () => addToast('Reset failed.', 'error'),
  });

  const suggestMutation = useMutation({
    mutationFn: aiSuggest,
    onSuccess: (data: AiSuggestion[]) => {
      setSuggestions(data ?? []);
    },
    onError: () => addToast('AI suggest failed.', 'error'),
  });

  const buildMutation = useMutation({
    mutationFn: aiBuild,
    onSuccess: (result: AiBuildResult) => {
      setAiBuildResult(result);
      invalidate();
    },
    onError: () => addToast('AI build failed.', 'error'),
  });

  function executeSuggestion(s: AiSuggestion) {
    const action = s.action.toLowerCase();
    const side = action === 'sell' ? 'sell' : 'buy';
    // Use current_price from positions if available, else 0 (backend will handle)
    const pos = positions.find(p => p.symbol === s.symbol);
    const price = pos?.current_price ?? 0;
    const fn = side === 'buy' ? buyStock : sellStock;
    fn(s.symbol, s.quantity, price)
      .then(() => {
        addToast(`Executed ${side.toUpperCase()} ${s.quantity} ${s.symbol}`, 'success');
        invalidate();
      })
      .catch(() => addToast(`Failed to execute ${side} ${s.symbol}`, 'error'));
  }

  const treemapData = positions.map(p => ({
    name: p.symbol,
    size: p.current_value,
    pnlPct: p.pnl_pct,
  }));

  const pnlPositive = (account?.pnl ?? 0) >= 0;

  return (
    <div className="min-h-screen bg-slate-900 text-slate-100 p-4 font-mono">
      {/* Toast notifications */}
      <div className="fixed top-4 right-4 z-50 flex flex-col gap-2 pointer-events-none">
        {toasts.map(t => (
          <div
            key={t.id}
            className={`px-4 py-2 rounded-lg shadow-lg text-sm font-medium transition-all ${
              t.type === 'success'
                ? 'bg-emerald-700 text-white border border-emerald-500'
                : 'bg-red-700 text-white border border-red-500'
            }`}
          >
            {t.message}
          </div>
        ))}
      </div>

      {/* Page header */}
      <div className="mb-5">
        <h1 className="text-xl font-bold text-cyan-400">Sim Portfolio</h1>
        <p className="text-slate-400 text-xs mt-0.5">Paper trading account — simulated funds only</p>
      </div>

      {/* Section 1: Account Summary */}
      <div className="bg-slate-800 border border-slate-700 rounded-lg px-5 py-4 mb-5">
        {accountLoading ? (
          <div className="text-slate-400 text-sm">Loading account…</div>
        ) : (
          <div className="flex flex-wrap gap-6 items-center">
            <div>
              <div className="text-slate-400 text-xs mb-0.5">Cash</div>
              <div className="text-white font-bold text-lg">${account ? fmtMoney(account.cash) : '—'}</div>
            </div>
            <div>
              <div className="text-slate-400 text-xs mb-0.5">Portfolio Value</div>
              <div className="text-white font-bold text-lg">${account ? fmtMoney(account.total_value) : '—'}</div>
            </div>
            <div>
              <div className="text-slate-400 text-xs mb-0.5">Equity</div>
              <div className="text-white font-bold text-lg">${account ? fmtMoney(account.equity) : '—'}</div>
            </div>
            <div>
              <div className="text-slate-400 text-xs mb-0.5">Total P&amp;L</div>
              <div className={`font-bold text-lg ${pnlPositive ? 'text-emerald-400' : 'text-red-400'}`}>
                {account
                  ? `${pnlPositive ? '+' : ''}$${fmtMoney(account.pnl)}`
                  : '—'}
              </div>
            </div>
            <div>
              <div className="text-slate-400 text-xs mb-0.5">Return</div>
              <div className={`font-bold text-lg ${pnlPositive ? 'text-emerald-400' : 'text-red-400'}`}>
                {account
                  ? `${pnlPositive ? '+' : ''}${(account.return_pct * 100).toFixed(2)}%`
                  : '—'}
              </div>
            </div>
            <div>
              <div className="text-slate-400 text-xs mb-0.5">Trades</div>
              <div className="text-slate-200 font-bold text-lg">{account?.trade_count ?? '—'}</div>
            </div>
            <div className="ml-auto">
              <button
                onClick={() => resetMutation.mutate()}
                disabled={resetMutation.isPending}
                className="text-xs px-3 py-1.5 bg-slate-600 hover:bg-slate-500 disabled:opacity-50 text-white rounded font-bold border border-slate-500"
              >
                {resetMutation.isPending ? 'Resetting…' : '↺ Reset'}
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Section 2: Portfolio Heatmap */}
      {positions.length > 0 && (
        <div className="bg-slate-800 border border-slate-700 rounded-lg p-4 mb-5">
          <div className="text-slate-300 font-bold mb-3 text-sm">Portfolio Heatmap</div>
          <ResponsiveContainer width="100%" height={200}>
            <Treemap
              data={treemapData}
              dataKey="size"
              nameKey="name"
              content={<TreemapContent />}
            >
              <Tooltip
                content={({ payload }) => {
                  if (!payload || !payload[0]) return null;
                  const d = payload[0].payload as { name: string; size: number; pnlPct: number };
                  return (
                    <div className="bg-slate-900 border border-slate-600 rounded px-3 py-2 text-xs">
                      <div className="font-bold text-white">{d.name}</div>
                      <div className="text-slate-300">Value: ${fmtMoney(d.size)}</div>
                      <div className={d.pnlPct >= 0 ? 'text-emerald-400' : 'text-red-400'}>
                        P&L: {d.pnlPct >= 0 ? '+' : ''}{(d.pnlPct * 100).toFixed(2)}%
                      </div>
                    </div>
                  );
                }}
              />
            </Treemap>
          </ResponsiveContainer>
        </div>
      )}

      {/* Section 3: Positions Table */}
      <div className="bg-slate-800 border border-slate-700 rounded-lg mb-5 overflow-auto">
        <div className="px-4 py-2 border-b border-slate-700 text-slate-300 font-bold text-sm">
          Open Positions
        </div>
        {positionsLoading ? (
          <div className="p-4 text-slate-400 text-sm">Loading positions…</div>
        ) : positions.length === 0 ? (
          <div className="p-4 text-slate-500 text-sm">No open positions. Use the Live Market page to trade.</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-slate-400 text-xs border-b border-slate-700">
                <th className="px-3 py-2 text-left">Symbol</th>
                <th className="px-3 py-2 text-right">Qty</th>
                <th className="px-3 py-2 text-right">Avg Cost</th>
                <th className="px-3 py-2 text-right">Current Price</th>
                <th className="px-3 py-2 text-right">Value</th>
                <th className="px-3 py-2 text-right">P&amp;L $</th>
                <th className="px-3 py-2 text-right">P&amp;L %</th>
                <th className="px-3 py-2 text-center">Actions</th>
              </tr>
            </thead>
            <tbody>
              {positions.map(pos => {
                const posPositive = pos.pnl >= 0;
                const pnlClass = posPositive ? 'text-emerald-400' : 'text-red-400';
                return (
                  <tr
                    key={pos.symbol}
                    className={`border-b border-slate-700/50 hover:bg-slate-700/30 ${
                      posPositive ? 'bg-emerald-950/10' : 'bg-red-950/10'
                    }`}
                  >
                    <td className="px-3 py-2 font-bold text-white">{pos.symbol}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-slate-200">{pos.quantity}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-slate-300">
                      ${fmtMoney(pos.avg_entry_price)}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums text-slate-200">
                      ${fmtMoney(pos.current_price)}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums text-slate-200">
                      ${fmtMoney(pos.current_value)}
                    </td>
                    <td className={`px-3 py-2 text-right tabular-nums font-medium ${pnlClass}`}>
                      {posPositive ? '+' : ''}${fmtMoney(pos.pnl)}
                    </td>
                    <td className={`px-3 py-2 text-right tabular-nums font-medium ${pnlClass}`}>
                      {posPositive ? '+' : ''}{(pos.pnl_pct * 100).toFixed(2)}%
                    </td>
                    <td className="px-3 py-2 text-center">
                      <button
                        onClick={() => closeMutation.mutate(pos.symbol)}
                        disabled={closeMutation.isPending}
                        className="text-xs px-3 py-1 bg-slate-600 hover:bg-red-700 disabled:opacity-50 text-white rounded border border-slate-500"
                      >
                        Close
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* Section 4: AI Assistant */}
      <div className="bg-slate-800 border border-slate-700 rounded-lg p-4">
        <div className="text-slate-300 font-bold mb-3 text-sm">🤖 AI Assistant</div>

        <div className="flex gap-3 mb-4">
          <button
            onClick={() => suggestMutation.mutate()}
            disabled={suggestMutation.isPending}
            className="text-sm px-4 py-2 bg-cyan-700 hover:bg-cyan-600 disabled:opacity-50 text-white rounded font-bold"
          >
            {suggestMutation.isPending ? 'Analyzing…' : '💡 Suggest Trades'}
          </button>
          <button
            onClick={() => buildMutation.mutate()}
            disabled={buildMutation.isPending}
            className="text-sm px-4 py-2 bg-emerald-700 hover:bg-emerald-600 disabled:opacity-50 text-white rounded font-bold"
          >
            {buildMutation.isPending ? 'Building…' : '🏗 Build Portfolio'}
          </button>
        </div>

        {/* AI Build Result */}
        {aiBuildResult && (
          <div className="bg-slate-700 border border-emerald-700/50 rounded-lg p-4 mb-4">
            <div className="text-emerald-400 font-bold mb-1 text-sm">
              Portfolio Built — {aiBuildResult.trades_executed} trade(s) executed
            </div>
            <p className="text-slate-300 text-sm leading-relaxed">{aiBuildResult.message}</p>
          </div>
        )}

        {/* Suggestions */}
        {suggestions.length > 0 && (
          <div>
            <div className="text-slate-400 text-xs mb-2">AI Suggestions</div>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {suggestions.map((s, i) => (
                <div key={i} className="bg-slate-700 rounded-lg p-3">
                  <div className="flex justify-between items-start">
                    <span className="font-bold text-emerald-400">
                      {s.action.toUpperCase()} {s.symbol}
                    </span>
                    <span className="text-slate-400 text-sm">qty: {s.quantity}</span>
                  </div>
                  <p className="text-slate-300 text-sm mt-1">{s.reason}</p>
                  <button
                    onClick={() => executeSuggestion(s)}
                    className="mt-2 text-xs px-3 py-1 bg-emerald-700 hover:bg-emerald-600 rounded text-white"
                  >
                    Execute
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {suggestions.length === 0 && !aiBuildResult && (
          <div className="text-slate-500 text-sm">
            Click "Suggest Trades" to get AI-powered trade recommendations, or "Build Portfolio" to let the AI construct a full portfolio for you.
          </div>
        )}
      </div>
    </div>
  );
}
