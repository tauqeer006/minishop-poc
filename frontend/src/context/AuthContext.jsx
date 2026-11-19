import { createContext, useContext, useEffect, useState, useCallback } from 'react';
import { api, TOKEN_KEY, USER_KEY } from '../services/api.js';

const AuthContext = createContext(null);

const readUser = () => {
  try { return JSON.parse(localStorage.getItem(USER_KEY)); } catch { return null; }
};

export function AuthProvider({ children }) {
  const [user, setUser] = useState(readUser);

  const store = (data) => {
    localStorage.setItem(TOKEN_KEY, data.access_token);
    localStorage.setItem(USER_KEY, JSON.stringify(data.user));
    setUser(data.user);
  };

  const login = useCallback(async (email, password) => {
    const { data } = await api.login({ email, password });
    store(data);
    return data.user;
  }, []);

  const register = useCallback(async (name, email, password) => {
    const { data } = await api.register({ name, email, password });
    store(data);
    return data.user;
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    setUser(null);
  }, []);

  useEffect(() => {
    const onUnauthorized = () => setUser(null);
    window.addEventListener('minishop-unauthorized', onUnauthorized);
    return () => window.removeEventListener('minishop-unauthorized', onUnauthorized);
  }, []);

  // Validate stored session once on load.
  useEffect(() => {
    if (localStorage.getItem(TOKEN_KEY)) {
      api.me().then(({ data }) => {
        localStorage.setItem(USER_KEY, JSON.stringify(data));
        setUser(data);
      }).catch(() => {});
    }
  }, []);

  return (
    <AuthContext.Provider value={{ user, login, register, logout, isAdmin: user?.role === 'admin' }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
