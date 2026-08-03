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
 * @property connected - Whether the landlord has a Stripe connected account.
 * @property charges_enabled - Whether that account can accept payments yet.
 */
export interface ConnectStatus {
  connected: boolean;
  charges_enabled: boolean;
}


/** @property enabled - Whether the landlord has enabled BTC payments. */
export interface BtcSettings {
  enabled: boolean;
}


/**
 * @property btc_address - The landlord's BTC address to display to the
 *   renter, or an empty string if BTC payment isn't attached.
 * @property btc_amount_sats - The fixed amount, in satoshis, the renter
 *   must send, or null if BTC payment isn't attached.
 * @property btc_watch_expires_at - When the current 15-minute "have we
 *   seen any tx yet" window closes (ISO 8601), or null if no watch is
 *   in progress.
 * @property status - The invoice's current status (mirrors
 *   InvoiceStatus, kept separate since some BTC endpoints don't return
 *   a full Invoice).
 */
export interface BtcInvoiceStatus {
  btc_address: string;
  btc_amount_sats: number | null;
  btc_watch_expires_at: string | null;
  status: InvoiceStatus;
}


/**
 * @property id - Primary key.
 * @property landlord - User id of the landlord on this lease.
 * @property landlord_detail - Full landlord record (name/email/role).
 * @property renter - User id of the renter on this lease.
 * @property renter_detail - Full renter record (name/email/role).
 * @property monthly_rent - Base monthly rent, as a decimal string.
 * @property current_monthly_rent - Rent in effect today, applying any
 *   due rent revision, as a decimal string.
 * @property pending_rent_revision - The nearest scheduled rent change
 *   not yet in effect, or null if none is queued.
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
  landlord_detail: User;
  renter: number;
  renter_detail: User;
  monthly_rent: string;
  current_monthly_rent: string;
  pending_rent_revision: {
    new_monthly_rent: string;
    effective_date: string;
  } | null;
  start_date: string;
  active: boolean;
  lease_type: LeaseType;
  document: string | null;
  term_months: number | null;
  terms_text: string | null;
}


/** Whether a logged day was driven by the landlord, a day off, or a
 * day someone else drove the renter (unpaid to the landlord, not a
 * day off).
 */
export type DrivenDayLogKind = 'driven' | 'day_off' | 'other_ride';


/**
 * @property id - Primary key.
 * @property landlord - User id of the landlord who logged this day.
 * @property renter - User id of the renter who was driven.
 * @property date - The date logged (ISO 8601).
 * @property kind - Whether this day was driven, a day off, or covered
 *   by someone else.
 * @property day_fraction - Fraction of a full day driven (e.g. "0.50").
 *   Always "0.00" when kind isn't 'driven'.
 * @property note - Optional free-text note.
 */
export interface DrivenDayLog {
  id: number;
  landlord: number;
  renter: number;
  date: string;
  kind: DrivenDayLogKind;
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
export type InvoiceStatus = 'draft' | 'sent' | 'pending' | 'paid' | 'void';


/**
 * @property id - Primary key.
 * @property billing_period - The billing period this invoice covers.
 * @property kind - Whether the invoice covers rent, gas, or both.
 * @property status - Current payment status.
 * @property due_date - Date the invoice is due (ISO 8601). Defaults to
 *   the 5th of the month after the billing period.
 * @property is_late - Whether the invoice is unpaid and past its due
 *   date.
 * @property stripe_payment_intent_id - Associated Stripe PaymentIntent id.
 * @property created_at - Creation timestamp (ISO 8601).
 * @property line_items - The rent/gas charges making up this invoice.
 * @property total - Sum of all line item amounts, as a decimal string.
 * @property btc_address - The landlord's BTC address, or an empty
 *   string if BTC payment isn't attached.
 * @property btc_amount_sats - The fixed BTC amount, in satoshis, or
 *   null if BTC payment isn't attached.
 */
export interface Invoice {
  id: number;
  billing_period: BillingPeriod;
  kind: InvoiceKind;
  status: InvoiceStatus;
  due_date: string;
  is_late: boolean;
  stripe_payment_intent_id: string;
  created_at: string;
  line_items: InvoiceLineItem[];
  total: string;
  btc_address: string;
  btc_amount_sats: number | null;
}


/**
 * @property rent - Rent portion of the period total, as a decimal string.
 * @property gas - Gas portion of the period total, as a decimal string.
 */
export interface PeriodPreview {
  rent: string;
  gas: string;
}


/**
 * @property date - The logged date (ISO 8601).
 * @property kind - Whether that day was driven, a day off, or covered
 *   by someone else.
 * @property day_fraction - Fraction of a full day driven, as a decimal
 *   string. "0.00" when kind isn't 'driven'.
 * @property miles - Miles driven that day, as a decimal string.
 * @property gas_cost - Gas cost for that day, as a decimal string.
 */
export interface InvoiceWeekDay {
  date: string;
  kind: DrivenDayLogKind;
  day_fraction: string;
  miles: string;
  gas_cost: string;
}


/**
 * @property week_start - First day (Sunday) of this billed week (ISO 8601).
 * @property week_end - Last day (Saturday) of this billed week (ISO 8601).
 * @property total_miles - Miles driven that week, as a decimal string.
 * @property total_gas_cost - Gas cost for that week, as a decimal string.
 * @property price_per_gallon - Gas price in effect that week, as a
 *   decimal string, or null if no day that week was actually driven.
 * @property days - Per-day detail for the week.
 */
export interface InvoiceWeek {
  week_start: string;
  week_end: string;
  total_miles: string;
  total_gas_cost: string;
  price_per_gallon: string | null;
  days: InvoiceWeekDay[];
}
