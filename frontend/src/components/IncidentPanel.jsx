import { useState } from 'react';
import { api, getError, ms, fmtDate } from '../services/api.js';
import { Badge, ErrorBanner, Section } from './ui.jsx';

const LIFE = { OPEN: 'red', VERIFYING: 'yellow', RESOLVED: 'green', FAILED: 'red', ESCALATED: 'purple', CLOSED_NO_ACTION: 'gray' };

const Row = ({ k, v }) => (
  <div className="flex justify-between gap-4 py-0.5"><span className="text-slate-500">{k}</span><span className="text-right font-medium">{v ?? '—'}</span></div>
);

function TraceView({ traceId }) {
  const [t, setT] = useState(null);
  const [err, setErr] = useState(null);
  const load = () => api.perfTrace(traceId).then((r) => setT(r.data)).catch((e) => setErr(getError(e)));
  if (!t && !err) return <button className="text-indigo-600 underline" onClick={load}>{traceId}</button>;
  if (err) return <ErrorBanner error={err} />;
  const byType = {};
  t.spans.forEach((s) => { byType[s.operation_type] = (byType[s.operation_type] || 0) + s.duration_ms; });
  return (
    <div className="my-2 rounded border border-indigo-200 bg-indigo-50 p-2">
      <div className="font-mono text-xs">{t.trace_id} — {t.endpoint} — total {ms(t.total_duration_ms)}</div>
      <div className="mt-1 text-xs">DB queries: <b>{t.db_query_count}</b> · DB duration: <b>{ms(t.db_duration_ms)}</b></div>
      <div className="mt-1 text-xs">Time by operation type (sum of span durations):{' '}
        {Object.entries(byType).map(([k, v]) => <Badge key={k} color="blue">{k}: {ms(v)}</Badge>)}</div>
      {t.repeated_queries?.length > 0 && (
        <div className="mt-1 text-xs">Repeated queries: {t.repeated_queries.map((q) => `${q.query_signature} ×${q.count}`).join('; ')}</div>
      )}
      <table className="mt-2 w-full text-xs">
        <thead><tr><th className="text-left">Span</th><th className="text-left">Type</th><th className="text-right">Duration</th><th className="text-left pl-2">Status</th></tr></thead>
        <tbody>
          {t.spans.map((s) => (
            <tr key={s.span_id} className="border-t border-indigo-100">
              <td>{s.parent_span_id ? '↳ ' : ''}{s.operation_name}</td><td>{s.operation_type}</td>
              <td className="text-right">{ms(s.duration_ms)}</td><td className="pl-2">{s.status}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function IncidentPanel({ inc }) {
  const b = inc.baseline_metrics || {}, d = inc.degraded_metrics || {}, ev = inc.evidence || {};
  const diag = inc.diagnosis || {}, act = inc.recommended_action, det = inc.detection || {};
  const executed = inc.action_status && inc.action_status !== 'NOT_EXECUTED';
  return (
    <div className="space-y-3">
      <Section title="1. Observed facts (measured)" tag="MEASURED">
        <table className="mb-2 w-full text-sm">
          <thead><tr><th className="th">Metric</th><th className="th">Baseline</th><th className="th">Degraded</th></tr></thead>
          <tbody>
            <tr><td className="td">Average</td><td className="td">{ms(b.average_ms)}</td><td className="td">{ms(d.average_ms)}</td></tr>
            <tr><td className="td">P95</td><td className="td">{ms(b.p95_ms)}</td><td className="td">{ms(d.p95_ms)}</td></tr>
            <tr><td className="td">P99</td><td className="td">{ms(b.p99_ms)}</td><td className="td">{ms(d.p99_ms)}</td></tr>
          </tbody>
        </table>
        <Row k="Detected at" v={fmtDate(inc.detected_at)} />
        <Row k="Degradation started" v={fmtDate(inc.degradation_started_at)} />
        <Row k="Degradation duration" v={inc.degradation_duration_seconds != null ? `${Math.round(inc.degradation_duration_seconds)} s` : null} />
        {d.windows?.length > 0 && (
          <div className="mt-2 text-xs text-slate-600">Degraded windows (avg ms): {d.windows.map((w) => Math.round(w.average_ms)).join(' → ')}</div>
        )}
        <div className="mt-3 font-semibold">Trace evidence</div>
        <Row k="Traces analysed" v={ev.traces_analyzed} />
        <Row k="Total duration (representative)" v={ms(ev.total_duration_ms)} />
        <Row k="DB query count" v={ev.db_query_count} />
        <Row k="DB duration" v={ms(ev.db_duration_ms)} />
        <Row k="Dominant operation" v={ev.dominant_operation_type ? `${ev.dominant_operation_type}${ev.dominant_share != null ? ` (${Math.round(ev.dominant_share * 100)}%)` : ''}` : null} />
        <Row k="Observed pattern" v={ev.pattern} />
        {ev.breakdown_ms && (
          <div className="mt-1 text-xs">Breakdown: {Object.entries(ev.breakdown_ms).map(([k, v]) => <Badge key={k} color="gray">{k}: {ms(v)}</Badge>)}</div>
        )}
        {ev.repeated_identical_queries?.length > 0 && (
          <div className="mt-1 text-xs">Repeated identical queries: {ev.repeated_identical_queries.map((q) => `${q.query_signature} ×${q.count}`).join('; ')}</div>
        )}
        <div className="mt-2 text-xs text-slate-500">Trace IDs (click to load spans):</div>
        <div className="space-y-1 font-mono text-xs">
          {(ev.trace_ids || []).slice(0, 5).map((t) => <div key={t}><TraceView traceId={t} /></div>)}
        </div>
      </Section>

      <Section title="2. Threshold-based detection" tag="RULE-BASED">
        <Row k="Method" v={det.method} />
        <Row k="Consecutive windows required" v={det.consecutive_windows} />
        <pre className="mt-1 overflow-x-auto rounded bg-slate-100 p-2 text-xs">{JSON.stringify(det.thresholds || {}, null, 2)}</pre>
      </Section>

      <Section title="3. ML diagnosis" tag="FUTURE PHASE">
        <Row k="Status" v={diag.status || 'AWAITING_ML_MODEL'} />
        <p className="mt-1 text-slate-600">No ML model has been run in this phase. {diag.note}</p>
        {diag.confidence != null && <Row k="Confidence" v={diag.confidence} />}
        {diag.probable_cause && <Row k="Probable cause" v={diag.probable_cause} />}
      </Section>

      <Section title="4. Recommended action" tag="PROPOSED">
        {act ? (
          <>
            <Row k="Action" v={`${act.action_id} — ${act.name}`} />
            <Row k="Selected by" v={act.selected_by} />
            <Row k="Requires approval" v={String(act.requires_approval)} />
            <p className="mt-1 text-slate-600">{act.description}</p>
            <p className="mt-1 text-xs font-semibold text-amber-700">Proposed only — not executed.</p>
          </>
        ) : <p className="text-slate-500">No action proposed.</p>}
        {inc.expected_verification && (
          <pre className="mt-2 overflow-x-auto rounded bg-slate-100 p-2 text-xs">{JSON.stringify(inc.expected_verification, null, 2)}</pre>
        )}
      </Section>

      <Section title="5. Action execution" tag="ACTUAL">
        <Row k="Action status" v={inc.action_status} />
        {!executed && <p className="text-slate-600">No action has been executed.</p>}
        {inc.action_attempts?.length > 0 && (
          <pre className="mt-1 overflow-x-auto rounded bg-slate-100 p-2 text-xs">{JSON.stringify(inc.action_attempts, null, 2)}</pre>
        )}
      </Section>

      <Section title="6. Verification" tag="VERIFIED RECOVERY">
        <Row k="Recovery status" v={inc.recovery_status} />
        {inc.verification_results?.length > 0
          ? <pre className="mt-1 overflow-x-auto rounded bg-slate-100 p-2 text-xs">{JSON.stringify(inc.verification_results, null, 2)}</pre>
          : <p className="text-slate-500">No verification results recorded.</p>}
        <Row k="Resolved at" v={fmtDate(inc.resolved_at)} />
      </Section>

      <Section title="7. Escalation" tag="ENGINEERING">
        <Row k="Escalation status" v={inc.escalation_status} />
        <Row k="Lifecycle state" v={<Badge color={LIFE[inc.lifecycle_state] || 'gray'}>{inc.lifecycle_state}</Badge>} />
      </Section>
    </div>
  );
}
