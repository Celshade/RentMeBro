import type { InvoiceStatus } from '../api/types';

const LABELS: Record<InvoiceStatus, string> = {
  draft: 'Draft',
  sent: 'Unpaid',
  paid: 'Paid',
  void: 'Void',
};


/**
 * A colored pill showing an invoice's payment status.
 * @param props.status - The invoice status to render.
 */
export function InvoiceStatusBadge({ status }: { status: InvoiceStatus }) {
  return (
    <span className={`status-badge status-badge--${status}`}>
      {LABELS[status]}
    </span>
  );
}
