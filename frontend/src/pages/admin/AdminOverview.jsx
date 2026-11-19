import { useEffect, useState } from 'react';
import { api, getError } from '../../services/api.js';
import { ErrorBanner, Spinner } from '../../components/ui.jsx';

export default function AdminOverview() {
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    api.dashboard().then((r) => setD(r.data)).catch((e) => setError(getError(e)));
  }, []);
  if (error) return <ErrorBanner error={error} />;
  if (!d) return <Spinner />;
  const cards = [
    ['Total products', d.total_products],
    ['Total customers', d.total_customers],
    ['Total orders', d.total_orders],
    ['Pending orders', d.pending_orders],
  ];
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {cards.map(([label, v]) => (
        <div key={label} className="card">
          <div className="text-sm text-slate-500">{label}</div>
          <div className="mt-1 text-3xl font-bold">{v}</div>
        </div>
      ))}
    </div>
  );
}
