import { createContext, useContext, useState, useEffect, useCallback } from 'react';
import api from '../services/api';

const AuthContext = createContext(null);

const TOKEN_KEY = 'token';
const USER_KEY = 'user';

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_KEY));
  const [isLoading, setIsLoading] = useState(true);

  const clearSession = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    setToken(null);
    setUser(null);
  }, []);

  /** Canonical user from the backend; source of truth for role. */
  const refreshUser = useCallback(async () => {
    const res = await api.get('/auth/me');
    const userData = res.data;
    localStorage.setItem(USER_KEY, JSON.stringify(userData));
    setUser(userData);
    return userData;
  }, []);

  // Session restoration: a stored token is only trusted after /auth/me succeeds.
  useEffect(() => {
    const restore = async () => {
      const stored = localStorage.getItem(TOKEN_KEY);
      if (!stored) {
        setIsLoading(false);
        return;
      }
      setToken(stored);
      try {
        await refreshUser();
      } catch {
        clearSession();
      } finally {
        setIsLoading(false);
      }
    };
    restore();
  }, [refreshUser, clearSession]);

  const login = async (email, password) => {
    const res = await api.post('/auth/login', {
      email: String(email).trim().toLowerCase(),
      password,
    });
    localStorage.setItem(TOKEN_KEY, res.data.access_token);
    setToken(res.data.access_token);
    // Canonical role comes from /auth/me, never from client input.
    return refreshUser();
  };

  const register = async (name, email, password, phone) => {
    const res = await api.post('/auth/register', {
      name: String(name).trim(),
      email: String(email).trim().toLowerCase(),
      password,
      ...(phone ? { phone: String(phone).trim() } : {}),
    });
    localStorage.setItem(TOKEN_KEY, res.data.access_token);
    setToken(res.data.access_token);
    return refreshUser();
  };

  const logout = useCallback(() => {
    clearSession();
  }, [clearSession]);

  return (
    <AuthContext.Provider
      value={{
        user,
        token,
        isAuthenticated: Boolean(user && token),
        isLoading,
        loading: isLoading,
        login,
        register,
        logout,
        refreshUser,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
