import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api, getError } from '../services/api.js';
import OrderView from '../components/OrderView.jsx';
import { ErrorBanner, Spinner } from '../components/ui.jsx';

export default function OrderDetail() {
  const { id } = useParams();
  const [order, setOrder] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.getOrder(id).then((r) => setOrder(r.data)).catch((e) => setError(getError(e)));
  }, [id]);

  return (
    <div>
      <Link to="/orders" className="text-sm text-indigo-600">← My orders</Link>
      <div className="card mt-3">
        <ErrorBanner error={error} />
        {!order && !error && <Spinner />}
        {order && <OrderView order={order} />}
      </div>
    </div>
  );
}
