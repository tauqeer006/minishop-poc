import { useEffect, useState, useCallback } from 'react';
import { api, getError, ms, fmtDate } from '../../services/api.js';
import { Badge, ErrorBanner, Spinner } from '../../components/ui.jsx';
import LineChart from '../../components/LineChart.jsx';
import IncidentPanel from '../../components/IncidentPanel.jsx';

const STATUS_COLOR = { NORMAL: 'green', SUSPECT: 'yellow', DEGRADED: 'red', LEARNING: 'blue', INSUFFICIENT_DATA: 'gray' };
const LIFE = { OPEN: 'red', VERIFYING: 'yellow', RESOLVED: 'green', FAILED: 'red', ESCALATED: 'purple', CLOSED_NO_ACTION: 'gray' };

export default function AdminPerformance() {
  const [eps, setEps] = useState(null);
  const [incidents, setIncidents] = useState([]);
  const [sel, setSel] = useState(null);
  const [metrics, setMetrics] = useState([]);
  const [openInc, setOpenInc] = useState(null);
  const [error, setError] = useState(null);
  const [updated, setUpdated] = useState(null);

  const loadMetrics = useCallback((e) => {
    if (!e) return;
    api.perfMetrics({ endpoint: e.endpoint, method: e.http_method, limit: 60 })
      .then((r) => setMetrics(r.data.items)).catch((x) => setError(getError(x)));
  }, []);

  const refresh = useCallback(() => {
    Promise.all([api.perfEndpoints(), api.perfIncidents({ limit: 50 })])
      .then(([a, b]) => {
        setEps(a.data); setIncidents(b.data.items); setError(null); setUpdated(new Date());
        setSel((cur) => {
          if (!cur) return cur;
          const fresh = a.data.items.find((i) => i.endpoint === cur.endpoint && i.http_method === cur.http_method);
          return fresh || cur;
        });
      })
      .catch((e) => setError(getError(e)));
  }, []);

  useEffect(() => { refresh(); const t = setInterval(refresh, 10000); return () => clearInterval(t); }, [refresh]);
  useEffect(() => { loadMetrics(sel); }, [sel?.endpoint, sel?.http_method, updated, loadMetrics]); // eslint-disable-line

  if (!eps && !error) return <Spinner />;
  const s = eps?.summary || {};
  const cards = [['Monitored endpoints', s.monitored], ['Normal performance', s.normal], ['Degraded performance', s.degraded], ['Active incidents', s.active_incidents]];
  const selIncidents = sel ? incidents.filter((i) => i.endpoint === sel.endpoint && i.http_method === sel.http_method) : [];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">API Performance — APP-R-056</h2>
          <p className="text-xs text-slate-500">Measured endpoint latency, baselines and threshold-based detection. No ML diagnosis or automatic remediation exists in this phase.</p>
        </div>
        <div className="flex items-center gap-2 text-xs text-slate-500">
          {updated && <span>Updated {updated.toLocaleTimeString()} (auto 10s)</span>}
          <button className="btn-secondary" onClick={refresh}>Refresh</button>
        </div>
      </div>
      <ErrorBanner error={error} onClose={() => setError(null)} />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {cards.map(([l, v]) => (
          <div key={l} className="card"><div className="text-sm text-slate-500">{l}</div><div className="mt-1 text-3xl font-bold">{v ?? 0}</div></div>
        ))}
      </div>

      <div className="card overflow-x-auto">
        <table className="w-full">
          <thead><tr><th className="th">Endpoint</th><th className="th">Average</th><th className="th">P95</th><th className="th">P99</th><th className="th">Baseline avg</th><th className="th">Samples</th><th className="th">Status</th></tr></thead>
          <tbody className="divide-y">
            {(eps?.items || []).map((e) => (
              <tr key={e.http_method + e.endpoint} onClick={() => setSel(e)}
                className={`cursor-pointer hover:bg-slate-50 ${sel?.endpoint === e.endpoint && sel?.http_method === e.http_method ? 'bg-indigo-50' : ''}`}>
                <td className="td font-mono text-xs">{e.http_method} {e.endpoint}</td>
                <td className="td">{ms(e.average_latency_ms)}</td>
                <td className="td">{ms(e.p95_latency_ms)}</td>
                <td className="td">{ms(e.p99_latency_ms)}</td>
                <td className="td">{ms(e.baseline_average_ms)}</td>
                <td className="td">{e.sample_count ?? '—'}</td>
                <td className="td"><Badge color={STATUS_COLOR[e.status] || 'gray'}>{e.status}</Badge></td>
              </tr>
            ))}
          </tbody>
        </table>
        {(eps?.items || []).length === 0 && <p className="py-6 text-center text-sm text-slate-500">No measurements yet. Use the application to generate traffic.</p>}
      </div>

      {sel && (
        <div className="card space-y-4">
          <h3 className="font-semibold">{sel.http_method} {sel.endpoint}</h3>
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <div className="text-sm font-semibold text-slate-700">Historical baseline <Badge color="gray">{sel.baseline_status || 'none'}</Badge></div>
              <div className="mt-1 text-sm">avg {ms(sel.baseline_average_ms)} · P95 {ms(sel.baseline_p95_ms)} · P99 {ms(sel.baseline_p99_ms)}</div>
            </div>
            <div>
              <div className="text-sm font-semibold text-slate-700">Current latency (latest window)</div>
              <div className="mt-1 text-sm">avg {ms(sel.average_latency_ms)} · P95 {ms(sel.p95_latency_ms)} · P99 {ms(sel.p99_latency_ms)}</div>
            </div>
          </div>
          <div className="grid gap-4 lg:grid-cols-3">
            <LineChart title="Average" points={metrics.map((m) => m.average_latency_ms)} baseline={sel.baseline_average_ms} />
            <LineChart title="P95" points={metrics.map((m) => m.p95_latency_ms)} baseline={sel.baseline_p95_ms} color="#d97706" />
            <LineChart title="P99" points={metrics.map((m) => m.p99_latency_ms)} baseline={sel.baseline_p99_ms} color="#dc2626" />
          </div>
          <div className="max-h-64 overflow-auto">
            <table className="w-full">
              <thead><tr><th className="th">Window end</th><th className="th">Samples</th><th className="th">Avg</th><th className="th">P95</th><th className="th">P99</th><th className="th">Min</th><th className="th">Max</th><th className="th">State</th></tr></thead>
              <tbody className="divide-y">
                {[...metrics].reverse().map((m) => (
                  <tr key={m.id}>
                    <td className="td">{fmtDate(m.window_end)}</td><td className="td">{m.sample_count}</td>
                    <td className="td">{ms(m.average_latency_ms)}</td><td className="td">{ms(m.p95_latency_ms)}</td><td className="td">{ms(m.p99_latency_ms)}</td>
                    <td className="td">{ms(m.min_latency_ms)}</td><td className="td">{ms(m.max_latency_ms)}</td>
                    <td className="td"><Badge color={STATUS_COLOR[m.degradation_status] || 'gray'}>{m.degradation_status}</Badge></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="text-sm">Incidents for this endpoint: <b>{selIncidents.length}</b></div>
        </div>
      )}

      <div className="card">
        <h3 className="mb-2 font-semibold">Performance incidents</h3>
        {incidents.length === 0 && <p className="text-sm text-slate-500">No incidents recorded.</p>}
        <div className="space-y-2">
          {incidents.map((i) => (
            <div key={i.id} className="rounded border border-slate-200">
              <button className="flex w-full flex-wrap items-center justify-between gap-2 px-3 py-2 text-left hover:bg-slate-50" onClick={() => setOpenInc(openInc === i.id ? null : i.id)}>
                <span className="font-mono text-xs">{i.http_method} {i.endpoint}</span>
                <span className="flex items-center gap-2 text-xs text-slate-500">
                  {fmtDate(i.detected_at)} · avg {ms(i.degraded_metrics?.average_ms)} vs {ms(i.baseline_metrics?.average_ms)}
                  <Badge color={LIFE[i.lifecycle_state] || 'gray'}>{i.lifecycle_state}</Badge>
                </span>
              </button>
              {openInc === i.id && <div className="border-t border-slate-200 p-3"><IncidentPanel inc={i} /></div>}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
