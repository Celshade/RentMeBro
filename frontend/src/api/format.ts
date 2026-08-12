import type { InvoiceKind, User } from './types';

const SATS_PER_BTC = 100_000_000;

const INVOICE_KIND_LABELS: Record<InvoiceKind, string> = {
  combined: 'Rent + Gas',
  rent_only: 'Rent-Only',
  gas_only: 'Gas-Only',
};


/**
 * Formats an invoice kind for display.
 * @param kind - The invoice kind to format.
 * @returns A human-readable label (e.g. "Rent + Gas" for 'combined').
 */
export function formatInvoiceKind(kind: InvoiceKind): string {
  return INVOICE_KIND_LABELS[kind];
}


/**
 * Formats a decimal-string dollar amount to exactly 2 decimal places.
 * @param amount - A decimal string (e.g. "4.200" or "4.2").
 * @returns The amount rounded to 2 decimal places (e.g. "4.20").
 */
export function formatMoney(amount: string): string {
  return Number(amount).toFixed(2);
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
 * Formats a billing period's month and year for display.
 * @param month - The 1-indexed month (1 for January, 12 for December).
 * @param year - The 4-digit year.
 * @returns A human-readable label (e.g. "June 2026").
 */
export function formatBillingPeriod(month: number, year: number): string {
  return `${MONTH_NAMES[month - 1]} ${year}`;
}

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
 * Formats a satoshi amount as a BTC decimal string.
 * @param sats - An amount in satoshis.
 * @returns The equivalent BTC amount, fixed to 8 decimal places.
 */
export function satsToBtc(sats: number): string {
  return (sats / SATS_PER_BTC).toFixed(8);
}


/**
 * Converts a BTC decimal amount to whole satoshis.
 * @param btc - A BTC amount, as typed by the user (e.g. "0.0021").
 * @returns The equivalent amount in satoshis, rounded to the nearest
 *   whole sat.
 */
export function btcToSats(btc: string): number {
  return Math.round(Number(btc) * SATS_PER_BTC);
}


/**
 * Formats a satoshi amount's estimated USD value at a given BTC price.
 * @param sats - An amount in satoshis.
 * @param usdPerBtc - The current price of 1 BTC in USD.
 * @returns The estimated USD value, fixed to 2 decimal places.
 */
export function satsToUsdEstimate(sats: number, usdPerBtc: number): string {
  return ((sats / SATS_PER_BTC) * usdPerBtc).toFixed(2);
}


/**
 * Converts a USD decimal amount to its equivalent BTC amount.
 * @param usd - A USD amount, as typed by the user (e.g. "50.00").
 * @param usdPerBtc - The current price of 1 BTC in USD.
 * @returns The equivalent BTC amount, fixed to 8 decimal places.
 */
export function usdToBtc(usd: string, usdPerBtc: number): string {
  return (Number(usd) / usdPerBtc).toFixed(8);
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


/**
 * Formats a millisecond duration as a countdown clock.
 * @param ms - The remaining duration, in milliseconds. Negative values
 *   are clamped to zero rather than showing a negative countdown.
 * @returns "M:SS" (e.g. "14:59").
 */
export function formatCountdown(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${String(seconds).padStart(2, '0')}`;
}


/**
 * Formats an ISO timestamp as a local wall-clock time.
 * @param iso - An ISO 8601 timestamp.
 * @returns The local time (e.g. "2:45 PM").
 */
export function formatClockTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], {
    hour: 'numeric',
    minute: '2-digit',
  });
}


/**
 * Middle-truncates a string, replacing its center with an ellipsis.
 * @param value - The string to truncate.
 * @param headLength - How many leading characters to keep.
 * @param tailLength - How many trailing characters to keep.
 * @returns The truncated string (e.g. "bc1qar0s...5mdq"), or the value
 *   unchanged if it is already short enough that truncating it would
 *   not save space.
 */
function truncateMiddle(
  value: string,
  headLength: number,
  tailLength: number
): string {
  if (value.length <= headLength + tailLength + 3) return value;
  return `${value.slice(0, headLength)}...${value.slice(-tailLength)}`;
}


/**
 * Middle-truncates a BTC address for compact display.
 * @param address - A full BTC address.
 * @returns The address with its middle replaced by an ellipsis (e.g.
 *   "bc1qar0s...5mdq"), or the address unchanged if it is already short
 *   enough that truncating it would not save space.
 */
export function formatBtcAddressShort(address: string): string {
  return truncateMiddle(address, 8, 4);
}


/**
 * Middle-truncates a transaction id for compact display.
 * @param txid - A full 64-hex-character transaction id.
 * @returns The txid with its middle replaced by an ellipsis.
 */
export function formatTxidShort(txid: string): string {
  return truncateMiddle(txid, 8, 6);
}


const MEMPOOL_BASE_URL =
  (import.meta.env.VITE_MEMPOOL_BASE_URL as string | undefined) ??
  'https://mempool.space';

/**
 * Builds a mempool.space (or configured explorer) link for a transaction.
 * @param txid - A full transaction id.
 * @returns The transaction's explorer URL.
 */
export function mempoolTxUrl(txid: string): string {
  return `${MEMPOOL_BASE_URL}/tx/${txid}`;
}
