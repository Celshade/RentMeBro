import type { User } from './types';

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
