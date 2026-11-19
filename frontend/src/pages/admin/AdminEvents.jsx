import { useEffect, useState, useCallback } from 'react';
import { api, getError, fmtDate } from '../../services/api.js';
import { Badge, ErrorBanner, Pagination, Spinner } from '../../components/ui.jsx';

const SEV = { INFO: 'blue', WARNING: 'yellow', ERROR: 'red', CRITICAL: 'red' };
const PAGE_SIZE = 15;

export default function AdminEvents() {
  const [filters, setFilters] = useState({ event_type: '', severity: '', rule_id: '', endpoint: '' });
  const [applied, setApplied] = useState(filters);
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    const params = { page, page_size: PAGE_SIZE };
    Object.entries(applied).forEach(([k, v]) => { if (v) params[k] = v; });
    api.events(params).then((r) => { setData(r.data); setError(null); }).catch((e) => setError(getError(e)));
  }, [applied, page]);
  useEffect(load, [load]);

  const f = (k) => (e) => setFilters({ ...filters, [k]: e.target.value });
  const submit = (e) => { e.preventDefault(); setPage(1); setApplied(filters); };

  return (
    <div className="space-y-4">
      <form onSubmit={submit} className="card flex flex-wrap items-end gap-2">
        <input className="input w-52" placeholder="Event type" value={filters.event_type} onChange={f('event_type')} />
        <select className="input w-36" value={filters.severity} onChange={f('severity')}>
          <option value="">Any severity</option>
          {['INFO', 'WARNING', 'ERROR', 'CRITICAL'].map((s) => <option key={s}>{s}</option>)}
        </select>
        <input className="input w-32" placeholder="Rule ID" value={filters.rule_id} onChange={f('rule_id')} />
        <input className="input w-52" placeholder="Endpoint" value={filters.endpoint} onChange={f('endpoint')} />
        <button className="btn-primary">Filter</button>
        <button type="button" className="btn-secondary" onClick={load}>Refresh</button>
      </form>
      <ErrorBanner error={error} />
      {!data ? <Spinner /> : (
        <div className="card overflow-x-auto">
          <table className="w-full">
            <thead><tr>{['Timestamp', 'Event type', 'Severity', 'Endpoint', 'Error code', 'Request ID', 'Rule'].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
            <tbody className="divide-y">
              {data.items.map((ev) => (
                <tr key={ev.id}>
                  <td className="td whitespace-nowrap">{fmtDate(ev.timestamp)}</td>
                  <td className="td font-medium">{ev.event_type}</td>
                  <td className="td"><Badge color={SEV[ev.severity] || 'gray'}>{ev.severity}</Badge></td>
                  <td className="td">{ev.http_method} {ev.endpoint}</td>
                  <td className="td">{ev.error_code || '—'}</td>
                  <td className="td font-mono text-xs">{ev.request_id}</td>
                  <td className="td">{ev.rule_id || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {data.items.length === 0 && <p className="py-6 text-center text-slate-500">No events match.</p>}
          <Pagination page={page} pageSize={PAGE_SIZE} total={data.total} onChange={setPage} />
        </div>
      )}
    </div>
  );
}
