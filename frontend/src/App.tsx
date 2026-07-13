import { useState } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import { formatUserName } from './api/format';
import { AuthProvider, useAuth } from './auth/AuthContext';
import { RequestMagicLink } from './auth/RequestMagicLink';
import { VerifyMagicLink } from './auth/VerifyMagicLink';
import { RenterDashboard } from './renter/RenterDashboard';
import { LandlordDashboard } from './landlord/LandlordDashboard';

function Home() {
  const { user, logout } = useAuth();
  const [gasBillingEnabled, setGasBillingEnabled] = useState(false);

  if (!user) return <Navigate to="/login" replace />;

  return (
    <div>
      <header className="app-header">
        <div className="app-header__identity">
          <span className="app-header__name">{formatUserName(user)}</span>
          <span className="app-header__role">{user.role}</span>
        </div>
        <div className="app-header__actions">
          {gasBillingEnabled && (
            <button onClick={() => setGasBillingEnabled(false)}>
              Back to dashboard
            </button>
          )}
          <button onClick={logout}>Log out</button>
        </div>
      </header>
      {user.role === 'renter' ? (
        <RenterDashboard />
      ) : (
        <LandlordDashboard
          gasBillingEnabled={gasBillingEnabled}
          onGasBillingEnabledChange={setGasBillingEnabled}
        />
      )}
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
