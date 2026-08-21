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
 * @property btc_txid - The in-flight round's matched transaction id,
 *   or an empty string if none has been seen yet, or once that round
 *   has settled. Distinguishes "tx seen, awaiting confirmation" from
 *   "nothing arrived" once the window has lapsed.
 * @property btc_settled_at - When the most recent BTC round settled
 *   (ISO 8601), or null if none has.
 * @property remainder_owed_usd - The outstanding USD balance still
 *   owed via BTC after a prior underpayment, or null when there's no
 *   shortfall.
 * @property btc_owed_usd - The USD still owed via BTC right now, as a
 *   decimal string: the remainder if one's outstanding, otherwise the
 *   current BTC portion. "0.00" once every BTC-payable item is paid --
 *   this is what distinguishes "this round settled, more is owed" from
 *   "the invoice is done" for a second BTC round.
 * @property status - The invoice's current status (mirrors
 *   InvoiceStatus, kept separate since some BTC endpoints don't return
 *   a full Invoice).
 * @property line_items - Ids of the line items the live round covers,
 *   or -- with no round live -- what a fresh quote would cover right
 *   now (`Invoice.btc_scope_line_items`). Distinct from the paid/
 *   frozen sets on a full `Invoice`.
 */
export interface BtcInvoiceStatus {
  btc_address: string;
  btc_amount_sats: number | null;
  btc_watch_expires_at: string | null;
  btc_txid: string;
  btc_settled_at: string | null;
  remainder_owed_usd: string | null;
  btc_owed_usd: string;
  status: InvoiceStatus;
  line_items: number[];
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


/** Which leg of a half day was driven, or '' when unset/not applicable
 * -- always '' when the log isn't a half-day 'driven' entry. */
export type DrivenDayHalfLeg = '' | 'drop_off' | 'pick_up';


/**
 * @property id - Primary key.
 * @property landlord - User id of the landlord who logged this day.
 * @property renter - User id of the renter who was driven.
 * @property date - The date logged (ISO 8601).
 * @property kind - Whether this day was driven, a day off, or covered
 *   by someone else.
 * @property day_fraction - Fraction of a full day driven (e.g. "0.50").
 *   Always "0.00" when kind isn't 'driven'.
 * @property half_leg - Which leg of a half day was driven, or '' if
 *   unknown or not applicable (a full day, or kind isn't 'driven').
 * @property note - Optional free-text note.
 */
export interface DrivenDayLog {
  id: number;
  landlord: number;
  renter: number;
  date: string;
  kind: DrivenDayLogKind;
  day_fraction: string;
  half_leg: DrivenDayHalfLeg;
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


/** Which rail a line item is locked to, or '' for either. Set by the
 * landlord explicitly -- see `payment_lock` below. */
export type PaymentLock = '' | 'btc' | 'card';


/**
 * @property id - Primary key.
 * @property description - Human-readable line description.
 * @property amount - Line amount, as a decimal string.
 * @property kind - Whether this line is a rent or gas charge.
 * @property payment_lock - Which rail may pay this charge: '' (either),
 *   'btc', or 'card'. The only thing that restricts a rail;
 *   `Invoice.btc_line_items` sizes and gates the BTC quote but never
 *   removes the card rail on its own.
 */
export interface InvoiceLineItem {
  id: number;
  description: string;
  amount: string;
  kind: 'rent' | 'gas';
  payment_lock: PaymentLock;
}


/**
 * One completed payment round against an invoice, and what it bought.
 * @property id - Primary key.
 * @property rail - Which payment rail settled this round.
 * @property txid - The settling BTC transaction id, or '' for a card
 *   settlement.
 * @property line_items - Ids of the line items this round covered.
 * @property amount_usd - USD this round settled, as a decimal string.
 * @property overpaid_usd - How much more than quoted a BTC round
 *   received, as a decimal string, or null if it settled on- or
 *   under-quote (always null for a card settlement).
 * @property note - An optional landlord-entered note, only ever set
 *   on a manual (cash/check/other) settlement.
 * @property settled_at - When this round settled (ISO 8601).
 */
export interface InvoiceSettlement {
  id: number;
  rail: 'btc' | 'card' | 'cash' | 'check' | 'other';
  txid: string;
  line_items: number[];
  amount_usd: string;
  overpaid_usd: string | null;
  note: string;
  settled_at: string;
}


export type BtcPaymentClaimStatus = 'pending' | 'accepted' | 'denied';


/**
 * A renter-submitted BTC txid awaiting landlord review, submitted as
 * a fallback when automatic reconciliation hasn't picked up a
 * payment yet.
 * @property id - Primary key.
 * @property txid - The transaction id the renter says paid the invoice.
 * @property status - Where the claim stands in the landlord's review.
 * @property created_at - When the claim was submitted (ISO 8601).
 * @property resolved_at - When the claim was accepted or denied (ISO
 *   8601), or null while still pending.
 */
export interface BtcPaymentClaim {
  id: number;
  txid: string;
  status: BtcPaymentClaimStatus;
  created_at: string;
  resolved_at: string | null;
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
export type InvoiceStatus =
  | 'draft'
  | 'sent'
  | 'pending'
  | 'partial'
  | 'underpaid'
  | 'paid'
  | 'void';


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
 * @property btc_amount_sats - The renter's current rate-locked BTC
 *   amount, in satoshis, or null if no payment attempt is in
 *   progress.
 * @property remainder_owed_usd - The outstanding USD balance still
 *   owed via BTC after a prior underpayment, or null when there's no
 *   shortfall. This is what distinguishes an underpaid invoice from
 *   one merely split across two payment methods, since both sit at
 *   'partial'.
 * @property btc_line_items - The landlord's BTC assignment: ids of the
 *   line items marked as BTC-billed. Binding -- empty means no BTC
 *   quote at all, even if a BTC address is attached. It sizes and
 *   gates the BTC quote and drives the "Due in BTC" badge, but does
 *   *not* by itself restrict the card rail -- only `payment_lock` does.
 *   Paid items stay in this set (it's what keeps their "Paid in BTC"
 *   glyph); everything downstream filters to unpaid.
 * @property btc_portion_usd - The USD a fresh BTC quote would cover
 *   right now, as a decimal string: the landlord's assignment
 *   intersected with what's still BTC-payable, falling back to every
 *   BTC-payable item only once something has been assigned and that
 *   intersection has gone empty (a settled round quoting the
 *   remainder); zero when nothing's ever been assigned.
 * @property stripe_portion_usd - The USD the Cash App tab bills by
 *   default, as a decimal string: card-payable items the landlord
 *   hasn't earmarked for BTC.
 * @property card_full_owed_usd - Every card-payable item's total, as a
 *   decimal string, ignoring the BTC expectation -- the opt-in "pay it
 *   all by card instead" figure. Only a `payment_lock: 'btc'` item is
 *   ever excluded from this.
 * @property btc_owed_usd - The USD still owed via BTC right now, as a
 *   decimal string: the remainder if one's outstanding, otherwise
 *   `btc_portion_usd`.
 * @property is_split_payment - Informational: whether BTC is scoped to
 *   some, but not all, of the unpaid charges. Drives the split-notice
 *   copy only; the invoice's paid status no longer depends on it.
 * @property btc_settled_at - When the most recent BTC round settled
 *   (ISO 8601), or null if none has.
 * @property btc_overpaid_usd - Total USD received beyond quote across
 *   every BTC round, as a decimal string, or null if none has been
 *   overpaid. An overpaid invoice is still fully paid -- this is an
 *   additive flag, not a replacement status.
 * @property stripe_settled_at - When the card leg most recently
 *   settled (ISO 8601), or null if it hasn't.
 * @property btc_txid - The in-flight round's matched tx, cleared once
 *   that round settles -- the settled tx lives on its `settlements`
 *   row instead.
 * @property btc_credited_txid - A short payment credited toward the
 *   invoice that leaves a remainder owed, or an empty string if there
 *   isn't one.
 * @property btc_credited_usd - What `btc_credited_txid` was worth at
 *   credit time, as a decimal string, or null if there isn't one.
 *   Already netted out of `stripe_portion_usd`, `card_full_owed_usd`,
 *   and `btc_full_owed_usd` server-side -- shown here only so the UI
 *   can explain why those totals are less than a line item's amount.
 * @property btc_watch_expires_at - When the current BTC quote window
 *   closes (ISO 8601), or null if no watch is in progress.
 * @property paid_line_items - Ids of line items covered by a settled
 *   payment. The single authority for per-item paid state.
 * @property frozen_line_items - Ids of line items the landlord may no
 *   longer re-scope or re-lock: paid, or with a payment in flight on
 *   either rail (minus the underpaid-round exception).
 * @property stripe_round_expires_at - When the current in-flight card
 *   round's local expiry lapses (ISO 8601), or null if there's no
 *   in-flight round or its expiry hasn't been learned from Stripe yet.
 * @property btc_scope_line_items - What a fresh BTC quote would cover
 *   right now. Distinct from `btc_line_items` (the landlord's
 *   assignment) and `paid_line_items` -- this is *what the next round
 *   would bill*, already resolved through the fallback rules on
 *   `Invoice.btc_scope_line_items`. Don't re-derive it client-side.
 * @property stripe_scope_line_items - What the Cash App tab would bill
 *   right now, following the same "what the next round would bill"
 *   convention as `btc_scope_line_items`.
 * @property card_full_line_items - What "pay full balance by card
 *   instead" would bill right now, ignoring the BTC expectation.
 * @property btc_full_owed_usd - Every BTC-payable item's total, as a
 *   decimal string, ignoring the landlord's BTC scope -- the opt-in
 *   "pay it all by BTC instead" figure.
 * @property btc_full_line_items - What "pay full balance by BTC
 *   instead" would bill right now, ignoring the landlord's BTC scope.
 * @property settlements - Every completed payment round against this
 *   invoice, oldest first.
 * @property btc_claims - Renter-submitted BTC txid claims awaiting or
 *   past landlord review, newest first.
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
  remainder_owed_usd: string | null;
  btc_line_items: number[];
  btc_portion_usd: string;
  stripe_portion_usd: string;
  card_full_owed_usd: string;
  btc_owed_usd: string;
  is_split_payment: boolean;
  btc_settled_at: string | null;
  btc_overpaid_usd: string | null;
  stripe_settled_at: string | null;
  btc_txid: string;
  btc_credited_txid: string;
  btc_credited_usd: string | null;
  btc_watch_expires_at: string | null;
  paid_line_items: number[];
  frozen_line_items: number[];
  stripe_round_expires_at: string | null;
  btc_scope_line_items: number[];
  stripe_scope_line_items: number[];
  card_full_line_items: number[];
  btc_full_owed_usd: string;
  btc_full_line_items: number[];
  settlements: InvoiceSettlement[];
  btc_claims: BtcPaymentClaim[];
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
