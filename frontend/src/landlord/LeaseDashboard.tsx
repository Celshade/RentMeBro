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
  gasChargeIsFrozen,
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
import { DrivenDaysCalendar } from './DrivenDaysCalendar';
import { EditRent } from './EditRent';
import { GenerateInvoice } from './GenerateInvoice';
import { LeaseSettings } from './LeaseSettings';
import { LogDrivenDay } from './LogDrivenDay';

/** How many invoices show before the list collapses behind "Show all". */
const COLLAPSED_INVOICE_COUNT = 3;

/** Mirrors the API's ordering so a locally-inserted invoice stays in place. */
function sortInvoices(list: Invoice[]): Invoice[] {
  return [...list].sort((a, b) => {
    if (a.billing_period.year !== b.billing_period.year) {
      return b.billing_period.year - a.billing_period.year;
    }
    if (a.billing_period.month !== b.billing_period.month) {
      return b.billing_period.month - a.billing_period.month;
    }
    return (
      new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
    );
  });
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
  const [priceEntries, setPriceEntries] = useState<GasPriceEntry[]>([]);
  const [showGasSettings, setShowGasSettings] = useState(false);
  const [showGenerateInvoice, setShowGenerateInvoice] = useState(false);
  const [showEditRent, setShowEditRent] = useState(false);
  const [editingInvoiceId, setEditingInvoiceId] = useState<number | null>(
    null
  );
  const [savingInvoiceEdit, setSavingInvoiceEdit] = useState(false);
  const [invoiceEditError, setInvoiceEditError] = useState<string | null>(
    null
  );
  const [logDayTarget, setLogDayTarget] = useState<{
    dates: string[];
    logs: (DrivenDayLog | null)[];
  } | null>(null);
  const [bulkSelectMode, setBulkSelectMode] = useState(false);
  const [selectedDates, setSelectedDates] = useState<Set<string>>(new Set());
  const [weekPriceRange, setWeekPriceRange] = useState<{
    from: string;
    to: string;
  } | null>(null);
  const [showAllInvoices, setShowAllInvoices] = useState(false);

  function toggleSelectedDate(date: string) {
    setSelectedDates((prev) => {
      const next = new Set(prev);
      if (next.has(date)) {
        next.delete(date);
      } else {
        next.add(date);
      }
      return next;
    });
  }

  function cancelBulkSelect() {
    setBulkSelectMode(false);
    setSelectedDates(new Set());
  }

  function closeGasSettings() {
    setShowGasSettings(false);
    setWeekPriceRange(null);
  }

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
    apiFetch<GasPriceEntry[]>('/api/gas-price-entries/').then((entries) =>
      setPriceEntries(entries.filter((entry) => entry.renter === lease.renter))
    );
  }, [lease.renter, showGasSettings]);

  useEffect(() => {
    if (showEditRent) {
      onBackHandlerChange(() => setShowEditRent(false));
    } else if (showGenerateInvoice) {
      onBackHandlerChange(() => setShowGenerateInvoice(false));
    } else if (showGasSettings) {
      onBackHandlerChange(() => closeGasSettings());
    } else if (logDayTarget) {
      onBackHandlerChange(() => setLogDayTarget(null));
    } else if (bulkSelectMode) {
      onBackHandlerChange(() => cancelBulkSelect());
    } else {
      onBackHandlerChange(null);
    }
    return () => onBackHandlerChange(null);
  }, [
    showEditRent,
    showGenerateInvoice,
    showGasSettings,
    logDayTarget,
    bulkSelectMode,
    onBackHandlerChange,
  ]);

  useEffect(() => {
    const editingInvoice = invoices.find(
      (invoice) => invoice.id === editingInvoiceId
    );
    if (editingInvoice && gasChargeIsFrozen(editingInvoice)) {
      setEditingInvoiceId(null);
    }
  }, [invoices, editingInvoiceId]);

  const lockedMonths = new Set(
    invoices
      .filter(
        (invoice) =>
          invoice.kind !== 'rent_only' &&
          (invoice.id !== editingInvoiceId || gasChargeIsFrozen(invoice))
      )
      .map(
        (invoice) =>
          `${invoice.billing_period.year}-` +
          `${String(invoice.billing_period.month).padStart(2, '0')}`
      )
  );

  async function handleDeleteInvoice(invoice: Invoice) {
    const confirmed = window.confirm(
      `Delete the ${formatBillingPeriod(
        invoice.billing_period.month,
        invoice.billing_period.year
      )} ${formatInvoiceKind(invoice.kind)} invoice? This cannot be undone.`
    );
    if (!confirmed) return;
    await apiFetch(`/api/invoices/${invoice.id}/`, { method: 'DELETE' });
    setInvoices(invoices.filter((inv) => inv.id !== invoice.id));
  }

  async function handleSendInvoice(invoiceId: number) {
    const updated = await apiFetch<Invoice>(
      `/api/invoices/${invoiceId}/send/`,
      { method: 'POST' }
    );
    setInvoices(
      invoices.map((invoice) =>
        invoice.id === updated.id ? updated : invoice
      )
    );
  }

  async function handleSaveInvoiceEdit(invoiceId: number) {
    setSavingInvoiceEdit(true);
    setInvoiceEditError(null);
    try {
      const updated = await apiFetch<Invoice>(
        `/api/invoices/${invoiceId}/recompute/`,
        { method: 'POST' }
      );
      setInvoices(
        invoices.map((invoice) =>
          invoice.id === updated.id ? updated : invoice
        )
      );
      setEditingInvoiceId(null);
    } catch (err) {
      setInvoiceEditError(
        err instanceof Error ? err.message : 'Failed to apply mileage.'
      );
    } finally {
      setSavingInvoiceEdit(false);
    }
  }

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
          <span className="stat-tile__label">Renter</span>
          <span className="stat-tile__value">
            {formatUserWithEmail(lease.renter_detail)}
          </span>
        </div>

        <div className="stat-tile">
          <div className="stat-tile__header">
            <span className="stat-tile__label">Mileage profile</span>
            {!showGasSettings && (
              <button
                type="button"
                className="stat-tile__edit"
                onClick={() => {
                  setWeekPriceRange(null);
                  setShowGasSettings(true);
                }}
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
            <h2>
              {weekPriceRange
                ? 'Gas price for this week'
                : 'Gas billing settings'}
            </h2>
          </div>
          <LeaseSettings
            renterId={lease.renter}
            section={weekPriceRange ? 'price' : 'both'}
            presetRange={weekPriceRange}
            onCancel={closeGasSettings}
          />
        </section>
      )}

      <div className="dashboard-columns">
        {mileageProfile && (
          <section className="card">
            <div className="card__header">
              <h2>Mileage Log</h2>
              {!logDayTarget && !bulkSelectMode && (
                <span className="dashboard-toolbar__actions">
                  <button
                    type="button"
                    onClick={() =>
                      setLogDayTarget({ dates: [''], logs: [null] })
                    }
                  >
                    Log a Day
                  </button>
                  <button
                    type="button"
                    onClick={() => setBulkSelectMode(true)}
                  >
                    Log Multiple Days
                  </button>
                </span>
              )}
              {bulkSelectMode && !logDayTarget && (
                <span className="dashboard-toolbar__actions">
                  <button
                    type="button"
                    disabled={selectedDates.size === 0}
                    onClick={() => {
                      const dates = [...selectedDates].sort();
                      setLogDayTarget({
                        dates,
                        logs: dates.map(
                          (d) => logs.find((l) => l.date === d) ?? null
                        ),
                      });
                    }}
                  >
                    Log {selectedDates.size} selected day
                    {selectedDates.size === 1 ? '' : 's'}
                  </button>
                  <button type="button" onClick={cancelBulkSelect}>
                    Cancel
                  </button>
                </span>
              )}
            </div>
            {logDayTarget && (
              <LogDrivenDay
                key={logDayTarget.dates.join(',')}
                renterId={lease.renter}
                dates={logDayTarget.dates}
                existingLogs={logDayTarget.logs}
                onSaved={(savedLogs) => {
                  const savedIds = new Set(savedLogs.map((l) => l.id));
                  setLogs(
                    [
                      ...logs.filter((l) => !savedIds.has(l.id)),
                      ...savedLogs,
                    ].sort((a, b) => a.date.localeCompare(b.date))
                  );
                  setLogDayTarget(null);
                  cancelBulkSelect();
                }}
                onDeleted={(logId) => {
                  setLogs(logs.filter((l) => l.id !== logId));
                  setLogDayTarget(null);
                }}
                onCancel={() => setLogDayTarget(null)}
              />
            )}
            <DrivenDaysCalendar
              logs={logs}
              onDayClick={
                bulkSelectMode
                  ? undefined
                  : (date, log) =>
                      setLogDayTarget({ dates: [date], logs: [log] })
              }
              selectedDates={bulkSelectMode ? selectedDates : undefined}
              onToggleDate={bulkSelectMode ? toggleSelectedDate : undefined}
              onSetWeekPrice={(from, to) => {
                setWeekPriceRange({ from, to });
                setShowGasSettings(true);
              }}
              pricedWeekRanges={priceEntries.map((entry) => ({
                from: entry.effective_from,
                to: entry.effective_to,
                price_per_gallon: entry.price_per_gallon,
              }))}
              lockedMonths={lockedMonths}
            />
            <DrivenDaysCalendarKey />
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
                Generate Invoice
              </button>
            )}
          </div>
          {showGenerateInvoice && (
            <GenerateInvoice
              renterId={lease.renter}
              onGenerated={(invoice) => {
                setInvoices(sortInvoices([invoice, ...invoices]));
                setShowGenerateInvoice(false);
              }}
              onCancel={() => setShowGenerateInvoice(false)}
            />
          )}
          {invoices.length === 0 ? (
            <p className="empty-state">No invoices yet.</p>
          ) : (
            <ul className="list">
              {(showAllInvoices || editingInvoiceId !== null
                ? invoices
                : invoices.slice(0, COLLAPSED_INVOICE_COUNT)
              ).map((invoice) => {
                const isLocked =
                  invoice.status === 'paid' ||
                  invoice.status === 'void' ||
                  gasChargeIsFrozen(invoice);
                const isEditing = editingInvoiceId === invoice.id;
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
                      {invoice.status === 'draft' && (
                        <button
                          type="button"
                          onClick={() => handleSendInvoice(invoice.id)}
                        >
                          Send invoice
                        </button>
                      )}
                      {(invoice.status === 'draft' ||
                        invoice.status === 'sent' ||
                        invoice.status === 'void') &&
                        invoice.settlements.length === 0 &&
                        invoice.frozen_line_items.length === 0 && (
                          <button
                            type="button"
                            onClick={() => handleDeleteInvoice(invoice)}
                          >
                            Delete
                          </button>
                        )}
                      {!isLocked && invoice.kind !== 'rent_only' && (
                        isEditing ? (
                          <>
                            <button
                              type="button"
                              disabled={savingInvoiceEdit}
                              onClick={() =>
                                handleSaveInvoiceEdit(invoice.id)
                              }
                            >
                              Apply to invoice
                            </button>
                            <button
                              type="button"
                              disabled={savingInvoiceEdit}
                              onClick={() => {
                                setEditingInvoiceId(null);
                                setInvoiceEditError(null);
                              }}
                            >
                              Cancel
                            </button>
                            {invoiceEditError && (
                              <span role="alert">{invoiceEditError}</span>
                            )}
                          </>
                        ) : (
                          <button
                            type="button"
                            onClick={() => setEditingInvoiceId(invoice.id)}
                          >
                            Correct mileage
                          </button>
                        )
                      )}
                    </span>
                  </li>
                );
              })}
            </ul>
          )}
          {invoices.length > COLLAPSED_INVOICE_COUNT &&
            editingInvoiceId === null && (
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
