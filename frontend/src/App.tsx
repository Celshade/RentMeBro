import { useCallback, useState } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import { formatUserName } from './api/format';
import { AuthProvider, useAuth } from './auth/AuthContext';
import { RequestMagicLink } from './auth/RequestMagicLink';
import { VerifyMagicLink } from './auth/VerifyMagicLink';
import { RenterDashboard } from './renter/RenterDashboard';
import { LandlordDashboard } from './landlord/LandlordDashboard';

function Home() {
  const { user, logout } = useAuth();
  const [backHandler, setBackHandler] = useState<(() => void) | null>(null);

  /**
   * Registers (or clears) the handler for the shared header's "back to
   * dashboard" button, so any active sub-view can offer a way back
   * without the header needing to know which one is open.
   */
  const handleBackHandlerChange = useCallback(
    (handler: (() => void) | null) => {
      setBackHandler(() => handler);
    },
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
          <button onClick={logout}>Log out</button>
        </div>
      </header>
      <main className="app-main">
        {user.role === 'renter' ? (
          <RenterDashboard />
        ) : (
          <LandlordDashboard onBackHandlerChange={handleBackHandlerChange} />
        )}
      </main>
    </div>
  );
}

function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/login" element={<RequestMagicLink />} />
        <Route path="/auth/verify" element={<VerifyMagicLink />} />
      </Routes>
    </AuthProvider>
  );
}

export default App;
