import { useQuery } from '@tanstack/react-query'
import { apiClient } from './client'
import type { Portfolio, Position, Signal, Decision, Trade, BacktestRun, Instrument } from './types'

export const usePortfolio = () =>
  useQuery<Portfolio>({
    queryKey: ['portfolio'],
    queryFn: () => apiClient.get<Portfolio>('/portfolio/summary').then(r => r.data),
    retry: 1,
  })

export const usePositions = () =>
  useQuery<Position[]>({
    queryKey: ['positions'],
    queryFn: () => apiClient.get<Position[]>('/portfolio/positions').then(r => r.data),
    retry: 1,
  })

export const useSignals = () =>
  useQuery<Signal[]>({
    queryKey: ['signals', 'today'],
    queryFn: () => apiClient.get<Signal[]>('/signals/today').then(r => r.data),
    retry: 1,
  })

export const useDecisions = () =>
  useQuery<Decision[]>({
    queryKey: ['decisions', 'today'],
    queryFn: () => apiClient.get<Decision[]>('/decisions/today').then(r => r.data),
    retry: 1,
  })

export const useTrades = (symbol?: string) =>
  useQuery<Trade[]>({
    queryKey: ['trades', symbol ?? 'all'],
    queryFn: () =>
      apiClient.get<Trade[]>('/trades/', { params: symbol ? { symbol } : {} }).then(r => r.data),
    retry: 1,
  })

export const useBacktestRuns = () =>
  useQuery<BacktestRun[]>({
    queryKey: ['backtests'],
    queryFn: () => apiClient.get<BacktestRun[]>('/backtests/').then(r => r.data),
    retry: 1,
  })

export const useInstruments = () =>
  useQuery<Instrument[]>({
    queryKey: ['instruments'],
    queryFn: () => apiClient.get<Instrument[]>('/instruments/').then(r => r.data),
    retry: 1,
  })
