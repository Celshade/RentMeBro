import type { InvoiceKind, User } from './types';


const INVOICE_KIND_LABELS: Record<InvoiceKind, string> = {
  combined: 'Rent + Gas',
  rent_only: 'Rent',
  gas_only: 'Gas',
};


/**
 * Formats an invoice kind for display.
 * @param kind - The invoice kind to format.
 * @returns A human-readable label (e.g. "Rent + Gas" for 'combined').
 */
export function formatInvoiceKind(kind: InvoiceKind): string {
  return INVOICE_KIND_LABELS[kind];
}


/** Full month names, indexed 0 (January) through 11 (December). */
export const MONTH_NAMES = [
  'January',
  'February',
  'March',
  'April',
  'May',
  'June',
  'July',
  'August',
  'September',
  'October',
  'November',
  'December',
];

/**
 * Formats a user's full name if set, otherwise falls back to email.
 * @param user - The user to format.
 * @returns The user's "First Last" name, or their email if no name is set.
 */
export function formatUserName(user: User): string {
  const name = [user.first_name, user.last_name].filter(Boolean).join(' ');
  return name || user.email;
}


/**
 * Formats a user's name alongside their email, when the two differ.
 * @param user - The user to format.
 * @returns "Name (email)", or just the email if no name is set.
 */
export function formatUserWithEmail(user: User): string {
  const name = formatUserName(user);
  return name === user.email ? name : `${name} (${user.email})`;
}
