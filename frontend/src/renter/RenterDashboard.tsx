import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { apiFetch } from '../api/client';
import { formatUserWithEmail } from '../api/format';
import type {
  DrivenDayLog,
  Invoice,
  Lease,
  MileageProfile,
} from '../api/types';
import { InvoiceStatusBadge } from '../components/InvoiceStatusBadge';
import { DrivenDaysCalendar } from '../landlord/DrivenDaysCalendar';
import { PayInvoice } from './PayInvoice';


/**
 * Renter's home screen: a read-only mirror of the landlord's lease
 * view (landlord identity, mileage profile, logged-days calendar)
 * plus the ability to pay invoices.
 */
export function RenterDashboard() {
  const [lease, setLease] = useState<Lease | null>(null);
  const [logs, setLogs] = useState<DrivenDayLog[]>([]);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [mileageProfile, setMileageProfile] = useState<MileageProfile | null>(
    null
  );
  const [payingInvoiceId, setPayingInvoiceId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      apiFetch<Lease[]>('/api/leases/').then(
        (leases) => setLease(leases[0] ?? null)
      ),
      apiFetch<DrivenDayLog[]>('/api/driven-days/').then(setLogs),
      apiFetch<Invoice[]>('/api/invoices/').then(setInvoices),
      apiFetch<MileageProfile[]>('/api/mileage-profiles/').then(
        (profiles) => setMileageProfile(profiles[0] ?? null)
      ),
    ])
      .catch(() => setError('Could not load your rental. Try refreshing.'))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p className="empty-state">Loading your rental…</p>;
  if (error) return <p className="empty-state">{error}</p>;
  if (!lease) return <p className="empty-state">No active lease found.</p>;

  return (
    <div className="renter-dashboard">
      <h1>Your rental</h1>

      <div className="stat-grid">
        <div className="stat-tile">
          <span className="stat-tile__label">Monthly rent</span>
          <span className="stat-tile__value">
            ${lease.current_monthly_rent}
          </span>
        </div>

        <div className="stat-tile">
          <span className="stat-tile__label">Landlord</span>
          <span className="stat-tile__value">
            {formatUserWithEmail(lease.landlord_detail)}
          </span>
        </div>

        <div className="stat-tile">
          <span className="stat-tile__label">Mileage profile</span>
          {mileageProfile ? (
            <>
              <span className="stat-tile__value">
                {mileageProfile.one_way_miles} mi one-way,{' '}
                {mileageProfile.mpg} MPG
              </span>
              <span className="stat-tile__meta">
                Effective {mileageProfile.effective_from}
              </span>
            </>
          ) : (
            <span className="stat-tile__value stat-tile__value--muted">
              Not set up
            </span>
          )}
        </div>
      </div>

      <div className="dashboard-columns">
        {mileageProfile && (
          <section className="card">
            <div className="card__header">
              <h2>Mileage log</h2>
            </div>
            <DrivenDaysCalendar logs={logs} />
          </section>
        )}

        <section className="card">
          <div className="card__header">
            <h2>Invoices</h2>
          </div>
          {invoices.length === 0 ? (
            <p className="empty-state">No invoices yet.</p>
          ) : (
            <ul className="list">
              {invoices.map((invoice) => {
                const month = String(invoice.billing_period.month).padStart(
                  2,
                  '0'
                );
                return (
                  <li key={invoice.id} className="list-row">
                    <span>
                      {invoice.billing_period.year}-{month} — {invoice.kind} —
                      ${invoice.total}
                    </span>
                    <span className="renter-dashboard__invoice-actions">
                      <InvoiceStatusBadge status={invoice.status} />
                      <Link to={`/invoices/${invoice.id}`}>Details</Link>
                      {invoice.status !== 'paid' && (
                        <button
                          type="button"
                          onClick={() => setPayingInvoiceId(invoice.id)}
                        >
                          Pay
                        </button>
                      )}
                    </span>
                    {payingInvoiceId === invoice.id && (
                      <PayInvoice
                        invoiceId={invoice.id}
                        onPaid={() => {
                          setPayingInvoiceId(null);
                          apiFetch<Invoice[]>('/api/invoices/').then(
                            setInvoices
                          );
                        }}
                      />
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}
