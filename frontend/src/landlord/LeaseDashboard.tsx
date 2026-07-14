import { useEffect, useState } from 'react';
import { apiFetch } from '../api/client';
import { formatUserName } from '../api/format';
import type {
  DrivenDayLog,
  Invoice,
  Lease,
  MileageProfile,
  User,
} from '../api/types';
import { InvoiceStatusBadge } from '../components/InvoiceStatusBadge';
import { DrivenDaysCalendar } from './DrivenDaysCalendar';
import { EditRent } from './EditRent';
import { GenerateInvoice } from './GenerateInvoice';
import { LeaseSettings } from './LeaseSettings';
import { LogDrivenDay } from './LogDrivenDay';

/** Formats a renter's name (if set) and email for display. */
function formatRenter(renter: User): string {
  const name = formatUserName(renter);
  return name === renter.email ? name : `${name} (${renter.email})`;
}

/**
 * Manages a single lease: rent/renter summary, optional gas billing
 * settings (mileage profile, gas price), driven-day logging (shown
 * once a mileage profile exists), and invoice generation.
 * @param props.lease - The lease to manage.
 * @param props.onBackHandlerChange - Called whenever the active
 *   sub-view changes, with a handler that closes it (or null when no
 *   sub-view is open) so the shared header can render a matching
 *   "back to dashboard" control.
 */
export function LeaseDashboard({
  lease,
  onBackHandlerChange,
}: {
  lease: Lease;
  onBackHandlerChange: (handler: (() => void) | null) => void;
}) {
  const [logs, setLogs] = useState<DrivenDayLog[]>([]);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [mileageProfile, setMileageProfile] = useState<MileageProfile | null>(
    null
  );
  const [showGasSettings, setShowGasSettings] = useState(false);
  const [showGenerateInvoice, setShowGenerateInvoice] = useState(false);
  const [showEditRent, setShowEditRent] = useState(false);
  const [showLogDrivenDay, setShowLogDrivenDay] = useState(false);

  useEffect(() => {
    apiFetch<DrivenDayLog[]>('/api/driven-days/').then((allLogs) =>
      setLogs(allLogs.filter((log) => log.renter === lease.renter))
    );
    apiFetch<Invoice[]>('/api/invoices/').then((allInvoices) =>
      setInvoices(
        allInvoices.filter(
          (inv) => inv.billing_period.renter === lease.renter
        )
      )
    );
  }, [lease.renter]);

  useEffect(() => {
    apiFetch<MileageProfile[]>('/api/mileage-profiles/').then((profiles) =>
      setMileageProfile(
        profiles.find((profile) => profile.renter === lease.renter) ?? null
      )
    );
  }, [lease.renter, showGasSettings]);

  useEffect(() => {
    if (showEditRent) {
      onBackHandlerChange(() => setShowEditRent(false));
    } else if (showGenerateInvoice) {
      onBackHandlerChange(() => setShowGenerateInvoice(false));
    } else if (showGasSettings) {
      onBackHandlerChange(() => setShowGasSettings(false));
    } else if (showLogDrivenDay) {
      onBackHandlerChange(() => setShowLogDrivenDay(false));
    } else {
      onBackHandlerChange(null);
    }
    return () => onBackHandlerChange(null);
  }, [
    showEditRent,
    showGenerateInvoice,
    showGasSettings,
    showLogDrivenDay,
    onBackHandlerChange,
  ]);

  return (
    <div className="lease-dashboard">
      <div className="stat-grid">
        <div className="stat-tile">
          <div className="stat-tile__header">
            <span className="stat-tile__label">Monthly rent</span>
            {!showEditRent && (
              <button
                type="button"
                className="stat-tile__edit"
                onClick={() => setShowEditRent(true)}
              >
                Edit
              </button>
            )}
          </div>
          <span className="stat-tile__value">
            ${lease.current_monthly_rent}
          </span>
        </div>

        <div className="stat-tile">
          <span className="stat-tile__label">Renter</span>
          <span className="stat-tile__value">
            {formatRenter(lease.renter_detail)}
          </span>
        </div>

        <div className="stat-tile">
          <div className="stat-tile__header">
            <span className="stat-tile__label">Mileage profile</span>
            {!showGasSettings && (
              <button
                type="button"
                className="stat-tile__edit"
                onClick={() => setShowGasSettings(true)}
              >
                {mileageProfile ? 'Edit' : 'Set up'}
              </button>
            )}
          </div>
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

      {showEditRent && (
        <section className="card">
          <div className="card__header">
            <h2>Edit rent</h2>
          </div>
          <EditRent
            leaseId={lease.id}
            onScheduled={() => setShowEditRent(false)}
            onCancel={() => setShowEditRent(false)}
          />
        </section>
      )}

      {showGasSettings && (
        <section className="card">
          <div className="card__header">
            <h2>Gas billing settings</h2>
          </div>
          <LeaseSettings renterId={lease.renter} />
        </section>
      )}

      {mileageProfile && (
        <section className="card">
          <div className="card__header">
            <h2>Renter's logged days</h2>
            {!showLogDrivenDay && (
              <button
                type="button"
                onClick={() => setShowLogDrivenDay(true)}
              >
                Log a day
              </button>
            )}
          </div>
          {showLogDrivenDay && (
            <LogDrivenDay
              renterId={lease.renter}
              onLogged={(log) => {
                setLogs(
                  [...logs, log].sort((a, b) => a.date.localeCompare(b.date))
                );
                setShowLogDrivenDay(false);
              }}
            />
          )}
          <DrivenDaysCalendar logs={logs} />
        </section>
      )}

      <section className="card">
        <div className="card__header">
          <h2>Invoices</h2>
          {!showGenerateInvoice && (
            <button
              type="button"
              onClick={() => setShowGenerateInvoice(true)}
            >
              Generate invoice
            </button>
          )}
        </div>
        {showGenerateInvoice && (
          <GenerateInvoice
            renterId={lease.renter}
            onGenerated={(invoice) => {
              setInvoices([invoice, ...invoices]);
              setShowGenerateInvoice(false);
            }}
          />
        )}
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
                  <InvoiceStatusBadge status={invoice.status} />
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}
