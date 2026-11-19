import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, getError, money } from '../services/api.js';
import { useCart } from '../context/CartContext.jsx';
import ProductImage from '../components/ProductImage.jsx';
import { ErrorBanner, Pagination, Spinner } from '../components/ui.jsx';

const PAGE_SIZE = 12;

export default function Products() {
  const { add } = useCart();
  const [search, setSearch] = useState('');
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [added, setAdded] = useState(null);

  useEffect(() => {
    setData(null);
    api.listProducts({ search: query || undefined, page, page_size: PAGE_SIZE })
      .then((r) => { setData(r.data); setError(null); })
      .catch((e) => setError(getError(e)));
  }, [query, page]);

  const submit = (e) => { e.preventDefault(); setPage(1); setQuery(search.trim()); };
  const addToCart = (p) => { add(p, 1); setAdded(p.id); setTimeout(() => setAdded(null), 1200); };

  return (
    <div>
      <form onSubmit={submit} className="mb-4 flex gap-2">
        <input className="input max-w-sm" placeholder="Search products…" value={search} onChange={(e) => setSearch(e.target.value)} />
        <button className="btn-primary">Search</button>
      </form>
      <ErrorBanner error={error} />
      {!data && !error && <Spinner />}
      {data && (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {data.items.map((p) => (
              <div key={p.id} className="card flex flex-col">
                <Link to={`/products/${p.id}`}><ProductImage name={p.name} /></Link>
                <Link to={`/products/${p.id}`} className="mt-3 font-semibold hover:text-indigo-600">{p.name}</Link>
                <div className="mt-1 text-lg font-bold">{money(p.price)}</div>
                <div className={`text-xs ${p.stock_quantity > 0 ? 'text-slate-500' : 'text-red-600'}`}>
                  {p.stock_quantity > 0 ? `${p.stock_quantity} in stock` : 'Out of stock'}
                </div>
                <button className="btn-primary mt-3" disabled={p.stock_quantity < 1} onClick={() => addToCart(p)}>
                  {added === p.id ? 'Added ✓' : 'Add to cart'}
                </button>
              </div>
            ))}
          </div>
          {data.items.length === 0 && <p className="py-8 text-center text-slate-500">No products found.</p>}
          <Pagination page={page} pageSize={PAGE_SIZE} total={data.total} onChange={setPage} />
        </>
      )}
    </div>
  );
}
