export interface Portfolio {
  cash: number
  equity: number
  total_value: number
  as_of_date: string
  mode?: string
  day_pnl?: number
}

export interface Position {
  id: number
  instrument_id?: number
  symbol: string
  quantity: number
  avg_entry_price: number
  current_price?: number
  unrealized_pnl?: number
  mode: 'paper' | 'backtest'
}

export interface Signal {
  id: number
  symbol: string
  as_of_date: string
  signal_score: number
  model_version?: string
}

export interface Decision {
  id: number
  symbol: string
  action: 'buy' | 'sell' | 'hold'
  position_size_pct: number
  confidence: number
  rationale: string
  risk_flags?: string[]
  as_of_date: string
  model_slug?: string
  signal_score?: number
}

export interface Trade {
  id: number
  symbol: string
  side: 'buy' | 'sell'
  quantity: number
  price: number
  executed_at: string
  mode: 'paper' | 'backtest'
  alpaca_order_id?: string
}

export interface BacktestRun {
  id: number
  date_range_start: string
  date_range_end: string
  strategy_version?: string
  results?: {
    cagr?: number
    sharpe?: number
    max_drawdown?: number
    win_rate?: number
    num_trades?: number
    total_return?: number
  }
  started_at?: string
  finished_at?: string
}

export interface Instrument {
  id: number
  symbol: string
  name?: string
  sector?: string
  is_active: boolean
}
