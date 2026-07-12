import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react';
import { apiFetch, tokenStorage } from '../api/client';
import type { Role, User } from '../api/types';


/**
 * @property access - JWT access token.
 * @property refresh - JWT refresh token.
 * @property user - The authenticated user.
 */
interface VerifyResponse {
  access: string;
  refresh: string;
  user: User;
}


/**
 * @property user - The currently authenticated user, or null if signed out.
 * @property loading - Whether an auth request is in flight.
 * @property requestMagicLink - Emails a sign-in link for the given address
 *   and role.
 * @property verifyMagicLink - Exchanges an emailed token for a session.
 * @property logout - Clears the stored session.
 */
interface AuthContextValue {
  user: User | null;
  loading: boolean;
  requestMagicLink: (email: string, role: Role) => Promise<void>;
  verifyMagicLink: (token: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

const USER_STORAGE_KEY = 'rentmebro_user';


/**
 * Provides magic-link auth state (current user, login/logout) to the app.
 * @param props.children - The subtree that can call useAuth().
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(() => {
    const stored = localStorage.getItem(USER_STORAGE_KEY);
    return stored ? (JSON.parse(stored) as User) : null;
  });
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (user) {
      localStorage.setItem(USER_STORAGE_KEY, JSON.stringify(user));
    } else {
      localStorage.removeItem(USER_STORAGE_KEY);
    }
  }, [user]);


  /**
   * Requests a magic sign-in link be emailed to the given address.
   * @param email - The address to email the sign-in link to.
   * @param role - Which role (landlord or renter) to sign in as.
   */
  async function requestMagicLink(email: string, role: Role) {
    setLoading(true);
    try {
      await apiFetch('/api/auth/magic-link/', {
        method: 'POST',
        body: { email, role },
      });
    } finally {
      setLoading(false);
    }
  }


  /**
   * Exchanges a magic-link token for a session and stores it.
   * @param token - The token from the emailed sign-in link.
   */
  async function verifyMagicLink(token: string) {
    setLoading(true);
    try {
      const data = await apiFetch<VerifyResponse>(
        '/api/auth/magic-link/verify/',
        { method: 'POST', body: { token } }
      );
      tokenStorage.set(data.access, data.refresh);
      setUser(data.user);
    } finally {
      setLoading(false);
    }
  }

  function logout() {
    tokenStorage.clear();
    setUser(null);
  }

  const value = { user, loading, requestMagicLink, verifyMagicLink, logout };
  return (
    <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
  );
}


/** @returns The current auth context; throws outside an AuthProvider. */
export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return ctx;
}
