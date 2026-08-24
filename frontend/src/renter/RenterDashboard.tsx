import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { apiFetch } from '../api/client';
import {
  formatBillingPeriod,
  formatInvoiceKind,
  formatUserWithEmail,
} from '../api/format';
import type {
  DrivenDayLog,
  GasPriceEntry,
  Invoice,
  Lease,
  MileageProfile,
} from '../api/types';
import {
  amountDueUsd,
  paymentRails,
  railCoverage,
  railCoverageLabel,
  settledAmountUsd,
  settledRailLabel,
  settledRails,
} from '../api/invoice';
import { DrivenDaysCalendarKey } from '../components/DrivenDaysCalendarKey';
import { InvoiceStatusBadge } from '../components/InvoiceStatusBadge';
import {
  PaymentRailGlyph,
  SettledCheckmark,
} from '../components/PaymentRailGlyph';
import { DrivenDaysCalendar } from '../landlord/DrivenDaysCalendar';
import { PayInvoice } from './PayInvoice';


/** How many invoices show before the list collapses behind "Show all". */
const COLLAPSED_INVOICE_COUNT = 3;


/**
 * Renter's home screen: a read-only mirror of the landlord's lease
 * view (landlord identity, mileage profile, logged-days calendar)
 * plus the ability to pay invoices.
 * @param props.onBackHandlerChange - Called whenever the renter opens
 *   or closes the pay-invoice panel, with a handler that closes it (or
 *   null when none is open) so the shared header can render a matching
 *   "back to dashboard" control.
 */
export function RenterDashboard({
  onBackHandlerChange,
}: {
  onBackHandlerChange: (handler: (() => void) | null) => void;
}) {
  const [lease, setLease] = useState<Lease | null>(null);
  const [logs, setLogs] = useState<DrivenDayLog[]>([]);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [mileageProfile, setMileageProfile] = useState<MileageProfile | null>(
    null
  );
  const [priceEntries, setPriceEntries] = useState<GasPriceEntry[]>([]);
  const [payingInvoiceId, setPayingInvoiceId] = useState<number | null>(null);
  const [showAllInvoices, setShowAllInvoices] = useState(false);
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
      apiFetch<GasPriceEntry[]>('/api/gas-price-entries/').then(
        setPriceEntries
      ),
    ])
      .catch(() => setError('Could not load your rental. Try refreshing.'))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (payingInvoiceId !== null) {
      onBackHandlerChange(() => setPayingInvoiceId(null));
    } else {
      onBackHandlerChange(null);
    }
    return () => onBackHandlerChange(null);
  }, [payingInvoiceId, onBackHandlerChange]);

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
          {lease.current_monthly_rent !== lease.monthly_rent && (
            <span className="stat-tile__meta">
              Revised from ${lease.monthly_rent}
            </span>
          )}
          {lease.pending_rent_revision && (
            <span className="stat-tile__meta">
              Pending: ${lease.pending_rent_revision.new_monthly_rent}{' '}
              effective {lease.pending_rent_revision.effective_date}
            </span>
          )}
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
              <h2>Mileage Log</h2>
            </div>
            <DrivenDaysCalendar
              logs={logs}
              pricedWeekRanges={priceEntries.map((entry) => ({
                from: entry.effective_from,
                to: entry.effective_to,
                price_per_gallon: entry.price_per_gallon,
              }))}
            />
            <DrivenDaysCalendarKey />
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
              {(showAllInvoices || payingInvoiceId !== null
                ? invoices
                : invoices.slice(0, COLLAPSED_INVOICE_COUNT)
              ).map((invoice) => {
                const rails = paymentRails(invoice);
                const coverage = railCoverage(invoice);
                const settled = settledRails(invoice);
                const isPaid = invoice.status === 'paid';
                return (
                  <li key={invoice.id} className="list-row">
                    <span>
                      <span className="list-row__rails">
                        {isPaid &&
                          settled.map((rail) => (
                            <PaymentRailGlyph
                              key={rail}
                              rail={rail}
                              settled
                              label={settledRailLabel(rail)}
                            />
                          ))}
                        {isPaid && settled.length > 0 && (
                          <SettledCheckmark />
                        )}
                        {rails.btc && (
                          <PaymentRailGlyph
                            rail="btc"
                            label={railCoverageLabel('btc', coverage.btc)}
                          />
                        )}
                        {rails.card && (
                          <PaymentRailGlyph
                            rail="card"
                            label={railCoverageLabel('card', coverage.card)}
                          />
                        )}
                      </span>
                      <strong>
                        {formatBillingPeriod(
                          invoice.billing_period.month,
                          invoice.billing_period.year
                        )}
                        : {formatInvoiceKind(invoice.kind)}
                      </strong>{' '}
                      — ${invoice.total}
                      {!isPaid && settled.length > 0 && (
                        <span className="list-row__remaining">
                          (${amountDueUsd(invoice)} remaining)
                        </span>
                      )}
                      <span className="list-row__due">
                        due {invoice.due_date}
                        {!isPaid && settled.length > 0 && (
                          <span className="list-row__paid-note">
                            — ${settledAmountUsd(invoice)} paid
                            {settled.map((rail) => (
                              <PaymentRailGlyph
                                key={rail}
                                rail={rail}
                                settled
                                label={settledRailLabel(rail)}
                              />
                            ))}
                          </span>
                        )}
                      </span>
                    </span>
                    <span
                      className={
                        'renter-dashboard__invoice-actions ' +
                        'list-row__actions--own-line'
                      }
                    >
                      <InvoiceStatusBadge
                        status={invoice.status}
                        isLate={invoice.is_late}
                        remainderOwedUsd={invoice.remainder_owed_usd}
                        overpaidUsd={invoice.btc_overpaid_usd}
                      />
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
                      <div className="list-row__pay-panel">
                        <PayInvoice
                          invoice={invoice}
                          onPaid={() => {
                            setPayingInvoiceId(null);
                            apiFetch<Invoice[]>('/api/invoices/').then(
                              setInvoices
                            );
                          }}
                        />
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
          {invoices.length > COLLAPSED_INVOICE_COUNT &&
            payingInvoiceId === null && (
              <button
                type="button"
                onClick={() => setShowAllInvoices((show) => !show)}
              >
                {showAllInvoices
                  ? 'Show fewer'
                  : `Show all (${invoices.length})`}
              </button>
            )}
        </section>
      </div>
    </div>
  );
}
