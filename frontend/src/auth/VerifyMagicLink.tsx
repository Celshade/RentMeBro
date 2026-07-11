import { useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from './AuthContext';

/** Exchanges the ?token= query param from the emailed link for a session. */
export function VerifyMagicLink() {
  const [searchParams] = useSearchParams();
  const { verifyMagicLink } = useAuth();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const attempted = useRef(false);

  useEffect(() => {
    const token = searchParams.get('token');
    if (!token || attempted.current) return;
    attempted.current = true;

    verifyMagicLink(token)
      .then(() => navigate('/'))
      .catch((err: Error) => setError(err.message));
  }, [searchParams, verifyMagicLink, navigate]);

  if (error) {
    return <p>Sign-in link is invalid or expired: {error}</p>;
  }
  return <p>Signing you in...</p>;
}
