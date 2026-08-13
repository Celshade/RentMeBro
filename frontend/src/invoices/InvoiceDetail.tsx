import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { apiFetch } from '../api/client';
import {
  formatBillingPeriod,
  formatInvoiceKind,
  formatMoney,
  satsToBtc,
  usdToBtc,
} from '../api/format';
import {
  isLineItemFrozen,
  isLineItemPaid,
  lineItemRails,
  paymentRails,
  railCoverage,
  railCoverageLabel,
  settlementForLineItem,
} from '../api/invoice';
import type {
  BtcSettings,
  DrivenDayLog,
  Invoice,
  InvoiceWeek,
  InvoiceWeekDay,
  PaymentLock,
} from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { BtcTxLink } from '../components/BtcTxLink';
import { DrivenDaysCalendarKey } from '../components/DrivenDaysCalendarKey';
import { InvoiceStatusBadge } from '../components/InvoiceStatusBadge';
import { PaymentRailGlyph } from '../components/PaymentRailGlyph';
import { DrivenDaysCalendar } from '../landlord/DrivenDaysCalendar';

// Only a whole-invoice settle/void locks everything; a not-yet-fully
// paid invoice may still have individually re-scopable line items --
// see `isLineItemFrozen` for the per-item check.
const LOCKED_STATUSES = new Set(['paid', 'void']);

/** Extracts a server-thrown Error's message, falling back to a generic one. */
function errorMessage(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback;
}


/**
 * Inline form letting a landlord attach a fixed BTC address/amount to
 * an invoice as a payment option, or remove one already attached,
 * shown only once BTC payments are enabled and the invoice isn't
 * already locked (paid/void/pending). Removing clears any line items
 * marked as BTC-billed along with the address. Surfaces the same
 * one-address-per-renter disclaimer shown when enabling BTC payments,
 * since a shared address makes tx matching ambiguous.
 * @param props.invoice - The invoice to attach or remove BTC payment
 *   info on.
 * @param props.onAttached - Called with the updated invoice once an
 *   attach or a removal succeeds.
 * @param props.nudge - When true, pulses the Attach button and shows
 *   an inline hint -- the landlord just tried to lock a charge to BTC
 *   with no address attached.
 * @param props.formRef - Forwarded to the underlying `<form>` so a
 *   caller can scroll it into view.
 */
function AttachBtcPaymentForm({
  invoice,
  onAttached,
  nudge = false,
  formRef,
}: {
  invoice: Invoice;
  onAttached: (invoice: Invoice) => void;
  nudge?: boolean;
  formRef?: React.RefObject<HTMLFormElement | null>;
}) {
  const [address, setAddress] = useState(invoice.btc_address);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [usdPerBtc, setUsdPerBtc] = useState<number | null>(null);

  useEffect(() => {
    apiFetch<{ usd: number }>('/api/payments/btc/price/')
      .then((data) => setUsdPerBtc(data.usd))
      .catch(() => setUsdPerBtc(null));
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      // Scopes every non-frozen item not hard-locked to card, mirroring
      // the payment-lock select's own Any-method/BTC-only behavior
      // instead of reproducing whatever (usually empty) scope existed
      // before an address was attached. A frozen item's scope can't be
      // touched at all, so it keeps whatever it already had.
      const lineItems = invoice.line_items
        .filter((item) =>
          isLineItemFrozen(invoice, item.id)
            ? invoice.btc_line_items.includes(item.id)
            : item.payment_lock !== 'card'
        )
        .map((item) => item.id);
      await apiFetch(`/api/invoices/${invoice.id}/btc/`, {
        method: 'POST',
        body: { address, line_items: lineItems },
      });
      // Re-read rather than patching locally: the split portions are
      // derived server-side, so this keeps them authoritative.
      onAttached(await apiFetch<Invoice>(`/api/invoices/${invoice.id}/`));
    } catch (err) {
      setError(errorMessage(err, 'Could not attach BTC address. Try again.'));
    } finally {
      setSubmitting(false);
    }
  }

  /**
   * Detaches BTC entirely: blanks the address and, since the backend
   * clears the scope along with it, drops any line items marked as
   * BTC-billed too.
   */
  async function handleRemove() {
    setSubmitting(true);
    setError(null);
    try {
      await apiFetch(`/api/invoices/${invoice.id}/btc/`, {
        method: 'POST',
        body: { address: '', line_items: [] },
      });
      setAddress('');
      onAttached(await apiFetch<Invoice>(`/api/invoices/${invoice.id}/`));
    } catch (err) {
      setError(errorMessage(err, 'Could not remove BTC address. Try again.'));
    } finally {
      setSubmitting(false);
    }
  }

  // A settled BTC payment can never be un-happened, and a BTC-locked
  // item would be stranded with no rail able to pay it -- see
  // attach_btc_payment's detach guard on the backend.
  const hasBtcSettlement = invoice.settlements.some((s) => s.rail === 'btc');
  const hasBtcLockedItem = invoice.line_items.some(
    (item) => item.payment_lock === 'btc'
  );
  const canRemove = !hasBtcSettlement && !hasBtcLockedItem;

  const estimatedBtc =
    usdPerBtc !== null
      ? usdToBtc(invoice.btc_portion_usd, usdPerBtc)
      : null;

  return (
    <form onSubmit={handleSubmit} className="btc-address-form" ref={formRef}>
      <p className="btc-address-disclaimer">
        Use a separate BTC address for each renter -- a shared address
        makes payments ambiguous to match and can misattribute one
        renter's payment to another's invoice.
      </p>
      <div className="btc-address-row">
        <label className="btc-address-row__field">
          BTC address
          <input
            type="text"
            value={address}
            onChange={(e) => setAddress(e.target.value)}
            required
          />
        </label>
        <div className="btc-address-row__actions">
          <button
            type="submit"
            className={
              nudge ? 'button--btc attach-nudge' : 'button--btc'
            }
            disabled={submitting}
          >
            {submitting ? 'Saving...' : 'Attach'}
          </button>
          {invoice.btc_address !== '' && canRemove && (
            <button
              type="button"
              className="button--btc"
              disabled={submitting}
              onClick={handleRemove}
            >
              Remove
            </button>
          )}
        </div>
      </div>
      {nudge && (
        <p className="btc-address-nudge-hint">
          Attach a BTC address before locking a charge to BTC.
        </p>
      )}
      {usdPerBtc !== null && (
        <p className="btc-price-hint">
          1 BTC ≈ ${usdPerBtc.toLocaleString()}
          {estimatedBtc !== null &&
            ` — the BTC portion's ${formatMoney(invoice.btc_portion_usd)} \
≈ ${estimatedBtc} BTC`}
          <span
            className="btc-price-hint__info"
            title={
              'Estimated BTC price taken from mempool.space; the actual ' +
              'amount the renter pays is generated and rate-locked at ' +
              'the time they initiate payment.'
            }
          >
            {' '}
            ⓘ
          </span>
        </p>
      )}
      {error && <p role="alert">{error}</p>}
    </form>
  );
}

/** Describes a logged day the way the mileage log form does, not as raw data. */
function formatDayDescription(day: InvoiceWeekDay): string {
  if (day.kind === 'day_off') return 'Day off';
  if (day.kind === 'other_ride') return 'Other ride';
  return Number(day.day_fraction) >= 0.75
    ? 'Full day (drop-off + pick-up)'
    : 'Half day (drop-off or pick-up only)';
}


/** Turns a week's per-day breakdown into calendar-shaped log entries. */
function weeksToLogs(weeks: InvoiceWeek[]): DrivenDayLog[] {
  const days = weeks.flatMap((week) => week.days);
  return days.map((day, index) => ({
    id: -(index + 1),
    landlord: 0,
    renter: 0,
    date: day.date,
    kind: day.kind,
    day_fraction: day.day_fraction,
    half_leg: '',
    note: '',
  }));
}


/** Turns a billed week's price into the `pricedWeekRanges` shape the
 * calendar's hover text expects. */
function weeksToPricedRanges(
  weeks: InvoiceWeek[]
): { from: string; to: string | null; price_per_gallon: string }[] {
  return weeks
    .filter((week) => week.price_per_gallon !== null)
    .map((week) => ({
      from: week.week_start,
      to: week.week_end,
      price_per_gallon: week.price_per_gallon as string,
    }));
}


/**
 * Full-page invoice detail: the mileage calendar for the billed month
 * alongside a week-by-week breakdown of miles driven and gas cost, for
 * both the renter and the landlord side of an invoice.
 * @param props.onBackHandlerChange - Registers the header's "Back to
 *   dashboard" handler for as long as this page is mounted.
 */
export function InvoiceDetail({
  onBackHandlerChange,
}: {
  onBackHandlerChange: (handler: (() => void) | null) => void;
}) {
  const { user } = useAuth();
  const navigate = useNavigate();
  const { invoiceId } = useParams<{ invoiceId: string }>();
  const [invoice, setInvoice] = useState<Invoice | null>(null);
  const [weeks, setWeeks] = useState<InvoiceWeek[]>([]);
  const [btcSettings, setBtcSettings] = useState<BtcSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lockingItemId, setLockingItemId] = useState<number | null>(null);
  const [lockError, setLockError] = useState<string | null>(null);
  const [nudgeAttach, setNudgeAttach] = useState(false);
  const [markPaidItemId, setMarkPaidItemId] = useState<number | null>(null);
  const [markPaidRail, setMarkPaidRail] = useState<'cash' | 'check' | 'other'>(
    'cash'
  );
  const [markPaidNote, setMarkPaidNote] = useState('');
  const [markPaidSubmitting, setMarkPaidSubmitting] = useState(false);
  const [markPaidError, setMarkPaidError] = useState<string | null>(null);
  const attachRef = useRef<HTMLFormElement>(null);

  useEffect(() => {
    if (!nudgeAttach) return;
    const timer = setTimeout(() => setNudgeAttach(false), 4000);
    return () => clearTimeout(timer);
  }, [nudgeAttach]);

  useEffect(() => {
    setLoading(true);
    setError(null);
    Promise.all([
      apiFetch<Invoice>(`/api/invoices/${invoiceId}/`),
      apiFetch<InvoiceWeek[]>(`/api/invoices/${invoiceId}/weeks/`),
    ])
      .then(([fetchedInvoice, fetchedWeeks]) => {
        setInvoice(fetchedInvoice);
        setWeeks(fetchedWeeks);
      })
      .catch(() => setError('Could not load this invoice.'))
      .finally(() => setLoading(false));
  }, [invoiceId]);

  useEffect(() => {
    if (user?.role !== 'landlord') return;
    apiFetch<BtcSettings>('/api/payments/btc/settings/').then(
      setBtcSettings
    );
  }, [user]);

  useEffect(() => {
    onBackHandlerChange(() => navigate('/'));
    return () => onBackHandlerChange(null);
  }, [onBackHandlerChange, navigate]);

  /**
   * Sets (or clears, via '') a line item's payment-method lock -- the
   * one and only way a rail is actually taken off a charge. Picking
   * 'btc' with no address attached instead nudges the landlord toward
   * the Attach form, since the select would otherwise snap back to
   * the item's current lock the moment the invoice re-fetches.
   * @param lineItemId - The line item to lock.
   * @param lock - '' (either rail), 'btc', or 'card'.
   */
  async function handleSetPaymentLock(lineItemId: number, lock: PaymentLock) {
    if (!invoice) return;
    if (lock === 'btc' && invoice.btc_address === '') {
      setNudgeAttach(true);
      attachRef.current?.scrollIntoView({
        behavior: 'smooth',
        block: 'center',
      });
      return;
    }
    setLockingItemId(lineItemId);
    setLockError(null);
    try {
      const updated = await apiFetch<Invoice>(
        `/api/invoices/${invoice.id}/line-items/${lineItemId}/payment-lock/`,
        { method: 'POST', body: { payment_lock: lock } }
      );
      setInvoice(updated);
    } catch (err) {
      setLockError(
        errorMessage(err, 'Could not change the payment lock. Try again.')
      );
    } finally {
      setLockingItemId(null);
    }
  }

  /** Opens the mark-paid modal for one line item, resetting its form state. */
  function openMarkPaid(lineItemId: number) {
    setMarkPaidItemId(lineItemId);
    setMarkPaidRail('cash');
    setMarkPaidNote('');
    setMarkPaidError(null);
  }

  /**
   * Records a manual (cash/check/other) settlement for the currently
   * open mark-paid modal's line item, then refetches the invoice so
   * the item's paid/frozen state and its settlement note reflect the
   * result.
   */
  async function handleMarkPaid() {
    if (!invoice || markPaidItemId === null) return;
    setMarkPaidSubmitting(true);
    setMarkPaidError(null);
    try {
      const updated = await apiFetch<Invoice>(
        `/api/invoices/${invoice.id}/line-items/${markPaidItemId}/mark-paid/`,
        { method: 'POST', body: { rail: markPaidRail, note: markPaidNote } }
      );
      setInvoice(updated);
      setMarkPaidItemId(null);
    } catch (err) {
      setMarkPaidError(
        errorMessage(err, 'Could not mark this item paid. Try again.')
      );
    } finally {
      setMarkPaidSubmitting(false);
    }
  }

  if (loading) return <p className="empty-state">Loading invoice…</p>;
  if (error) return <p className="empty-state">{error}</p>;
  if (!invoice) return <p className="empty-state">Invoice not found.</p>;

  const hasGasBreakdown = invoice.kind !== 'rent_only';
  // Needs an address to point somewhere and the whole invoice not yet
  // settled/void -- a not-fully-paid invoice can still have individual
  // items frozen, which is checked per-row below.
  const canLockPayments =
    user?.role === 'landlord' &&
    btcSettings?.enabled === true &&
    !LOCKED_STATUSES.has(invoice.status);
  // Marking paid manually doesn't need BTC enabled -- it's a landlord
  // recording an off-platform payment, not a rail on the invoice.
  const canMarkPaid =
    user?.role === 'landlord' && !LOCKED_STATUSES.has(invoice.status);
  // A non-empty btc_txid only ever means an in-flight, unconfirmed
  // round -- once it settles the tx lives on the settlement row.
  const btcPending = invoice.btc_txid !== '';
  const rails = paymentRails(invoice);
  const coverage = railCoverage(invoice);

  return (
    <div className="invoice-detail">
      <div className="dashboard-toolbar">
        <h1>
          Invoice for{' '}
          {formatBillingPeriod(
            invoice.billing_period.month,
            invoice.billing_period.year
          )}
        </h1>
        <Link to="/">← Back to dashboard</Link>
      </div>

      <div className="stat-grid">
        <div className="stat-tile">
          <span className="stat-tile__label">Status</span>
          <span className="stat-tile__value stat-tile__value--badges">
            <InvoiceStatusBadge
              status={invoice.status}
              isLate={invoice.is_late}
              remainderOwedUsd={invoice.remainder_owed_usd}
              overpaidUsd={invoice.btc_overpaid_usd}
            />
          </span>
        </div>
        <div className="stat-tile">
          <span className="stat-tile__label">Payment options</span>
          <span className="stat-tile__value stat-tile__value--rails">
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
            {!rails.btc && !rails.card && (
              <span className="stat-tile__value--muted">—</span>
            )}
          </span>
          {invoice.is_split_payment && (
            <span className="stat-tile__meta">
              <PaymentRailGlyph rail="btc" label="Payable in Bitcoin" /> $
              {formatMoney(invoice.btc_portion_usd)} ·{' '}
              <PaymentRailGlyph
                rail="card"
                label="Payable by card (Cash App)"
              />{' '}
              $
              {formatMoney(invoice.stripe_portion_usd)}
            </span>
          )}
        </div>
        <div className="stat-tile">
          <span className="stat-tile__label">Kind</span>
          <span className="stat-tile__value">
            {formatInvoiceKind(invoice.kind)}
          </span>
        </div>
        <div className="stat-tile">
          <span className="stat-tile__label">Due date</span>
          <span className="stat-tile__value">{invoice.due_date}</span>
        </div>
        <div className="stat-tile">
          <span className="stat-tile__label">Total</span>
          <span className="stat-tile__value">${invoice.total}</span>
        </div>
      </div>

      <section className="card">
        <div className="card__header">
          <h2>Line items</h2>
          {invoice.btc_line_items.length === 0 && btcPending && (
            <BtcTxLink txid={invoice.btc_txid} pending />
          )}
        </div>
        <ul className="list">
          {invoice.line_items.map((item) => {
            const isAssigned = invoice.btc_line_items.includes(item.id);
            const paid = isLineItemPaid(invoice, item.id);
            const frozen = isLineItemFrozen(invoice, item.id);
            const itemRails = lineItemRails(invoice, item);
            const settlement = settlementForLineItem(invoice, item.id);
            // Paid: the settling tx. Assigned + still pending: the
            // in-flight round's tx, if this item is part of it.
            const itemTxid = settlement
              ? settlement.txid
              : isAssigned && btcPending
                ? invoice.btc_txid
                : '';
            const lockLabel =
              item.payment_lock === 'btc'
                ? 'BTC only'
                : item.payment_lock === 'card'
                  ? 'Card only'
                  : null;
            return (
              <li key={item.id} className="list-row">
                <span>
                  <span className="list-row__rails">
                    {itemRails.btc && (
                      <PaymentRailGlyph rail="btc" label="Payable in Bitcoin" />
                    )}
                    {itemRails.card && (
                      <PaymentRailGlyph
                        rail="card"
                        label="Payable by card (Cash App)"
                      />
                    )}
                  </span>
                  {item.description}
                </span>
                <span className="renter-dashboard__invoice-actions">
                  ${item.amount}
                  {paid && (
                    <span className="status-badge status-badge--paid">
                      Paid
                    </span>
                  )}
                  {!paid && lockLabel && (
                    <span className="status-badge status-badge--pending">
                      {lockLabel}
                    </span>
                  )}
                  {itemTxid !== '' && (
                    <BtcTxLink txid={itemTxid} pending={!settlement} />
                  )}
                  {settlement &&
                    ['cash', 'check', 'other'].includes(settlement.rail) && (
                      <PaymentRailGlyph
                        rail={settlement.rail}
                        label={
                          settlement.note !== ''
                            ? settlement.note
                            : undefined
                        }
                      />
                    )}
                  {canMarkPaid && !frozen && (
                    <button type="button" onClick={() => openMarkPaid(item.id)}>
                      Mark paid
                    </button>
                  )}
                  {canLockPayments && !frozen && (
                    <select
                      className="payment-lock-select"
                      value={item.payment_lock}
                      disabled={lockingItemId !== null}
                      onChange={(e) =>
                        handleSetPaymentLock(
                          item.id,
                          e.target.value as PaymentLock
                        )
                      }
                    >
                      <option value="">Any method</option>
                      <option value="btc">BTC only</option>
                      <option value="card">Card only</option>
                    </select>
                  )}
                </span>
              </li>
            );
          })}
        </ul>
        {lockError && <p role="alert">{lockError}</p>}
      </section>

      {markPaidItemId !== null && (
        <div className="mark-paid-modal-overlay">
          <div className="mark-paid-modal card">
            <h2>Mark paid</h2>
            <label>
              Method
              <select
                value={markPaidRail}
                onChange={(e) =>
                  setMarkPaidRail(
                    e.target.value as 'cash' | 'check' | 'other'
                  )
                }
              >
                <option value="cash">Cash</option>
                <option value="check">Check</option>
                <option value="other">Other</option>
              </select>
            </label>
            <label>
              Note (optional)
              <textarea
                value={markPaidNote}
                onChange={(e) => setMarkPaidNote(e.target.value)}
                rows={2}
              />
            </label>
            {markPaidError && <p role="alert">{markPaidError}</p>}
            <div className="mark-paid-modal__actions">
              <button
                type="button"
                onClick={() => setMarkPaidItemId(null)}
                disabled={markPaidSubmitting}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleMarkPaid}
                disabled={markPaidSubmitting}
              >
                {markPaidSubmitting ? 'Saving…' : 'Confirm'}
              </button>
            </div>
          </div>
        </div>
      )}

      {user?.role === 'landlord' &&
        btcSettings?.enabled &&
        !LOCKED_STATUSES.has(invoice.status) && (
          <section className="card">
            <div className="card__header">
              <h2>BTC Payment</h2>
            </div>
            {invoice.btc_address && invoice.btc_amount_sats !== null && (
              <p>
                Attached: {satsToBtc(invoice.btc_amount_sats)} BTC
                {invoice.is_split_payment &&
                  `, covering $${formatMoney(invoice.btc_portion_usd)} of \
this invoice`}
              </p>
            )}
            <AttachBtcPaymentForm
              invoice={invoice}
              onAttached={(updated) => {
                setNudgeAttach(false);
                setInvoice(updated);
              }}
              nudge={nudgeAttach}
              formRef={attachRef}
            />
          </section>
        )}

      {hasGasBreakdown && (
        <div className="dashboard-columns">
          <section className="card">
            <div className="card__header">
              <h2>Mileage Log</h2>
            </div>
            <DrivenDaysCalendar
              logs={weeksToLogs(weeks)}
              pricedWeekRanges={weeksToPricedRanges(weeks)}
              initialYear={invoice.billing_period.year}
              initialMonth={invoice.billing_period.month - 1}
            />
            <DrivenDaysCalendarKey />
          </section>

          <section className="card">
            <div className="card__header">
              <h2>Weekly Breakdown</h2>
            </div>
            {weeks.length === 0 ? (
              <p className="empty-state">No days logged.</p>
            ) : (
              <ul className="list">
                {weeks.map((week) => (
                  <li key={week.week_start} className="invoice-detail__week">
                    <div className="list-row">
                      <span>
                        {week.week_start} – {week.week_end}
                        {week.price_per_gallon !== null &&
                          ` — $${formatMoney(week.price_per_gallon)}/gal`}
                      </span>
                      <span>
                        {week.total_miles} mi — ${week.total_gas_cost}
                      </span>
                    </div>
                    <ul className="invoice-detail__week-days">
                      {week.days.map((day) => (
                        <li key={day.date} className="list-row">
                          <span>
                            {day.date} — {formatDayDescription(day)}
                          </span>
                          <span>
                            {day.kind === 'driven'
                              ? `${day.miles} mi — $${day.gas_cost}`
                              : '—'}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
