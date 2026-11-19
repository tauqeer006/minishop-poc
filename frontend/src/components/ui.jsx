import { useState } from 'react';

export function ErrorBanner({ error, onClose }) {
  if (!error) return null;
  return (
    <div className="mb-3 flex items-start justify-between rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
      <div>
        <span className="font-semibold">{error.code}</span>: {error.message}
        {error.requestId && <span className="ml-2 text-xs text-red-600">request_id: {error.requestId}</span>}
      </div>
      {onClose && <button onClick={onClose} className="ml-3 text-red-700">✕</button>}
    </div>
  );
}

export function Notice({ children, onClose }) {
  if (!children) return null;
  return (
    <div className="mb-3 flex items-start justify-between rounded-md border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-800">
      <div>{children}</div>
      {onClose && <button onClick={onClose} className="ml-3">✕</button>}
    </div>
  );
}

const BADGE = {
  green: 'bg-green-100 text-green-800',
  red: 'bg-red-100 text-red-800',
  yellow: 'bg-yellow-100 text-yellow-800',
  blue: 'bg-blue-100 text-blue-800',
  gray: 'bg-slate-100 text-slate-700',
  purple: 'bg-purple-100 text-purple-800',
};

export function Badge({ color = 'gray', children }) {
  return <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${BADGE[color]}`}>{children}</span>;
}

export const statusColor = (s) =>
  ({ PENDING: 'yellow', CONFIRMED: 'blue', SHIPPED: 'purple', DELIVERED: 'green', CANCELLED: 'red' }[s] || 'gray');

export function Pagination({ page, pageSize, total, onChange }) {
  const pages = Math.max(1, Math.ceil((total || 0) / pageSize));
  return (
    <div className="mt-3 flex items-center justify-between text-sm text-slate-600">
      <span>{total || 0} total</span>
      <div className="flex items-center gap-2">
        <button className="btn-secondary" disabled={page <= 1} onClick={() => onChange(page - 1)}>Prev</button>
        <span>Page {page} / {pages}</span>
        <button className="btn-secondary" disabled={page >= pages} onClick={() => onChange(page + 1)}>Next</button>
      </div>
    </div>
  );
}

export function Spinner() {
  return <div className="py-8 text-center text-sm text-slate-500">Loading…</div>;
}

export function Section({ title, tag, children }) {
  const [open, setOpen] = useState(true);
  return (
    <div className="rounded-md border border-slate-200">
      <button className="flex w-full items-center justify-between bg-slate-50 px-3 py-2 text-left" onClick={() => setOpen(!open)}>
        <span className="text-sm font-semibold text-slate-800">{title}</span>
        {tag && <Badge color="gray">{tag}</Badge>}
      </button>
      {open && <div className="p-3 text-sm">{children}</div>}
    </div>
  );
}
