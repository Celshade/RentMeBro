import { type ReactNode, useCallback, useEffect, useState } from 'react';
import { Navigate, Route, Routes, useNavigate } from 'react-router-dom';
import { apiFetch } from './api/client';
import { formatUserName } from './api/format';
import { AuthProvider, useAuth } from './auth/AuthContext';
import { RequestMagicLink } from './auth/RequestMagicLink';
import { VerifyMagicLink } from './auth/VerifyMagicLink';
import { InvoiceDetail } from './invoices/InvoiceDetail';
import { RenterDashboard } from './renter/RenterDashboard';
import { LandlordDashboard } from './landlord/LandlordDashboard';
import { ThemeProvider, useTheme, type Theme } from './theme/ThemeContext';

const THEME_OPTIONS: { value: Theme; label: string }[] = [
  { value: 'system', label: 'System' },
  { value: 'light', label: 'Light' },
  { value: 'dark', label: 'Dark' },
];


/** A segmented control letting the user pick system/light/dark directly. */
function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  return (
    <div className="theme-toggle" role="group" aria-label="Theme">
      {THEME_OPTIONS.map((option) => (
        <button
          key={option.value}
          type="button"
          className="theme-toggle__option"
          aria-pressed={theme === option.value}
          onClick={() => setTheme(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

/**
 * Shared signed-in shell: header with identity/back/logout controls,
 * wrapping whatever page is active. Redirects to /login if signed out.
 * @param props.children - Render prop for the active page, given the
 *   setter for the header's "back to dashboard" handler.
 */
function AppShell({
  children,
}: {
  children: (
    setBackHandler: (handler: (() => void) | null) => void
  ) => ReactNode;
}) {
  const { user, logout } = useAuth();
  const [backHandler, setBackHandler] = useState<(() => void) | null>(null);
  const registerBackHandler = useCallback(
    (handler: (() => void) | null) => setBackHandler(() => handler),
    []
  );

  if (!user) return <Navigate to="/login" replace />;

  return (
    <div>
      <header className="app-header">
        <div className="app-header__identity">
          <span className="app-header__name">{formatUserName(user)}</span>
          <span className="app-header__role">{user.role}</span>
        </div>
        <div className="app-header__actions">
          {backHandler && (
            <button onClick={backHandler}>Back to dashboard</button>
          )}
          <ThemeToggle />
          <button onClick={logout}>Log Out</button>
        </div>
      </header>
      <main className="app-main">{children(registerBackHandler)}</main>
    </div>
  );
}

function Home({
  onBackHandlerChange,
}: {
  onBackHandlerChange: (handler: (() => void) | null) => void;
}) {
  const { user } = useAuth();

  if (!user) return null;

  return user.role === 'renter' ? (
    <RenterDashboard onBackHandlerChange={onBackHandlerChange} />
  ) : (
    <LandlordDashboard onBackHandlerChange={onBackHandlerChange} />
  );
}


/**
 * Landing page for the Stripe Connect onboarding redirect (both the
 * "return" and "refresh" AccountLink URLs land here). Forces a live
 * refresh of the landlord's connect status — rather than waiting on
 * the account.updated webhook, which can lag behind this redirect —
 * then sends them back to the dashboard so its "Payments" badge
 * reflects the up-to-date status.
 */
function StripeReturn() {
  const navigate = useNavigate();

  useEffect(() => {
    apiFetch('/api/payments/connect/status/?refresh=true').finally(() =>
      navigate('/', { replace: true })
    );
  }, [navigate]);

  return (
    <AppShell>{() => <p>Finishing Stripe setup...</p>}</AppShell>
  );
}

function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <Routes>
          <Route
            path="/"
            element={
              <AppShell>
                {(setBackHandler) => (
                  <Home onBackHandlerChange={setBackHandler} />
                )}
              </AppShell>
            }
          />
          <Route
            path="/invoices/:invoiceId"
            element={
              <AppShell>
                {(setBackHandler) => (
                  <InvoiceDetail onBackHandlerChange={setBackHandler} />
                )}
              </AppShell>
            }
          />
          <Route path="/login" element={<RequestMagicLink />} />
          <Route path="/auth/verify" element={<VerifyMagicLink />} />
          <Route path="/landlord/stripe/return" element={<StripeReturn />} />
          <Route path="/landlord/stripe/refresh" element={<StripeReturn />} />
        </Routes>
      </AuthProvider>
    </ThemeProvider>
  );
}

export default App;
