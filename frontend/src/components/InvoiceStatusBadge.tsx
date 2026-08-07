import { formatMoney } from '../api/format';
import type { InvoiceStatus } from '../api/types';

const LABELS: Record<InvoiceStatus, string> = {
  draft: 'Draft',
  sent: 'Unpaid',
  pending: 'Payment pending',
  partial: 'Partially Paid',
  underpaid: 'Underpaid',
  paid: 'Paid',
  void: 'Void',
};


/**
 * A colored pill showing an invoice's payment status, plus separate
 * "Late" and "Overpaid" pills layered on top of it.
 *
 * 'partial' and 'underpaid' both mean some money arrived but call for
 * different responses: a split invoice is progressing normally and
 * just needs its other leg, while an underpaid one is short and needs
 * chasing. An overpayment is additive rather than its own status --
 * the invoice is still fully paid -- so it reads "Paid" + "Overpaid",
 * the same pattern as "Late".
 * @param props.status - The invoice status to render.
 * @param props.isLate - Whether the invoice is unpaid and past its due
 *   date. Omit or pass false to hide the "Late" pill.
 * @param props.remainderOwedUsd - Outstanding USD still owed after a
 *   BTC underpayment, as a decimal string. Shown in the pill's tooltip
 *   on an 'underpaid' invoice; ignored otherwise.
 * @param props.overpaidUsd - How much more than the quote the BTC leg
 *   received, as a decimal string, or null/undefined if it didn't.
 *   Shown as a separate "Overpaid" pill with the amount in its tooltip.
 */
export function InvoiceStatusBadge({
  status,
  isLate,
  remainderOwedUsd,
  overpaidUsd,
}: {
  status: InvoiceStatus;
  isLate?: boolean;
  remainderOwedUsd?: string | null;
  overpaidUsd?: string | null;
}) {
  const showsRemainder = status === 'underpaid' && remainderOwedUsd != null;
  return (
    <>
      <span
        className={`status-badge status-badge--${status}`}
        title={
          showsRemainder
            ? `$${formatMoney(remainderOwedUsd)} still owed`
            : undefined
        }
      >
        {LABELS[status]}
      </span>
      {isLate && <span className="status-badge status-badge--late">Late</span>}
      {overpaidUsd != null && (
        <span
          className="status-badge status-badge--overpaid"
          title={`$${formatMoney(overpaidUsd)} overpaid`}
        >
          Overpaid
        </span>
      )}
    </>
  );
}
