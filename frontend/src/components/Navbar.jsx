import { Link, NavLink, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext.jsx';
import { useCart } from '../context/CartContext.jsx';

export default function Navbar() {
  const { user, logout, isAdmin } = useAuth();
  const { count } = useCart();
  const nav = useNavigate();
  const cls = ({ isActive }) => `text-sm ${isActive ? 'text-indigo-600 font-semibold' : 'text-slate-600 hover:text-slate-900'}`;
  return (
    <header className="border-b border-slate-200 bg-white">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
        <Link to="/" className="text-lg font-bold text-indigo-600">MiniShop</Link>
        <nav className="flex items-center gap-4">
          <NavLink to="/" end className={cls}>Products</NavLink>
          <NavLink to="/cart" className={cls}>Cart ({count})</NavLink>
          {user && <NavLink to="/orders" className={cls}>My Orders</NavLink>}
          {isAdmin && <NavLink to="/admin" className={cls}>Admin</NavLink>}
          {user ? (
            <>
              <span className="text-xs text-slate-500">{user.name} ({user.role})</span>
              <button className="btn-secondary" onClick={() => { logout(); nav('/login'); }}>Logout</button>
            </>
          ) : (
            <>
              <NavLink to="/login" className={cls}>Login</NavLink>
              <NavLink to="/register" className={cls}>Register</NavLink>
            </>
          )}
        </nav>
      </div>
    </header>
  );
}
