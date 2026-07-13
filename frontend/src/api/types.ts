/** Whether a user/account is a landlord or a renter. */
export type Role = 'landlord' | 'renter';


/**
 * @property id - Primary key.
 * @property email - Login email address.
 * @property role - Whether this user is the landlord or the renter.
 * @property first_name - Optional given name.
 * @property last_name - Optional family name.
 */
export interface User {
  id: number;
  email: string;
  role: Role;
  first_name: string;
  last_name: string;
}


/** Whether a lease is a landlord-uploaded document or the default lease. */
export type LeaseType = 'custom' | 'default';


/**
 * @property id - Primary key.
 * @property landlord - User id of the landlord on this lease.
 * @property renter - User id of the renter on this lease.
 * @property renter_detail - Full renter record (name/email/role).
 * @property monthly_rent - Base monthly rent, as a decimal string.
 * @property start_date - Lease start date (ISO 8601).
 * @property active - Whether the lease is currently active.
 * @property lease_type - Custom uploaded document or the default lease.
 * @property document - URL of the uploaded document, if lease_type is
 *   'custom'; otherwise null.
 * @property term_months - Lease term in months, set for 'default' leases.
 * @property terms_text - Generated boilerplate terms text for 'default'
 *   leases; null for 'custom' leases.
 */
export interface Lease {
  id: number;
  landlord: number;
  renter: number;
  renter_detail: User;
  monthly_rent: string;
  start_date: string;
  active: boolean;
  lease_type: LeaseType;
  document: string | null;
  term_months: number | null;
  terms_text: string | null;
}


/**
 * @property id - Primary key.
 * @property landlord - User id of the landlord who logged this day.
 * @property renter - User id of the renter who was driven.
 * @property date - The date driven (ISO 8601).
 * @property day_fraction - Fraction of a full day driven (e.g. "0.50").
 * @property note - Optional free-text note.
 */
export interface DrivenDayLog {
  id: number;
  landlord: number;
  renter: number;
  date: string;
  day_fraction: string;
  note: string;
}


/**
 * @property id - Primary key.
 * @property landlord - User id of the landlord this profile belongs to.
 * @property renter - User id of the renter this profile is for.
 * @property one_way_miles - One-way commute distance, as a decimal string.
 * @property mpg - Vehicle fuel efficiency, as a decimal string.
 * @property effective_from - Date this profile takes effect (ISO 8601).
 * @property full_day_miles - one_way_miles * 4, as a decimal string.
 */
export interface MileageProfile {
  id: number;
  landlord: number;
  renter: number;
  one_way_miles: string;
  mpg: string;
  effective_from: string;
  full_day_miles: string;
}


/**
 * @property id - Primary key.
 * @property landlord - User id of the landlord this entry belongs to.
 * @property renter - User id of the renter this entry is for.
 * @property price_per_gallon - Price per gallon, as a decimal string.
 * @property effective_from - Date this price takes effect (ISO 8601).
 * @property effective_to - Date this price stops applying (ISO 8601), or
 *   null if still in effect.
 */
export interface GasPriceEntry {
  id: number;
  landlord: number;
  renter: number;
  price_per_gallon: string;
  effective_from: string;
  effective_to: string | null;
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
 * @property landlord - User id of the landlord this period belongs to.
 * @property renter - User id of the renter this period belongs to.
 * @property year - Calendar year of the billing period.
 * @property month - Calendar month of the billing period (1-12).
 */
export interface BillingPeriod {
  id: number;
  landlord: number;
  renter: number;
  year: number;
  month: number;
}


export type InvoiceKind = 'combined' | 'rent_only' | 'gas_only';
export type InvoiceStatus = 'draft' | 'sent' | 'paid' | 'void';


/**
 * @property id - Primary key.
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
