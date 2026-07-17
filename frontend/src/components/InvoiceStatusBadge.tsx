import type { InvoiceStatus } from '../api/types';

const LABELS: Record<InvoiceStatus, string> = {
  draft: 'Draft',
  sent: 'Unpaid',
  paid: 'Paid',
  void: 'Void',
};


/**
 * A colored pill showing an invoice's payment status, plus a separate
 * "Late" pill when the invoice is unpaid past its due date.
 * @param props.status - The invoice status to render.
 * @param props.isLate - Whether the invoice is unpaid and past its due
 *   date. Omit or pass false to hide the "Late" pill.
 */
export function InvoiceStatusBadge({
  status,
  isLate,
}: {
  status: InvoiceStatus;
  isLate?: boolean;
}) {
  return (
    <>
      <span className={`status-badge status-badge--${status}`}>
        {LABELS[status]}
      </span>
      {isLate && <span className="status-badge status-badge--late">Late</span>}
    </>
  );
}
