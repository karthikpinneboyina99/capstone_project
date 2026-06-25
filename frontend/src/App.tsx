import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import LiveMarket from './pages/LiveMarket'
import Signals from './pages/Signals'
import Trades from './pages/Trades'
import Backtests from './pages/Backtests'
import Settings from './pages/Settings'
import SimPortfolio from './pages/SimPortfolio'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 30_000, gcTime: 5 * 60_000, retry: 1 },
  },
})

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Layout />}>
            <Route index element={<Dashboard />} />
            <Route path="market" element={<LiveMarket />} />
            <Route path="signals" element={<Signals />} />
            <Route path="trades" element={<Trades />} />
            <Route path="backtests" element={<Backtests />} />
            <Route path="settings" element={<Settings />} />
            <Route path="sim-portfolio" element={<SimPortfolio />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
