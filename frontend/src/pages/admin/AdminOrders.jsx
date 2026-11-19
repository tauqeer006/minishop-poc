import { useEffect, useState, useCallback } from 'react';
import { api, getError, money, fmtDate, uuid } from '../../services/api.js';
import OrderView from '../../components/OrderView.jsx';
import { Badge, ErrorBanner, Notice, Pagination, Spinner, statusColor } from '../../components/ui.jsx';

const STATUSES = ['PENDING', 'CONFIRMED', 'SHIPPED', 'DELIVERED', 'CANCELLED'];
const TRANSITIONS = {
  PENDING: ['CONFIRMED', 'CANCELLED'],
  CONFIRMED: ['SHIPPED', 'CANCELLED'],
  SHIPPED: ['DELIVERED'],
  DELIVERED: [],
  CANCELLED: [],
};
const PAGE_SIZE = 10;

export default function AdminOrders() {
  const [status, setStatus] = useState('');
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  const [selected, setSelected] = useState(null);
  const [next, setNext] = useState('');
  const [error, setError] = useState(null);
  const [msg, setMsg] = useState('');

  const load = useCallback(() => {
    api.adminOrders({ status: status || undefined, page, page_size: PAGE_SIZE })
      .then((r) => { setData(r.data); setSelected((s) => (s ? r.data.items.find((o) => o.id === s.id) || s : s)); })
      .catch((e) => setError(getError(e)));
  }, [status, page]);
  useEffect(load, [load]);

  const update = async () => {
    if (!next) return;
    setError(null); setMsg('');
    try {
      const { meta } = await api.updateOrderStatus(selected.id, { status: next, workflow_execution_id: uuid() });
      setMsg(meta?.duplicate ? 'Duplicate workflow execution ignored — previous result returned.' : `Order moved to ${next}.`);
      setNext('');
    } catch (err) { setError(getError(err)); }
    load();
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Orders</h2>
        <select className="input w-44" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
          <option value="">All statuses</option>
          {STATUSES.map((s) => <option key={s}>{s}</option>)}
        </select>
      </div>
      <ErrorBanner error={error} onClose={() => setError(null)} />
      <Notice onClose={() => setMsg('')}>{msg}</Notice>
      {!data ? <Spinner /> : (
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="card overflow-x-auto">
            <table className="w-full">
              <thead><tr><th className="th">Order</th><th className="th">Customer</th><th className="th">Total</th><th className="th">Status</th></tr></thead>
              <tbody className="divide-y">
                {data.items.map((o) => (
                  <tr key={o.id} className={`cursor-pointer hover:bg-slate-50 ${selected?.id === o.id ? 'bg-indigo-50' : ''}`} onClick={() => { setSelected(o); setNext(''); }}>
                    <td className="td"><div className="font-mono text-xs">{o.id}</div><div className="text-xs text-slate-400">{fmtDate(o.created_at)}</div></td>
                    <td className="td">{o.customer_name}<div className="text-xs text-slate-400">{o.customer_email}</div></td>
                    <td className="td">{money(o.total_amount)}</td>
                    <td className="td"><Badge color={statusColor(o.status)}>{o.status}</Badge></td>
                  </tr>
                ))}
              </tbody>
            </table>
            {data.items.length === 0 && <p className="py-6 text-center text-slate-500">No orders.</p>}
            <Pagination page={page} pageSize={PAGE_SIZE} total={data.total} onChange={setPage} />
          </div>
          <div className="card">
            {!selected ? <p className="text-sm text-slate-500">Select an order to see its details.</p> : (
              <>
                <OrderView order={selected} />
                <div className="mt-4 flex items-center gap-2 border-t pt-3">
                  {TRANSITIONS[selected.status].length === 0 ? (
                    <span className="text-sm text-slate-500">No further transitions available.</span>
                  ) : (
                    <>
                      <select className="input w-44" value={next} onChange={(e) => setNext(e.target.value)}>
                        <option value="">Change status…</option>
                        {TRANSITIONS[selected.status].map((s) => <option key={s}>{s}</option>)}
                      </select>
                      <button className="btn-primary" disabled={!next} onClick={update}>Update</button>
                    </>
                  )}
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
