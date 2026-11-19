import { useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useCart } from '../context/CartContext.jsx';
import { useAuth } from '../context/AuthContext.jsx';
import { api, getError, money, uuid } from '../services/api.js';
import { ErrorBanner } from '../components/ui.jsx';

export default function Cart() {
  const { items, setQty, remove, clear, total } = useCart();
  const { user } = useAuth();
  const nav = useNavigate();
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  // Idempotency key lives for one checkout attempt: reused on retry after a
  // network failure, cleared on success. A changed cart gets a new key.
  const attempt = useRef({ key: null, fingerprint: null });

  const place = async () => {
    if (!user) { nav('/login', { state: { from: '/cart' } }); return; }
    const body = { items: items.map((i) => ({ product_id: i.product_id, quantity: i.quantity })) };
    const fp = JSON.stringify(body);
    if (!attempt.current.key || attempt.current.fingerprint !== fp) {
      attempt.current = { key: uuid(), fingerprint: fp };
    }
    setBusy(true); setError(null);
    try {
      const { data } = await api.createOrder(body, attempt.current.key);
      attempt.current = { key: null, fingerprint: null };
      clear();
      nav(`/orders/${data.id}`);
    } catch (err) {
      const e = getError(err);
      setError(e);
      // Definitive server rejections need a fresh attempt; network errors keep the key.
      if (!e.network && e.status && e.status < 500) attempt.current = { key: null, fingerprint: null };
    } finally { setBusy(false); }
  };

  if (items.length === 0) {
    return <div className="card text-center text-slate-500">Your cart is empty. <Link to="/" className="text-indigo-600">Browse products</Link></div>;
  }

  return (
    <div className="card">
      <h1 className="mb-3 text-xl font-bold">Cart</h1>
      <ErrorBanner error={error} onClose={() => setError(null)} />
      <table className="w-full">
        <thead><tr><th className="th">Product</th><th className="th">Price</th><th className="th">Qty</th><th className="th">Subtotal</th><th /></tr></thead>
        <tbody className="divide-y">
          {items.map((i) => (
            <tr key={i.product_id}>
              <td className="td font-medium">{i.name}</td>
              <td className="td">{money(i.price)}</td>
              <td className="td">
                <input type="number" min="1" className="input w-20" value={i.quantity}
                  onChange={(e) => setQty(i.product_id, parseInt(e.target.value) || 1)} />
              </td>
              <td className="td">{money(i.price * i.quantity)}</td>
              <td className="td"><button className="text-red-600 text-sm" onClick={() => remove(i.product_id)}>Remove</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-4 flex items-center justify-between">
        <div className="text-lg font-bold">Total: {money(total)} <span className="text-xs font-normal text-slate-500">(final amount is recalculated by the server)</span></div>
        <button className="btn-primary" disabled={busy} onClick={place}>{busy ? 'Placing order…' : 'Place order'}</button>
      </div>
    </div>
  );
}
