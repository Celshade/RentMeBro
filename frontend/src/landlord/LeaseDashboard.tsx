import { useEffect, useState } from 'react';
import { apiFetch } from '../api/client';
import { formatUserWithEmail } from '../api/format';
import type { DrivenDayLog, Invoice, Lease, MileageProfile } from '../api/types';
import { InvoiceStatusBadge } from '../components/InvoiceStatusBadge';
import { DrivenDaysCalendar } from './DrivenDaysCalendar';
import { EditRent } from './EditRent';
import { GenerateInvoice } from './GenerateInvoice';
import { LeaseSettings } from './LeaseSettings';
import { LogDrivenDay } from './LogDrivenDay';

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
            <h2>Gas billing settings</h2>
          </div>
          <LeaseSettings
            renterId={lease.renter}
            presetRange={weekPriceRange}
            onCancel={closeGasSettings}
          />
        </section>
      )}

      <div className="dashboard-columns">
        {mileageProfile && (
          <section className="card">
            <div className="card__header">
              <h2>Renter's logged days</h2>
              {!logDayTarget && !bulkSelectMode && (
                <span className="dashboard-toolbar__actions">
                  <button
                    type="button"
                    onClick={() =>
                      setLogDayTarget({ dates: [''], logs: [null] })
                    }
                  >
                    Log a day
                  </button>
                  <button
                    type="button"
                    onClick={() => setBulkSelectMode(true)}
                  >
                    Log multiple days
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
            />
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
                      {invoice.billing_period.year}-{month}
                      {' — '}
                      {invoice.kind} — ${invoice.total}
                    </span>
                    <InvoiceStatusBadge status={invoice.status} />
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
