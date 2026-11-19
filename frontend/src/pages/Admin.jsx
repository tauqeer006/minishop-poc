import { useState } from 'react';
import AdminOverview from './admin/AdminOverview.jsx';
import AdminProducts from './admin/AdminProducts.jsx';
import AdminOrders from './admin/AdminOrders.jsx';
import AdminEvents from './admin/AdminEvents.jsx';
import AdminPerformance from './admin/AdminPerformance.jsx';

const TABS = [
  ['overview', 'Overview', AdminOverview],
  ['products', 'Products', AdminProducts],
  ['orders', 'Orders', AdminOrders],
  ['events', 'Application Events', AdminEvents],
  ['performance', 'API Performance', AdminPerformance],
];

export default function Admin() {
  const [tab, setTab] = useState(() => {
    try { return localStorage.getItem('minishop_admin_tab') || 'overview'; } catch { return 'overview'; }
  });
  const select = (t) => { setTab(t); try { localStorage.setItem('minishop_admin_tab', t); } catch { /* ignore */ } };
  const Active = (TABS.find((t) => t[0] === tab) || TABS[0])[2];

  return (
    <div>
      <h1 className="mb-3 text-xl font-bold">Administrator dashboard</h1>
      <div className="mb-4 flex flex-wrap gap-1 border-b border-slate-200">
        {TABS.map(([key, label]) => (
          <button key={key} onClick={() => select(key)}
            className={`px-3 py-2 text-sm font-medium ${tab === key ? 'border-b-2 border-indigo-600 text-indigo-600' : 'text-slate-500 hover:text-slate-800'}`}>
            {label}
          </button>
        ))}
      </div>
      <Active />
    </div>
  );
}
