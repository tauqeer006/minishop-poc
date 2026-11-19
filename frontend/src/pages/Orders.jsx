import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, getError, money, fmtDate } from '../services/api.js';
import { Badge, ErrorBanner, Pagination, Spinner, statusColor } from '../components/ui.jsx';

export default function Orders() {
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.listOrders({ page, page_size: 10 }).then((r) => setData(r.data)).catch((e) => setError(getError(e)));
  }, [page]);

  return (
    <div className="card">
      <h1 className="mb-3 text-xl font-bold">My orders</h1>
      <ErrorBanner error={error} />
      {!data && !error && <Spinner />}
      {data && (
        <>
          <table className="w-full">
            <thead><tr><th className="th">Order</th><th className="th">Date</th><th className="th">Items</th><th className="th">Total</th><th className="th">Status</th></tr></thead>
            <tbody className="divide-y">
              {data.items.map((o) => (
                <tr key={o.id}>
                  <td className="td"><Link className="text-indigo-600" to={`/orders/${o.id}`}>{o.id}</Link></td>
                  <td className="td">{fmtDate(o.created_at)}</td>
                  <td className="td">{o.items.length}</td>
                  <td className="td">{money(o.total_amount)}</td>
                  <td className="td"><Badge color={statusColor(o.status)}>{o.status}</Badge></td>
                </tr>
              ))}
            </tbody>
          </table>
          {data.items.length === 0 && <p className="py-6 text-center text-slate-500">No orders yet.</p>}
          <Pagination page={page} pageSize={10} total={data.total} onChange={setPage} />
        </>
      )}
    </div>
  );
}
