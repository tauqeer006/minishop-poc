import { money, fmtDate } from '../services/api.js';
import { Badge, statusColor } from './ui.jsx';

export default function OrderView({ order }) {
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-lg font-bold">Order {order.id}</h2>
        <Badge color={statusColor(order.status)}>{order.status}</Badge>
        <span className="text-xs text-slate-500">Placed {fmtDate(order.created_at)}</span>
      </div>
      <table className="w-full">
        <thead><tr><th className="th">Product</th><th className="th">Qty</th><th className="th">Unit price</th><th className="th">Subtotal</th></tr></thead>
        <tbody className="divide-y">
          {order.items.map((i) => (
            <tr key={i.product_id}>
              <td className="td">{i.product_name}</td>
              <td className="td">{i.quantity}</td>
              <td className="td">{money(i.unit_price)}</td>
              <td className="td">{money(i.subtotal)}</td>
            </tr>
          ))}
        </tbody>
        <tfoot><tr><td colSpan={3} className="td text-right font-semibold">Total</td><td className="td font-bold">{money(order.total_amount)}</td></tr></tfoot>
      </table>
      <div>
        <h3 className="mb-2 text-sm font-semibold">Status history</h3>
        <ol className="space-y-2 border-l-2 border-slate-200 pl-4">
          {(order.status_history || []).map((h, idx) => (
            <li key={idx} className="text-sm">
              <Badge color={statusColor(h.status)}>{h.status}</Badge>
              <span className="ml-2 text-xs text-slate-500">{fmtDate(h.at)}{h.note ? ` — ${h.note}` : ''}</span>
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}
