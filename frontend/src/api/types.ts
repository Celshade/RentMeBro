/** Whether a user/account is a landlord or a renter. */
export type Role = 'landlord' | 'renter';


/**
 * @property id - Primary key.
 * @property email - Login email address.
 * @property role - Whether this user is the landlord or the renter.
 */
export interface User {
  id: number;
  email: string;
  role: Role;
}


/**
 * @property id - Primary key.
 * @property landlord - User id of the landlord on this lease.
 * @property renter - User id of the renter on this lease.
 * @property monthly_rent - Base monthly rent, as a decimal string.
 * @property start_date - Lease start date (ISO 8601).
 * @property active - Whether the lease is currently active.
 */
export interface Lease {
  id: number;
  landlord: number;
  renter: number;
  monthly_rent: string;
  start_date: string;
  active: boolean;
}


/**
 * @property id - Primary key.
 * @property lease - Id of the lease this log entry belongs to.
 * @property date - The date driven (ISO 8601).
 * @property day_fraction - Fraction of a full day driven (e.g. "0.50").
 * @property note - Optional free-text note.
 */
export interface DrivenDayLog {
  id: number;
  lease: number;
  date: string;
  day_fraction: string;
  note: string;
}


/**
 * @property id - Primary key.
 * @property description - Human-readable line description.
 * @property amount - Line amount, as a decimal string.
 * @property kind - Whether this line is a rent or gas charge.
 */
export interface InvoiceLineItem {
  id: number;
  description: string;
  amount: string;
  kind: 'rent' | 'gas';
}


/**
 * @property id - Primary key.
 * @property lease - Id of the lease this period belongs to.
 * @property year - Calendar year of the billing period.
 * @property month - Calendar month of the billing period (1-12).
 */
export interface BillingPeriod {
  id: number;
  lease: number;
  year: number;
  month: number;
}


export type InvoiceKind = 'combined' | 'rent_only' | 'gas_only';
export type InvoiceStatus = 'draft' | 'sent' | 'paid' | 'void';


/**
 * @property id - Primary key.
 * @property lease - Id of the lease this invoice belongs to.
 * @property billing_period - The billing period this invoice covers.
 * @property kind - Whether the invoice covers rent, gas, or both.
 * @property status - Current payment status.
 * @property stripe_payment_intent_id - Associated Stripe PaymentIntent id.
 * @property created_at - Creation timestamp (ISO 8601).
 * @property line_items - The rent/gas charges making up this invoice.
 * @property total - Sum of all line item amounts, as a decimal string.
 */
export interface Invoice {
  id: number;
  lease: number;
  billing_period: BillingPeriod;
  kind: InvoiceKind;
  status: InvoiceStatus;
  stripe_payment_intent_id: string;
  created_at: string;
  line_items: InvoiceLineItem[];
  total: string;
}


/**
 * @property rent - Rent portion of the period total, as a decimal string.
 * @property gas - Gas portion of the period total, as a decimal string.
 */
export interface PeriodPreview {
  rent: string;
  gas: string;
}
