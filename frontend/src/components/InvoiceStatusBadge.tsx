import { formatMoney } from '../api/format';
import type { InvoiceStatus } from '../api/types';

const LABELS: Record<InvoiceStatus, string> = {
  draft: 'Draft',
  sent: 'Unpaid',
  pending: 'Payment pending',
  partial: 'Partially Paid',
  paid: 'Paid',
  void: 'Void',
};


/**
 * A colored pill showing an invoice's payment status, plus a separate
 * "Late" pill when the invoice is unpaid past its due date.
 *
 * A 'partial' invoice covers two situations needing different
 * responses, so they're labelled apart: a renter who underpaid a BTC
 * quote ("Underpaid", with a concrete remainder still owed) versus an
 * invoice merely split across two payment methods with one leg settled
 * ("Partially Paid", nothing wrong). The remainder is what tells them
 * apart, so it's derived here rather than carried as its own status.
 * @param props.status - The invoice status to render.
 * @param props.isLate - Whether the invoice is unpaid and past its due
 *   date. Omit or pass false to hide the "Late" pill.
 * @param props.remainderOwedUsd - Outstanding USD still owed after a
 *   BTC underpayment, as a decimal string, or null when there's no
 *   shortfall. Only meaningful on a 'partial' invoice.
 */
export function InvoiceStatusBadge({
  status,
  isLate,
  remainderOwedUsd,
}: {
  status: InvoiceStatus;
  isLate?: boolean;
  remainderOwedUsd?: string | null;
}) {
  const isShortfall = status === 'partial' && remainderOwedUsd != null;
  return (
    <>
      <span
        className={
          isShortfall
            ? 'status-badge status-badge--underpaid'
            : `status-badge status-badge--${status}`
        }
        title={
          isShortfall
            ? `$${formatMoney(remainderOwedUsd)} still owed`
            : undefined
        }
      >
        {isShortfall ? 'Underpaid' : LABELS[status]}
      </span>
      {isLate && <span className="status-badge status-badge--late">Late</span>}
    </>
  );
}
