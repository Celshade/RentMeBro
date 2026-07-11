import { Navigate, Route, Routes } from 'react-router-dom';
import { AuthProvider, useAuth } from './auth/AuthContext';
import { RequestMagicLink } from './auth/RequestMagicLink';
import { VerifyMagicLink } from './auth/VerifyMagicLink';
import { RenterDashboard } from './renter/RenterDashboard';
import { LandlordDashboard } from './landlord/LandlordDashboard';

function Home() {
  const { user, logout } = useAuth();

  if (!user) return <Navigate to="/login" replace />;

  return (
    <div>
      <header>
        <span>{user.email}</span>
        <button onClick={logout}>Log out</button>
      </header>
      {user.role === 'renter' ? <RenterDashboard /> : <LandlordDashboard />}
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
