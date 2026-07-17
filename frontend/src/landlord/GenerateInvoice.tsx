import { useState, type FormEvent } from 'react';
import { apiFetch } from '../api/client';
import { MONTH_NAMES } from '../api/format';
import type { Invoice, InvoiceKind, PeriodPreview } from '../api/types';

/**
 * Landlord form to preview a period's charges and generate an invoice.
 * @param props.renterId - The renter to generate the invoice for.
 * @param props.onGenerated - Called with the created invoice on success.
 */
export function GenerateInvoice({
  renterId,
  onGenerated,
}: {
  renterId: number;
  onGenerated: (invoice: Invoice) => void;
}) {
  const now = new Date();
  const [year, setYear] = useState(String(now.getFullYear()));
  const [month, setMonth] = useState(String(now.getMonth() + 1));
  const [kind, setKind] = useState<InvoiceKind>('combined');
  const [preview, setPreview] = useState<PeriodPreview | null>(null);
  const [error, setError] = useState<string | null>(null);

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
    setError(null);
    try {
      const invoice = await apiFetch<Invoice>('/api/invoices/', {
        method: 'POST',
        body: {
          renter: renterId,
          year: Number(year),
          month: Number(month),
          kind,
        },
      });
      onGenerated(invoice);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <form onSubmit={handleGenerate}>
      <h3>Generate invoice</h3>
      <label htmlFor="year">Year</label>
      <input
        id="year"
        type="number"
        value={year}
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
        <option value="combined">Rent + gas (combined)</option>
        <option value="rent_only">Rent only</option>
        <option value="gas_only">Gas only</option>
      </select>

      <button type="button" onClick={handlePreview}>
        Preview
      </button>
      {preview && (
        <p>
          Rent: ${preview.rent} — Gas: ${preview.gas}
        </p>
      )}

      <button type="submit">Generate invoice</button>
      {error && <p role="alert">{error}</p>}
    </form>
  );
}
