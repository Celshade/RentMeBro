import { useEffect, useState, type FormEvent } from 'react';
import { apiFetch } from '../api/client';
import { MONTH_NAMES } from '../api/format';
import type { Invoice, InvoiceKind, PeriodPreview } from '../api/types';

/** The 5th of the month after the given billing period, as YYYY-MM-DD. */
function defaultDueDate(year: string, month: string): string {
  const y = Number(year);
  const m = Number(month);
  const [dueYear, dueMonth] = m === 12 ? [y + 1, 1] : [y, m + 1];
  return `${dueYear}-${String(dueMonth).padStart(2, '0')}-05`;
}

/** Matches the backend's InvoiceCreateSerializer bound. */
const MAX_FUTURE_INVOICE_MONTHS = 12;

/** Whether year/month falls strictly after the current calendar month. */
function isFutureMonth(year: string, month: string, now: Date): boolean {
  const y = Number(year);
  const m = Number(month);
  const nowY = now.getFullYear();
  const nowM = now.getMonth() + 1;
  return y > nowY || (y === nowY && m > nowM);
}

/** The furthest year/month a landlord may generate an invoice for. */
function maxAllowedMonth(now: Date): { year: number; month: number } {
  const total = now.getFullYear() * 12 + now.getMonth() + MAX_FUTURE_INVOICE_MONTHS;
  return { year: Math.floor(total / 12), month: (total % 12) + 1 };
}

/**
 * Landlord form to preview a period's charges and generate an invoice.
 * @param props.renterId - The renter to generate the invoice for.
 * @param props.onGenerated - Called with the created invoice on success.
 * @param props.onCancel - Called when the landlord backs out without
 *     generating an invoice.
 */
export function GenerateInvoice({
  renterId,
  onGenerated,
  onCancel,
}: {
  renterId: number;
  onGenerated: (invoice: Invoice) => void;
  onCancel: () => void;
}) {
  const now = new Date();
  const [year, setYear] = useState(String(now.getFullYear()));
  const [month, setMonth] = useState(String(now.getMonth() + 1));
  const [kind, setKind] = useState<InvoiceKind>('combined');
  const [dueDate, setDueDate] = useState(defaultDueDate(year, month));
  const [preview, setPreview] = useState<PeriodPreview | null>(null);
  const [error, setError] = useState<string | null>(null);

  const future = isFutureMonth(year, month, now);
  const maxAllowed = maxAllowedMonth(now);

  useEffect(() => {
    setDueDate(defaultDueDate(year, month));
  }, [year, month]);

  useEffect(() => {
    if (future && kind !== 'rent_only') {
      setKind('rent_only');
    }
  }, [future, kind]);

  async function handlePreview() {
    setError(null);
    try {
      const data = await apiFetch<PeriodPreview>(
        `/api/renters/${renterId}/billing-periods/${year}-${month}/preview/`
      );
      setPreview(data);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function handleGenerate(event: FormEvent) {
    event.preventDefault();
    const confirmed = window.confirm(
      `Generate the ${MONTH_NAMES[Number(month) - 1]} ${year} invoice? ` +
        'Make sure the mileage log for that month is accurate first — ' +
        'this cannot be undone.'
    );
    if (!confirmed) return;
    setError(null);
    try {
      const invoice = await apiFetch<Invoice>('/api/invoices/', {
        method: 'POST',
        body: {
          renter: renterId,
          year: Number(year),
          month: Number(month),
          kind,
          due_date: dueDate,
        },
      });
      onGenerated(invoice);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <form onSubmit={handleGenerate}>
      <h3>Generate Invoice</h3>
      <label htmlFor="year">Year</label>
      <input
        id="year"
        type="number"
        value={year}
        min={now.getFullYear()}
        max={maxAllowed.year}
        onChange={(e) => setYear(e.target.value)}
      />
      <label htmlFor="month">Month</label>
      <select
        id="month"
        value={month}
        onChange={(e) => setMonth(e.target.value)}
      >
        {MONTH_NAMES.map((name, index) => (
          <option key={name} value={index + 1}>
            {name}
          </option>
        ))}
      </select>
      <label htmlFor="kind">Invoice type</label>
      <select
        id="kind"
        value={kind}
        onChange={(e) => setKind(e.target.value as InvoiceKind)}
      >
        <option value="combined" disabled={future}>
          Rent + gas (combined)
        </option>
        <option value="rent_only">Rent only</option>
        <option value="gas_only" disabled={future}>
          Gas only
        </option>
      </select>
      {future && (
        <p>
          Future months can only be billed rent-only, up to{' '}
          {MONTH_NAMES[maxAllowed.month - 1]} {maxAllowed.year}.
        </p>
      )}
      <label htmlFor="due_date">Due date</label>
      <input
        id="due_date"
        type="date"
        value={dueDate}
        onChange={(e) => setDueDate(e.target.value)}
      />

      <button type="button" onClick={handlePreview}>
        Preview
      </button>
      {preview && (
        <p>
          Rent: ${preview.rent} — Gas: ${preview.gas}
        </p>
      )}

      <button type="submit">Generate Invoice</button>
      <button type="button" onClick={onCancel}>
        Cancel
      </button>
      {error && <p role="alert">{error}</p>}
    </form>
  );
}
