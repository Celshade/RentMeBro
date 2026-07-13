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
