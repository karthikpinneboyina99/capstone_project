import { apiClient as api } from './client';

export const getAccount = () => api.get('/simulation/account').then(r => r.data);
export const getPositions = () => api.get('/simulation/positions').then(r => r.data);
export const getTrades = () => api.get('/simulation/trades').then(r => r.data);
export const buyStock = (symbol: string, quantity: number, price: number) =>
  api.post('/simulation/buy', { symbol, quantity, price }).then(r => r.data);
export const sellStock = (symbol: string, quantity: number, price: number) =>
  api.post('/simulation/sell', { symbol, quantity, price }).then(r => r.data);
export const closePosition = (symbol: string) =>
  api.post(`/simulation/close/${symbol}`).then(r => r.data);
export const resetSimulation = () => api.post('/simulation/reset').then(r => r.data);
export const aiSuggest = () => api.post('/simulation/ai/suggest').then(r => r.data);
export const aiBuild = () => api.post('/simulation/ai/build').then(r => r.data);
