import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext.jsx';
import { getError } from '../services/api.js';
import { ErrorBanner } from '../components/ui.jsx';

export default function Register() {
  const { register } = useAuth();
  const nav = useNavigate();
  const [form, setForm] = useState({ name: '', email: '', password: '' });
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      await register(form.name, form.email, form.password);
      nav('/', { replace: true });
    } catch (err) { setError(getError(err)); } finally { setBusy(false); }
  };

  return (
    <div className="mx-auto max-w-sm">
      <form onSubmit={submit} className="card space-y-3">
        <h1 className="text-xl font-bold">Create account</h1>
        <ErrorBanner error={error} />
        <input className="input" placeholder="Name" value={form.name} onChange={set('name')} required />
        <input className="input" type="email" placeholder="Email" value={form.email} onChange={set('email')} required />
        <input className="input" type="password" placeholder="Password (8–72 chars)" minLength={8} maxLength={72} value={form.password} onChange={set('password')} required />
        <button className="btn-primary w-full" disabled={busy}>{busy ? 'Creating…' : 'Register'}</button>
        <p className="text-sm text-slate-500">Already registered? <Link className="text-indigo-600" to="/login">Login</Link></p>
      </form>
    </div>
  );
}
