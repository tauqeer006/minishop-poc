import { useEffect, useState, useCallback } from 'react';
import { api, getError, money } from '../../services/api.js';
import { Badge, ErrorBanner, Notice, Pagination, Spinner } from '../../components/ui.jsx';

const EMPTY = { name: '', description: '', price: '', stock_quantity: '', is_active: true };
const PAGE_SIZE = 10;

export default function AdminProducts() {
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [msg, setMsg] = useState('');
  const [editing, setEditing] = useState(null); // product or 'new'
  const [form, setForm] = useState(EMPTY);
  const [delta, setDelta] = useState({});

  const load = useCallback(() => {
    api.listProducts({ page, page_size: PAGE_SIZE, include_inactive: true })
      .then((r) => setData(r.data)).catch((e) => setError(getError(e)));
  }, [page]);
  useEffect(load, [load]);

  const handle = async (fn, okMsg) => {
    setError(null); setMsg('');
    try { await fn(); setMsg(okMsg); }
    catch (err) {
      const e = getError(err);
      if (e.code === 'VERSION_CONFLICT') e.message = 'This product was modified by someone else. The list has been reloaded — please retry.';
      setError(e);
    }
    load();
  };

  const startEdit = (p) => {
    setEditing(p);
    setForm({ name: p.name, description: p.description, price: (p.price / 100).toFixed(2), stock_quantity: p.stock_quantity, is_active: p.is_active });
  };
  const startNew = () => { setEditing('new'); setForm(EMPTY); };

  const save = async (e) => {
    e.preventDefault();
    const payload = {
      name: form.name, description: form.description,
      price: Math.round(parseFloat(form.price) * 100),
      stock_quantity: parseInt(form.stock_quantity, 10),
      is_active: form.is_active,
    };
    await handle(async () => {
      if (editing === 'new') await api.createProduct(payload);
      else await api.updateProduct(editing.id, { ...payload, expected_version: editing.version });
      setEditing(null);
    }, 'Product saved.');
  };

  const applyDelta = (p) => {
    const d = parseInt(delta[p.id], 10);
    if (!d) return;
    handle(async () => {
      await api.updateProduct(p.id, { stock_delta: d, expected_version: p.version });
      setDelta((cur) => ({ ...cur, [p.id]: '' }));
    }, 'Stock updated.');
  };

  const toggle = (p) =>
    handle(() => api.updateProduct(p.id, { is_active: !p.is_active, expected_version: p.version }), p.is_active ? 'Product deactivated.' : 'Product activated.');

  const f = (k) => (e) => setForm({ ...form, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Products</h2>
        <button className="btn-primary" onClick={startNew}>+ Add product</button>
      </div>
      <ErrorBanner error={error} onClose={() => setError(null)} />
      <Notice onClose={() => setMsg('')}>{msg}</Notice>

      {editing && (
        <form onSubmit={save} className="card grid gap-3 md:grid-cols-2">
          <h3 className="md:col-span-2 font-semibold">{editing === 'new' ? 'New product' : `Edit ${editing.name} (v${editing.version})`}</h3>
          <input className="input" placeholder="Name" value={form.name} onChange={f('name')} required />
          <input className="input" type="number" step="0.01" min="0.01" placeholder="Price (e.g. 19.99)" value={form.price} onChange={f('price')} required />
          <input className="input" type="number" min="0" placeholder="Stock quantity" value={form.stock_quantity} onChange={f('stock_quantity')} required />
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.is_active} onChange={f('is_active')} /> Active</label>
          <textarea className="input md:col-span-2" rows={2} placeholder="Description" value={form.description} onChange={f('description')} />
          <div className="md:col-span-2 flex gap-2">
            <button className="btn-primary">Save</button>
            <button type="button" className="btn-secondary" onClick={() => setEditing(null)}>Cancel</button>
          </div>
        </form>
      )}

      {!data ? <Spinner /> : (
        <div className="card overflow-x-auto">
          <table className="w-full">
            <thead><tr><th className="th">Name</th><th className="th">Price</th><th className="th">Stock</th><th className="th">Ver</th><th className="th">Status</th><th className="th">Adjust stock (±)</th><th className="th">Actions</th></tr></thead>
            <tbody className="divide-y">
              {data.items.map((p) => (
                <tr key={p.id}>
                  <td className="td font-medium">{p.name}</td>
                  <td className="td">{money(p.price)}</td>
                  <td className="td">{p.stock_quantity}</td>
                  <td className="td">{p.version}</td>
                  <td className="td"><Badge color={p.is_active ? 'green' : 'gray'}>{p.is_active ? 'Active' : 'Inactive'}</Badge></td>
                  <td className="td">
                    <div className="flex gap-1">
                      <input type="number" className="input w-20" value={delta[p.id] ?? ''} onChange={(e) => setDelta({ ...delta, [p.id]: e.target.value })} />
                      <button className="btn-secondary" onClick={() => applyDelta(p)}>Apply</button>
                    </div>
                  </td>
                  <td className="td">
                    <div className="flex gap-1">
                      <button className="btn-secondary" onClick={() => startEdit(p)}>Edit</button>
                      <button className="btn-secondary" onClick={() => toggle(p)}>{p.is_active ? 'Deactivate' : 'Activate'}</button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <Pagination page={page} pageSize={PAGE_SIZE} total={data.total} onChange={setPage} />
        </div>
      )}
    </div>
  );
}
