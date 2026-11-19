import { useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext.jsx';
import { getError } from '../services/api.js';
import { ErrorBanner } from '../components/ui.jsx';

export default function Login() {
  const { login } = useAuth();
  const nav = useNavigate();
  const loc = useLocation();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      const u = await login(email, password);
      nav(loc.state?.from || (u.role === 'admin' ? '/admin' : '/'), { replace: true });
    } catch (err) { setError(getError(err)); } finally { setBusy(false); }
  };

  return (
    <div className="mx-auto max-w-sm">
      <form onSubmit={submit} className="card space-y-3">
        <h1 className="text-xl font-bold">Login</h1>
        <ErrorBanner error={error} />
        <input className="input" type="email" placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        <input className="input" type="password" placeholder="Password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        <button className="btn-primary w-full" disabled={busy}>{busy ? 'Signing in…' : 'Login'}</button>
        <p className="text-sm text-slate-500">No account? <Link className="text-indigo-600" to="/register">Register</Link></p>
        {import.meta.env.DEV && (
          <div className="rounded bg-slate-100 p-2 text-xs text-slate-600">
            <div className="font-semibold">Development credentials</div>
            <div>admin@minishop.dev / Admin@12345</div>
            <div>customer1@minishop.dev / Customer@12345</div>
          </div>
        )}
      </form>
    </div>
  );
}
