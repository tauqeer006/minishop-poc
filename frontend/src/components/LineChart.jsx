import { ms } from '../services/api.js';

/** Minimal inline-SVG line chart. points: number[]; baseline: number|null. */
export default function LineChart({ title, points, baseline, color = '#4f46e5' }) {
  const W = 360, H = 130, P = 28;
  const vals = points.filter((v) => v !== null && v !== undefined);
  if (vals.length === 0) return <div className="text-xs text-slate-400">{title}: no data</div>;
  const max = Math.max(...vals, baseline || 0) * 1.1 || 1;
  const x = (i) => P + (points.length === 1 ? (W - 2 * P) / 2 : (i * (W - 2 * P)) / (points.length - 1));
  const y = (v) => H - P - (v / max) * (H - 2 * P);
  const path = points.map((v, i) => (v == null ? null : `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(v).toFixed(1)}`)).filter(Boolean).join(' ');
  return (
    <div>
      <div className="mb-1 flex justify-between text-xs"><span className="font-semibold text-slate-700">{title}</span>
        <span className="text-slate-500">latest {ms(vals[vals.length - 1])}{baseline ? ` · baseline ${ms(baseline)}` : ''}</span></div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full rounded border border-slate-200 bg-white">
        <line x1={P} y1={H - P} x2={W - P} y2={H - P} stroke="#cbd5e1" />
        <line x1={P} y1={P / 2} x2={P} y2={H - P} stroke="#cbd5e1" />
        <text x={2} y={y(max / 1.1) + 3} fontSize="9" fill="#64748b">{Math.round(max / 1.1)}</text>
        <text x={2} y={H - P + 3} fontSize="9" fill="#64748b">0</text>
        {baseline ? (
          <>
            <line x1={P} x2={W - P} y1={y(baseline)} y2={y(baseline)} stroke="#16a34a" strokeDasharray="4 3" />
            <text x={W - P} y={y(baseline) - 3} fontSize="9" textAnchor="end" fill="#16a34a">baseline</text>
          </>
        ) : null}
        <path d={path} fill="none" stroke={color} strokeWidth="2" />
        {points.map((v, i) => v == null ? null : <circle key={i} cx={x(i)} cy={y(v)} r="2.5" fill={color} />)}
      </svg>
    </div>
  );
}
