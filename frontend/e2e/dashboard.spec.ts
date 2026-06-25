import { test, expect } from '@playwright/test';

const API_BASE = 'http://localhost:8000';

// Mock data matching the app's type interfaces
const MOCK_PORTFOLIO = {
  cash: 95000,
  equity: 12500,
  total_value: 107500,
  as_of_date: '2024-06-01',
  mode: 'paper',
  day_pnl: 500,
};

const MOCK_POSITIONS = [
  {
    id: 1,
    instrument_id: 1,
    symbol: 'AAPL',
    quantity: 10,
    avg_entry_price: 185.5,
    mode: 'paper',
  },
];

// The Signals page uses useDecisions() — it renders Decision objects as SignalCards
const MOCK_DECISIONS = [
  {
    id: 1,
    symbol: 'AAPL',
    as_of_date: '2024-06-01',
    action: 'buy',
    position_size_pct: 0.8,
    confidence: 0.75,
    rationale: 'Strong momentum with RSI in healthy range.',
    risk_flags: ['sector rotation risk'],
    signal_score: 0.72,
  },
  {
    id: 2,
    symbol: 'MSFT',
    as_of_date: '2024-06-01',
    action: 'hold',
    position_size_pct: 0.5,
    confidence: 0.6,
    rationale: 'Neutral signal, holding position.',
    risk_flags: [],
    signal_score: -0.31,
  },
];

const MOCK_TRADES = [
  {
    id: 1,
    symbol: 'AAPL',
    side: 'buy',
    quantity: 10,
    price: 185.5,
    executed_at: '2024-06-01T14:35:00Z',
    mode: 'paper',
  },
];

const MOCK_BACKTESTS = [
  {
    id: 1,
    strategy_version: 'v1',
    date_range_start: '2023-01-01',
    date_range_end: '2023-12-31',
    results: { cagr: 0.18, sharpe: 1.4, max_drawdown: 0.08 },
  },
];

test.beforeEach(async ({ page }) => {
  // Mock all backend API routes before each test
  await page.route(`${API_BASE}/portfolio/summary`, async route => {
    await route.fulfill({ json: MOCK_PORTFOLIO });
  });
  await page.route(`${API_BASE}/portfolio/positions`, async route => {
    await route.fulfill({ json: MOCK_POSITIONS });
  });
  await page.route(`${API_BASE}/signals/today`, async route => {
    await route.fulfill({ json: [] });
  });
  await page.route(`${API_BASE}/decisions/today`, async route => {
    await route.fulfill({ json: MOCK_DECISIONS });
  });
  await page.route(`${API_BASE}/trades/`, async route => {
    await route.fulfill({ json: MOCK_TRADES });
  });
  await page.route(`${API_BASE}/backtests/`, async route => {
    await route.fulfill({ json: MOCK_BACKTESTS });
  });
  await page.route(`${API_BASE}/instruments/`, async route => {
    await route.fulfill({ json: [] });
  });
  await page.route(`${API_BASE}/health`, async route => {
    await route.fulfill({ json: { status: 'ok', mode: 'paper', environment: 'development' } });
  });
});

// ─── Dashboard page ──────────────────────────────────────────────────────────

test.describe('Dashboard page', () => {
  test('loads with correct page title', async ({ page }) => {
    await page.goto('/');
    await expect(page).toHaveTitle(/Trading/i);
  });

  test('shows portfolio total value formatted with dollar sign', async ({ page }) => {
    await page.goto('/');
    // total_value 107500 → "$107,500"
    await expect(page.getByText('$107,500')).toBeVisible({ timeout: 10_000 });
  });

  test('shows portfolio cash formatted with dollar sign', async ({ page }) => {
    await page.goto('/');
    // cash 95000 → "$95,000"
    await expect(page.getByText('$95,000')).toBeVisible({ timeout: 10_000 });
  });

  test('shows open positions with AAPL symbol', async ({ page }) => {
    await page.goto('/');
    // positions table shows AAPL
    await expect(page.getByText('AAPL').first()).toBeVisible({ timeout: 10_000 });
  });

  test('navigation sidebar is present with Signals and Trades links', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('link', { name: /Signals/i })).toBeVisible();
    await expect(page.getByRole('link', { name: /Trades/i })).toBeVisible();
  });

  test('shows paper trading warning banner', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText(/Paper trading only/i)).toBeVisible();
  });
});

// ─── Signals page ─────────────────────────────────────────────────────────────

test.describe('Signals page', () => {
  // The Signals page renders Decision objects (useDecisions) as SignalCards
  test('shows decision/signal cards with AAPL and MSFT', async ({ page }) => {
    await page.goto('/signals');
    await expect(page.getByText('AAPL')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText('MSFT')).toBeVisible({ timeout: 10_000 });
  });

  test('shows BUY action badge for AAPL decision', async ({ page }) => {
    await page.goto('/signals');
    await expect(page.getByText('buy', { exact: true })).toBeVisible({ timeout: 10_000 });
  });

  test('shows confidence percentage for decisions', async ({ page }) => {
    await page.goto('/signals');
    // confidence 0.75 → "75%"
    await expect(page.getByText('75%')).toBeVisible({ timeout: 10_000 });
  });

  test('shows filter buttons', async ({ page }) => {
    await page.goto('/signals');
    await expect(page.getByRole('button', { name: 'All' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Buy' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Sell' })).toBeVisible();
  });

  test('filter by buy shows only buy decisions', async ({ page }) => {
    await page.goto('/signals');
    await page.getByRole('button', { name: 'Buy' }).click();
    // AAPL is buy — should be visible
    await expect(page.getByText('AAPL')).toBeVisible({ timeout: 10_000 });
    // MSFT is hold — should be hidden after filter
    await expect(page.getByText('MSFT')).not.toBeVisible();
  });
});

// ─── Trades page ──────────────────────────────────────────────────────────────

test.describe('Trades page', () => {
  test('shows trade history table with AAPL', async ({ page }) => {
    await page.goto('/trades');
    await expect(page.getByText('AAPL')).toBeVisible({ timeout: 10_000 });
  });

  test('shows trade side (buy)', async ({ page }) => {
    await page.goto('/trades');
    await expect(page.getByText('buy')).toBeVisible({ timeout: 10_000 });
  });

  test('shows trade price formatted to 2 decimal places', async ({ page }) => {
    await page.goto('/trades');
    // price 185.5 → "$185.50"
    await expect(page.getByText('$185.50')).toBeVisible({ timeout: 10_000 });
  });

  test('shows mode badge', async ({ page }) => {
    await page.goto('/trades');
    await expect(page.getByText('v0.1.0 · paper mode')).toBeVisible({ timeout: 10_000 });
  });

  test('has symbol filter input', async ({ page }) => {
    await page.goto('/trades');
    await expect(page.getByPlaceholder('Filter by symbol…')).toBeVisible();
  });
});

// ─── Backtests page ───────────────────────────────────────────────────────────

test.describe('Backtests page', () => {
  test('shows backtest run list item', async ({ page }) => {
    await page.goto('/backtests');
    // Backtest list shows "Run #1"
    await expect(page.getByText('Run #1')).toBeVisible({ timeout: 10_000 });
  });

  test('shows date range for backtest run', async ({ page }) => {
    await page.goto('/backtests');
    // Date range: "2023-01-01 → 2023-12-31"
    await expect(page.getByText('2023-01-01')).toBeVisible({ timeout: 10_000 });
  });

  test('shows CAGR percentage in run list', async ({ page }) => {
    await page.goto('/backtests');
    // cagr 0.18 → "CAGR 18.00%"
    await expect(page.getByText(/18\.00%/)).toBeVisible({ timeout: 10_000 });
  });

  test('clicking a run shows detail panel', async ({ page }) => {
    await page.goto('/backtests');
    await page.getByText('Run #1').click();
    // Detail panel header appears
    await expect(page.getByText(/Run #1 — 2023-01-01/)).toBeVisible({ timeout: 5_000 });
  });

  test('detail panel shows Sharpe ratio', async ({ page }) => {
    await page.goto('/backtests');
    await page.getByText('Run #1').click();
    // sharpe 1.4 → "1.400"
    await expect(page.getByText('1.400')).toBeVisible({ timeout: 5_000 });
  });
});

// ─── Page routing ─────────────────────────────────────────────────────────────

test.describe('Page routing', () => {
  test('navigates between all pages without errors', async ({ page }) => {
    const routes = ['/', '/signals', '/trades', '/backtests'];
    for (const route of routes) {
      await page.goto(route);
      // No error boundary text
      await expect(page.getByText(/something went wrong/i)).not.toBeVisible();
      // No 404 in URL
      await expect(page).not.toHaveURL(/.*404.*/);
    }
  });

  test('nav links navigate to correct pages', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('link', { name: /Signals/i }).click();
    await expect(page).toHaveURL(/\/signals/);

    await page.getByRole('link', { name: /Trades/i }).click();
    await expect(page).toHaveURL(/\/trades/);

    await page.getByRole('link', { name: /Backtests/i }).click();
    await expect(page).toHaveURL(/\/backtests/);

    await page.getByRole('link', { name: /Dashboard/i }).click();
    await expect(page).toHaveURL(/\/$/);
  });
});
