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
 * @param props.gasBillingEnabled - Whether the gas-billing section is
 *   expanded.
 * @param props.onGasBillingEnabledChange - Called to expand/collapse the
 *   gas-billing section; the caller renders the matching "back to
 *   dashboard" control in the shared header.
 */
export function LeaseDashboard({
  lease,
  gasBillingEnabled,
  onGasBillingEnabledChange,
}: {
  lease: Lease;
  gasBillingEnabled: boolean;
  onGasBillingEnabledChange: (enabled: boolean) => void;
}) {
  const [logs, setLogs] = useState<DrivenDayLog[]>([]);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [showGenerateInvoice, setShowGenerateInvoice] = useState(false);

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
      onGasBillingEnabledChange(
        profiles.some((profile) => profile.renter === lease.renter)
      )
    );
  }, [lease.renter, onGasBillingEnabledChange]);

  return (
    <div>
      <p>
        Monthly rent: ${lease.monthly_rent} — Renter:{' '}
        {formatRenter(lease.renter_detail)}
      </p>

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
        <button type="button" onClick={() => onGasBillingEnabledChange(true)}>
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
