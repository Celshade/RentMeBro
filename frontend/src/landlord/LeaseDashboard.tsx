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
 * (mileage profile, gas price, logged days), and invoice generation.
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
  const [gasBillingEnabled, setGasBillingEnabled] = useState(false);
  const [showGenerateInvoice, setShowGenerateInvoice] = useState(false);
  const [showEditRent, setShowEditRent] = useState(false);

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
      setGasBillingEnabled(
        profiles.some((profile) => profile.renter === lease.renter)
      )
    );
  }, [lease.renter]);

  useEffect(() => {
    if (showEditRent) {
      onBackHandlerChange(() => setShowEditRent(false));
    } else if (showGenerateInvoice) {
      onBackHandlerChange(() => setShowGenerateInvoice(false));
    } else if (gasBillingEnabled) {
      onBackHandlerChange(() => setGasBillingEnabled(false));
    } else {
      onBackHandlerChange(null);
    }
    return () => onBackHandlerChange(null);
  }, [
    showEditRent,
    showGenerateInvoice,
    gasBillingEnabled,
    onBackHandlerChange,
  ]);

  return (
    <div>
      <p>
        Monthly rent: ${lease.current_monthly_rent} — Renter:{' '}
        {formatRenter(lease.renter_detail)}
      </p>

      {showEditRent ? (
        <EditRent
          leaseId={lease.id}
          onScheduled={() => setShowEditRent(false)}
          onCancel={() => setShowEditRent(false)}
        />
      ) : (
        <button type="button" onClick={() => setShowEditRent(true)}>
          Edit rent
        </button>
      )}

      {gasBillingEnabled ? (
        <>
          <LeaseSettings renterId={lease.renter} />

          <h2>Renter's logged days</h2>
          <LogDrivenDay
            renterId={lease.renter}
            onLogged={(log) =>
              setLogs(
                [...logs, log].sort((a, b) => a.date.localeCompare(b.date))
              )
            }
          />
          <ul>
            {logs.map((log) => (
              <li key={log.id}>
                {log.date} — {log.day_fraction} day
                {log.note ? ` (${log.note})` : ''}
              </li>
            ))}
          </ul>
        </>
      ) : (
        <button type="button" onClick={() => setGasBillingEnabled(true)}>
          Set up gas billing
        </button>
      )}

      {showGenerateInvoice ? (
        <GenerateInvoice
          renterId={lease.renter}
          onGenerated={(invoice) => {
            setInvoices([invoice, ...invoices]);
            setShowGenerateInvoice(false);
          }}
        />
      ) : (
        <button type="button" onClick={() => setShowGenerateInvoice(true)}>
          Generate invoice
        </button>
      )}

      <h2>Invoices</h2>
      <ul>
        {invoices.map((invoice) => {
          const month = String(invoice.billing_period.month).padStart(
            2,
            '0'
          );
          return (
            <li key={invoice.id}>
              {invoice.billing_period.year}-{month}
              {' — '}
              {invoice.kind} — ${invoice.total}{' '}
              <InvoiceStatusBadge status={invoice.status} />
            </li>
          );
        })}
      </ul>
    </div>
  );
}
