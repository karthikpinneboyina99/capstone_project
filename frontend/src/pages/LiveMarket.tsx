import { useEffect, useRef, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  getAccount,
  buyStock,
  sellStock,
  aiBuild,
} from '../api/simulation';

const WATCHLIST = ['AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN', 'META', 'TSLA', 'SPY', 'QQQ', 'BRK.B'];
const SPARK_CHARS = '▁▂▃▄▅▆▇█';
const BIG_MOVE_PCT = 1.5;
const EVENT_MAX = 12;
const API_BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? 'http://localhost:8000';

interface TickerData {
  price: number;
  prev: number;
  volume: number;
  bid: number;
  ask: number;
  history: number[];
}

interface PriceEvent {
  tick: number;
  ts: string;
  prices: Record<string, TickerData>;
}

interface EventLog {
  ts: string;
  symbol: string;
  pct: number;
  price: number;
}

interface OrderModal {
  symbol: string;
  side: 'buy' | 'sell';
  price: number;
}

interface AccountData {
  cash: number;
  equity: number;
  total_value: number;
  return_pct: number;
  pnl: number;
  trade_count: number;
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

function spark(prices: number[]): string {
  if (prices.length < 2) return '─';
  const mn = Math.min(...prices);
  const mx = Math.max(...prices);
  const rng = mx - mn || 1;
  const n = SPARK_CHARS.length - 1;
  return prices
    .map(p => SPARK_CHARS[Math.min(Math.floor(((p - mn) / rng) * n), n)])
    .join('');
}

function fmtVol(v: number): string {
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `${(v / 1_000).toFixed(0)}K`;
  return String(v);
}

function pctColor(pct: number): string {
  if (pct > 0.05) return 'text-emerald-400';
  if (pct < -0.05) return 'text-red-400';
  return 'text-slate-400';
}

function arrow(pct: number): string {
  if (pct > 0.05) return '↑';
  if (pct < -0.05) return '↓';
  return '→';
}

function fmtMoney(v: number): string {
  return v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export default function LiveMarket() {
  const [data, setData] = useState<PriceEvent | null>(null);
  const [events, setEvents] = useState<EventLog[]>([]);
  const [connected, setConnected] = useState(false);
  const esRef = useRef<EventSource | null>(null);

  const [orderModal, setOrderModal] = useState<OrderModal | null>(null);
  const [qty, setQty] = useState(1);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [aiBuildModal, setAiBuildModal] = useState<AiBuildResult | null>(null);
  const toastIdRef = useRef(0);

  const queryClient = useQueryClient();

  const { data: account } = useQuery<AccountData>({
    queryKey: ['simulation-account'],
    queryFn: getAccount,
    refetchInterval: 3000,
  });

  const buyMutation = useMutation({
    mutationFn: ({ symbol, quantity, price }: { symbol: string; quantity: number; price: number }) =>
      buyStock(symbol, quantity, price),
    onSuccess: (_data, variables) => {
      addToast(`Bought ${variables.quantity} ${variables.symbol} @ $${variables.price.toFixed(2)}`, 'success');
      void queryClient.invalidateQueries({ queryKey: ['simulation-account'] });
    },
    onError: () => addToast('Order failed. Check your cash balance.', 'error'),
  });

  const sellMutation = useMutation({
    mutationFn: ({ symbol, quantity, price }: { symbol: string; quantity: number; price: number }) =>
      sellStock(symbol, quantity, price),
    onSuccess: (_data, variables) => {
      addToast(`Sold ${variables.quantity} ${variables.symbol} @ $${variables.price.toFixed(2)}`, 'success');
      void queryClient.invalidateQueries({ queryKey: ['simulation-account'] });
    },
    onError: () => addToast('Order failed. Check your positions.', 'error'),
  });

  const aiBuildMutation = useMutation({
    mutationFn: aiBuild,
    onSuccess: (result: AiBuildResult) => {
      setAiBuildModal(result);
      void queryClient.invalidateQueries({ queryKey: ['simulation-account'] });
    },
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    onError: (err: any) => {
      if (err?.response?.status === 429) {
        addToast('Cerebras is busy (rate limit). Wait 30 s and try again.', 'error');
      } else {
        const msg = err?.response?.data?.detail || 'AI build failed.';
        addToast(msg, 'error');
      }
    },
  });

  function addToast(message: string, type: 'success' | 'error') {
    const id = ++toastIdRef.current;
    setToasts(prev => [...prev, { id, message, type }]);
    setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), 4000);
  }

  function handleOrder() {
    if (!orderModal) return;
    const payload = { symbol: orderModal.symbol, quantity: qty, price: orderModal.price };
    if (orderModal.side === 'buy') {
      buyMutation.mutate(payload);
    } else {
      sellMutation.mutate(payload);
    }
    setOrderModal(null);
    setQty(1);
  }

  useEffect(() => {
    const es = new EventSource(`${API_BASE}/stream/prices`);
    esRef.current = es;

    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);

    es.onmessage = (e: MessageEvent<string>) => {
      const payload: PriceEvent = JSON.parse(e.data) as PriceEvent;
      setData(payload);

      setEvents(prev => {
        const newEvents = [...prev];
        for (const sym of WATCHLIST) {
          const t = payload.prices[sym];
          if (!t) continue;
          const pct = t.prev ? ((t.price - t.prev) / t.prev) * 100 : 0;
          if (Math.abs(pct) >= BIG_MOVE_PCT) {
            newEvents.unshift({ ts: payload.ts, symbol: sym, pct, price: t.price });
          }
        }
        return newEvents.slice(0, EVENT_MAX);
      });
    };

    return () => {
      es.close();
      setConnected(false);
    };
  }, []);

  // Session summary
  const pcts: Record<string, number> = {};
  const vols: Record<string, number> = {};
  if (data) {
    for (const sym of WATCHLIST) {
      const t = data.prices[sym];
      if (t && t.prev) {
        pcts[sym] = ((t.price - t.prev) / t.prev) * 100;
        vols[sym] = t.volume;
      }
    }
  }
  const gainer = Object.entries(pcts).sort((a, b) => b[1] - a[1])[0];
  const loser = Object.entries(pcts).sort((a, b) => a[1] - b[1])[0];
  const active = Object.entries(vols).sort((a, b) => b[1] - a[1])[0];

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

      {/* Header */}
      <div className="flex items-center justify-between mb-4 px-2">
        <div>
          <span className="text-cyan-400 font-bold text-lg">AI Trading Workstation</span>
          <span className="text-slate-500 text-sm ml-3">SimulatorProvider &middot; GBM offline</span>
        </div>
        <div className="flex items-center gap-3">
          {data && (
            <span className="text-slate-400 text-sm">
              Tick #{data.tick} &middot; {data.ts}
            </span>
          )}
          <span
            className={`text-xs px-2 py-0.5 rounded-full ${
              connected ? 'bg-emerald-900 text-emerald-400' : 'bg-red-900 text-red-400'
            }`}
          >
            {connected ? '● LIVE' : '○ connecting…'}
          </span>
        </div>
      </div>

      {/* Portfolio summary strip */}
      <div className="bg-slate-800 border border-slate-700 rounded-lg px-4 py-3 mb-4 flex flex-wrap items-center gap-4 text-sm">
        <div className="flex gap-1 items-center">
          <span className="text-slate-400">Cash:</span>
          <span className="text-white font-bold">
            ${account ? fmtMoney(account.cash) : '—'}
          </span>
        </div>
        <div className="text-slate-600">|</div>
        <div className="flex gap-1 items-center">
          <span className="text-slate-400">Portfolio Value:</span>
          <span className="text-white font-bold">
            ${account ? fmtMoney(account.total_value) : '—'}
          </span>
        </div>
        <div className="text-slate-600">|</div>
        <div className="flex gap-1 items-center">
          <span className="text-slate-400">P&amp;L:</span>
          <span className={`font-bold ${pnlPositive ? 'text-emerald-400' : 'text-red-400'}`}>
            {account
              ? `${pnlPositive ? '+' : ''}$${fmtMoney(account.pnl)} (${pnlPositive ? '+' : ''}${(account.return_pct * 100).toFixed(2)}%)`
              : '—'}
          </span>
        </div>
        <div className="ml-auto flex gap-2">
          <button
            onClick={() => aiBuildMutation.mutate()}
            disabled={aiBuildMutation.isPending}
            className="text-xs px-3 py-1.5 bg-cyan-700 hover:bg-cyan-600 disabled:opacity-50 text-white rounded font-bold"
          >
            {aiBuildMutation.isPending ? 'Building…' : '🤖 Let AI Build Portfolio'}
          </button>
        </div>
      </div>

      {/* Price table */}
      <div className="bg-slate-800 rounded-lg border border-slate-700 mb-4 overflow-auto">
        <div className="px-4 py-2 border-b border-slate-700 text-slate-300 font-bold">
          Live Prices &mdash; {WATCHLIST.length} Symbols
        </div>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-slate-400 text-xs border-b border-slate-700">
              <th className="px-2 py-2 w-6"></th>
              <th className="px-2 py-2 text-left">Symbol</th>
              <th className="px-3 py-2 text-right">Price</th>
              <th className="px-3 py-2 text-right">Chg $</th>
              <th className="px-3 py-2 text-right">Chg %</th>
              <th className="px-3 py-2 text-left">&#8211;&#8211; last 18 bars &#8211;&#8211;</th>
              <th className="px-3 py-2 text-right">Volume</th>
              <th className="px-3 py-2 text-right">Bid</th>
              <th className="px-3 py-2 text-right">Ask</th>
              <th className="px-3 py-2 text-right">Spread</th>
              <th className="px-3 py-2 text-center">Order</th>
            </tr>
          </thead>
          <tbody>
            {WATCHLIST.map(sym => {
              const t = data?.prices[sym];
              const px = t?.price ?? 0;
              const prev = t?.prev ?? px;
              const chg = px - prev;
              const pct = prev ? (chg / prev) * 100 : 0;
              const vol = t?.volume ?? 0;
              const bid = t?.bid ?? px;
              const ask = t?.ask ?? px;
              const hist = t?.history ?? [];
              const col = pctColor(pct);

              return (
                <tr key={sym} className="border-b border-slate-700/50 hover:bg-slate-700/30">
                  <td className={`px-2 py-1.5 text-center font-bold ${col}`}>{arrow(pct)}</td>
                  <td className={`px-2 py-1.5 font-bold ${col}`}>{sym}</td>
                  <td className={`px-3 py-1.5 text-right tabular-nums ${col}`}>
                    {px
                      ? `$${px.toLocaleString('en-US', {
                          minimumFractionDigits: 2,
                          maximumFractionDigits: 2,
                        })}`
                      : '—'}
                  </td>
                  <td className={`px-3 py-1.5 text-right tabular-nums ${col}`}>
                    {chg >= 0 ? '+' : ''}
                    {chg.toFixed(2)}
                  </td>
                  <td className={`px-3 py-1.5 text-right tabular-nums ${col}`}>
                    {pct >= 0 ? '+' : ''}
                    {pct.toFixed(2)}%
                  </td>
                  <td className={`px-3 py-1.5 text-left tracking-wide ${col}`}>
                    <span className="opacity-80">{spark(hist)}</span>
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-slate-400">
                    {fmtVol(vol)}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-slate-400">
                    ${bid.toFixed(2)}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-slate-400">
                    ${ask.toFixed(2)}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-slate-400">
                    {(ask - bid).toFixed(3)}
                  </td>
                  <td className="px-2 py-1.5">
                    <div className="flex gap-1">
                      <button
                        onClick={() => { setOrderModal({ symbol: sym, side: 'buy', price: px }); setQty(1); }}
                        className="text-xs px-2 py-0.5 bg-emerald-700 hover:bg-emerald-600 text-white rounded"
                      >
                        Buy
                      </button>
                      <button
                        onClick={() => { setOrderModal({ symbol: sym, side: 'sell', price: px }); setQty(1); }}
                        className="text-xs px-2 py-0.5 bg-red-700 hover:bg-red-600 text-white rounded"
                      >
                        Sell
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Bottom row: event log + session summary */}
      <div className="grid grid-cols-4 gap-4">
        {/* Event log */}
        <div className="col-span-3 bg-slate-800 rounded-lg border border-yellow-700/50">
          <div className="px-4 py-2 border-b border-yellow-700/50 text-yellow-400 font-bold text-sm">
            &#9889; Event Log
          </div>
          <div className="p-3 space-y-0.5 min-h-32">
            {events.length === 0 && (
              <div className="text-slate-500 text-xs">
                Watching for moves &gt;{BIG_MOVE_PCT}%&hellip;
              </div>
            )}
            {events.map((ev, i) => (
              <div key={i} className="text-xs flex gap-3">
                <span className="text-slate-500">{ev.ts}</span>
                <span className={ev.pct > 0 ? 'text-emerald-400' : 'text-red-400'}>
                  {ev.pct > 0 ? '↑' : '↓'} {ev.symbol.padEnd(6)}
                </span>
                <span className={ev.pct > 0 ? 'text-emerald-400' : 'text-red-400'}>
                  {Math.abs(ev.pct) >= 3 ? '⚡' : ev.pct > 0 ? '📈' : '📉'}{' '}
                  {ev.pct >= 0 ? '+' : ''}
                  {ev.pct.toFixed(2)}% ${ev.price.toFixed(2)}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Session summary */}
        <div className="bg-slate-800 rounded-lg border border-slate-600">
          <div className="px-4 py-2 border-b border-slate-600 text-slate-200 font-bold text-sm">
            Session Summary
          </div>
          <div className="p-4 space-y-3 text-sm">
            <div>
              <div className="text-slate-500 text-xs">Top Gainer</div>
              {gainer ? (
                <div className="text-emerald-400 font-bold">
                  {gainer[0]}&nbsp;&nbsp;+{gainer[1].toFixed(2)}%
                </div>
              ) : (
                <div className="text-slate-500">—</div>
              )}
            </div>
            <div>
              <div className="text-slate-500 text-xs">Top Loser</div>
              {loser ? (
                <div className="text-red-400 font-bold">
                  {loser[0]}&nbsp;&nbsp;{loser[1].toFixed(2)}%
                </div>
              ) : (
                <div className="text-slate-500">—</div>
              )}
            </div>
            <div>
              <div className="text-slate-500 text-xs">Most Active</div>
              {active ? (
                <div className="text-cyan-400 font-bold">
                  {active[0]}&nbsp;&nbsp;{fmtVol(active[1])}
                </div>
              ) : (
                <div className="text-slate-500">—</div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Order Modal */}
      {orderModal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
          <div className="bg-slate-800 border border-slate-600 rounded-xl p-6 w-80">
            <h3 className="text-lg font-bold mb-4">
              {orderModal.side === 'buy' ? '🟢 Buy' : '🔴 Sell'} {orderModal.symbol}
            </h3>
            <div className="mb-3">
              <label className="text-slate-400 text-sm">Price</label>
              <div className="text-white font-mono">${orderModal.price.toFixed(2)}</div>
            </div>
            <div className="mb-4">
              <label className="text-slate-400 text-sm">Quantity</label>
              <input
                type="number"
                min="1"
                value={qty}
                onChange={e => setQty(Math.max(1, Number(e.target.value)))}
                className="w-full bg-slate-700 border border-slate-500 rounded px-3 py-2 text-white mt-1"
              />
              <div className="text-slate-400 text-xs mt-1">
                Total: ${(qty * orderModal.price).toLocaleString('en-US', { minimumFractionDigits: 2 })}
              </div>
            </div>
            <div className="flex gap-2">
              <button
                onClick={handleOrder}
                className={`flex-1 py-2 rounded font-bold ${
                  orderModal.side === 'buy'
                    ? 'bg-emerald-600 hover:bg-emerald-500'
                    : 'bg-red-600 hover:bg-red-500'
                }`}
              >
                Confirm {orderModal.side === 'buy' ? 'Buy' : 'Sell'}
              </button>
              <button
                onClick={() => { setOrderModal(null); setQty(1); }}
                className="flex-1 py-2 rounded font-bold bg-slate-600 hover:bg-slate-500"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* AI Build Result Modal */}
      {aiBuildModal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
          <div className="bg-slate-800 border border-slate-600 rounded-xl p-6 w-96 max-w-full">
            <h3 className="text-lg font-bold mb-4 text-cyan-400">🤖 AI Portfolio Built</h3>
            <div className="mb-3 text-sm">
              <span className="text-slate-400">Trades executed: </span>
              <span className="text-white font-bold">{aiBuildModal.trades_executed}</span>
            </div>
            <div className="mb-4 bg-slate-700 rounded p-3 text-sm text-slate-200 leading-relaxed">
              {aiBuildModal.message}
            </div>
            <button
              onClick={() => setAiBuildModal(null)}
              className="w-full py-2 rounded font-bold bg-slate-600 hover:bg-slate-500"
            >
              Close
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
