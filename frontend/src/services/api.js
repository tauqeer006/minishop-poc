import axios from 'axios';

export const TOKEN_KEY = 'minishop_token';
export const USER_KEY = 'minishop_user';

const http = axios.create({
  baseURL: '/api/v1',
  headers: { 'X-Client-Version': '1.0.0' },
  timeout: 30000,
});

http.interceptors.request.use((config) => {
  try {
    const token = localStorage.getItem(TOKEN_KEY);
    if (token) config.headers.Authorization = `Bearer ${token}`;
  } catch { /* ignore */ }
  return config;
});

http.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err.response?.status === 401) {
      try {
        localStorage.removeItem(TOKEN_KEY);
        localStorage.removeItem(USER_KEY);
      } catch { /* ignore */ }
      window.dispatchEvent(new Event('minishop-unauthorized'));
    }
    return Promise.reject(err);
  }
);

/** Unwraps {success, data} envelope; returns data (with envelope extras under _meta). */
const unwrap = (res) => {
  const body = res.data;
  if (body && typeof body === 'object' && 'data' in body) {
    return { data: body.data, status: res.status, meta: body };
  }
  return { data: body, status: res.status, meta: body };
};

const call = (config) => http.request(config).then(unwrap);

export const getError = (err) => {
  const e = err?.response?.data?.error;
  if (e) {
    return {
      code: e.code || 'ERROR',
      message: e.message || 'Request failed',
      requestId: err.response.data.request_id,
      details: e.details,
      status: err.response.status,
    };
  }
  if (err?.response) {
    return { code: 'HTTP_' + err.response.status, message: err.response.statusText || 'Request failed', status: err.response.status };
  }
  return { code: 'NETWORK_ERROR', message: 'Network error. Please try again.', network: true };
};

export const api = {
  register: (body) => call({ method: 'post', url: '/auth/register', data: body }),
  login: (body) => call({ method: 'post', url: '/auth/login', data: body }),
  me: () => call({ url: '/auth/me' }),

  listProducts: (params) => call({ url: '/products', params }),
  getProduct: (id) => call({ url: `/products/${id}` }),
  createProduct: (body) => call({ method: 'post', url: '/products', data: body }),
  updateProduct: (id, body) => call({ method: 'patch', url: `/products/${id}`, data: body }),

  createOrder: (body, key) =>
    call({ method: 'post', url: '/orders', data: body, headers: { 'Idempotency-Key': key } }),
  listOrders: (params) => call({ url: '/orders', params }),
  getOrder: (id) => call({ url: `/orders/${id}` }),

  dashboard: () => call({ url: '/admin/dashboard' }),
  adminOrders: (params) => call({ url: '/admin/orders', params }),
  updateOrderStatus: (id, body) => call({ method: 'patch', url: `/admin/orders/${id}/status`, data: body }),
  events: (params) => call({ url: '/admin/events', params }),

  perfEndpoints: () => call({ url: '/admin/performance/endpoints' }),
  perfMetrics: (params) => call({ url: '/admin/performance/metrics', params }),
  perfBaselines: () => call({ url: '/admin/performance/baselines' }),
  perfIncidents: (params) => call({ url: '/admin/performance/incidents', params }),
  perfTrace: (id) => call({ url: `/admin/performance/traces/${id}` }),
};

export const money = (cents) => `$${((cents ?? 0) / 100).toFixed(2)}`;
export const ms = (v) => (v === null || v === undefined ? '—' : `${Math.round(v)} ms`);
export const fmtDate = (s) => (s ? new Date(s).toLocaleString() : '—');
export const uuid = () =>
  (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`);
