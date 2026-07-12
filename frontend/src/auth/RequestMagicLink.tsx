import { useState, type FormEvent } from 'react';
import type { Role } from '../api/types';
import { useAuth } from './AuthContext';

/** Login screen: renter/landlord enters their email to receive a link. */
export function RequestMagicLink() {
  const { requestMagicLink, loading } = useAuth();
  const [email, setEmail] = useState('');
  const [role, setRole] = useState<Role>('renter');
  const [sent, setSent] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    await requestMagicLink(email, role);
    setSent(true);
  }

  if (sent) {
    return <p>If that email has an account, a sign-in link is on its way.</p>;
  }

  return (
    <form onSubmit={handleSubmit}>
      <h1>Sign in to RentMeBro</h1>
      <fieldset>
        <legend>I am signing in as a</legend>
        <label>
          <input
            type="radio"
            name="role"
            value="renter"
            checked={role === 'renter'}
            onChange={() => setRole('renter')}
          />
          Renter
        </label>
        <label>
          <input
            type="radio"
            name="role"
            value="landlord"
            checked={role === 'landlord'}
            onChange={() => setRole('landlord')}
          />
          Landlord
        </label>
      </fieldset>
      <label htmlFor="email">Email</label>
      <input
        id="email"
        type="email"
        required
        value={email}
        onChange={(e) => setEmail(e.target.value)}
      />
      <button type="submit" disabled={loading}>
        Send sign-in link
      </button>
    </form>
  );
}
