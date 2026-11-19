import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api, getError, money } from '../services/api.js';
import { useCart } from '../context/CartContext.jsx';
import ProductImage from '../components/ProductImage.jsx';
import { ErrorBanner, Spinner, Notice } from '../components/ui.jsx';

export default function ProductDetail() {
  const { id } = useParams();
  const { add } = useCart();
  const [p, setP] = useState(null);
  const [qty, setQty] = useState(1);
  const [error, setError] = useState(null);
  const [msg, setMsg] = useState('');

  useEffect(() => {
    api.getProduct(id).then((r) => setP(r.data)).catch((e) => setError(getError(e)));
  }, [id]);

  if (error) return <ErrorBanner error={error} />;
  if (!p) return <Spinner />;

  return (
    <div>
      <Link to="/" className="text-sm text-indigo-600">← Back to products</Link>
      <div className="card mt-3 grid gap-6 md:grid-cols-2">
        <ProductImage name={p.name} className="h-72 w-full" />
        <div>
          <h1 className="text-2xl font-bold">{p.name}</h1>
          <p className="mt-2 text-slate-600">{p.description}</p>
          <div className="mt-4 text-3xl font-bold">{money(p.price)}</div>
          <div className={`mt-1 text-sm ${p.stock_quantity > 0 ? 'text-slate-500' : 'text-red-600'}`}>
            {p.stock_quantity > 0 ? `${p.stock_quantity} available` : 'Out of stock'}
          </div>
          <div className="mt-4 flex items-center gap-2">
            <input type="number" min="1" max={Math.max(1, p.stock_quantity)} className="input w-20" value={qty}
              onChange={(e) => setQty(Math.max(1, parseInt(e.target.value) || 1))} />
            <button className="btn-primary" disabled={p.stock_quantity < 1 || !p.is_active}
              onClick={() => { add(p, qty); setMsg(`Added ${qty} to cart`); }}>Add to cart</button>
          </div>
          <div className="mt-3"><Notice>{msg}</Notice></div>
        </div>
      </div>
    </div>
  );
}
