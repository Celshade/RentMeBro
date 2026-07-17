import {
  useCallback,
  useEffect,
  useState,
  type FormEvent,
} from 'react';
import { apiFetch } from '../api/client';
import type { GasPriceEntry, MileageProfile } from '../api/types';

/**
 * Landlord form to set (or edit) the mileage profile and gas price
 * for a renter. Gas billing is optional and tied to the renter
 * directly rather than a specific lease, so it persists across
 * lease renewals/changes. Gas price fluctuates over time, so
 * multiple date-ranged entries (e.g. one per week) can coexist; a
 * `presetRange` (e.g. from a calendar week's "$" button) prefills a
 * new entry for that range.
 * @param props.renterId - The renter to configure gas billing for.
 * @param props.section - Which form(s) to show: 'mileage', 'price',
 *   or 'both' (default). Use 'price' to show only gas price entries,
 *   e.g. when jumping straight to pricing a specific week.
 * @param props.presetRange - A date range to prefill a new gas price
 *   entry with, switching the form to "add new" mode.
 * @param props.onCancel - Called if the landlord backs out without
 *   saving.
 */
export function LeaseSettings({
  renterId,
  section = 'both',
  presetRange,
  onCancel,
}: {
  renterId: number;
  section?: 'mileage' | 'price' | 'both';
  presetRange?: { from: string; to: string } | null;
  onCancel: () => void;
}) {
  const [profiles, setProfiles] = useState<MileageProfile[]>([]);
  const [profileId, setProfileId] = useState<number | null>(null);
  const [oneWayMiles, setOneWayMiles] = useState('');
  const [mpg, setMpg] = useState('');
  const [mileageEffectiveFrom, setMileageEffectiveFrom] = useState('');
  const [mileageStatus, setMileageStatus] = useState<string | null>(null);

  const [priceEntries, setPriceEntries] = useState<GasPriceEntry[]>([]);
  const [priceId, setPriceId] = useState<number | null>(null);
  const [pricePerGallon, setPricePerGallon] = useState('');
  const [priceEffectiveFrom, setPriceEffectiveFrom] = useState('');
  const [priceEffectiveTo, setPriceEffectiveTo] = useState('');
  const [priceStatus, setPriceStatus] = useState<string | null>(null);

  const loadPriceEntries = useCallback(() => {
    apiFetch<GasPriceEntry[]>('/api/gas-price-entries/').then((entries) => {
      setPriceEntries(
        entries
          .filter((entry) => entry.renter === renterId)
          .sort((a, b) => a.effective_from.localeCompare(b.effective_from))
      );
    });
  }, [renterId]);

  /** Loads a gas price entry into the form for editing. */
  function editPriceEntry(entry: GasPriceEntry) {
    setPriceId(entry.id);
    setPricePerGallon(entry.price_per_gallon);
    setPriceEffectiveFrom(entry.effective_from);
    setPriceEffectiveTo(entry.effective_to ?? '');
    setPriceStatus(null);
  }

  /** Clears the form to add a new gas price entry. */
  function startNewPriceEntry(from = '', to = '') {
    setPriceId(null);
    setPricePerGallon('');
    setPriceEffectiveFrom(from);
    setPriceEffectiveTo(to);
  }

  async function deletePriceEntry(entry: GasPriceEntry) {
    const confirmed = window.confirm(
      `Delete the gas price for ${entry.effective_from} to ` +
        `${entry.effective_to ?? 'ongoing'}?`
    );
    if (!confirmed) return;
    try {
      await apiFetch(`/api/gas-price-entries/${entry.id}/`, {
        method: 'DELETE',
      });
      loadPriceEntries();
      if (priceId === entry.id) startNewPriceEntry();
    } catch (err) {
      setPriceStatus((err as Error).message);
    }
  }

  const loadProfiles = useCallback(() => {
    apiFetch<MileageProfile[]>('/api/mileage-profiles/').then(
      (allProfiles) => {
        const renterProfiles = allProfiles.filter(
          (profile) => profile.renter === renterId
        );
        setProfiles(renterProfiles);
        const current = renterProfiles[0];
        if (!current) return;
        setProfileId(current.id);
        setOneWayMiles(current.one_way_miles);
        setMpg(current.mpg);
        setMileageEffectiveFrom(current.effective_from);
      }
    );
  }, [renterId]);

  useEffect(() => {
    loadProfiles();
  }, [loadProfiles]);

  useEffect(() => {
    loadPriceEntries();
  }, [loadPriceEntries]);

  useEffect(() => {
    if (!presetRange) return;
    const existing = priceEntries.find(
      (entry) =>
        entry.effective_from <= presetRange.to &&
        (entry.effective_to === null || entry.effective_to >= presetRange.from)
    );
    if (existing) {
      setPriceId(existing.id);
      setPricePerGallon(existing.price_per_gallon);
    } else {
      setPriceId(null);
      setPricePerGallon('');
    }
    setPriceEffectiveFrom(presetRange.from);
    setPriceEffectiveTo(presetRange.to);
  }, [presetRange, priceEntries]);

  async function handleMileageSubmit(event: FormEvent) {
    event.preventDefault();
    setMileageStatus(null);
    try {
      const body = {
        renter: renterId,
        one_way_miles: oneWayMiles,
        mpg,
        effective_from: mileageEffectiveFrom,
      };
      const path = profileId
        ? `/api/mileage-profiles/${profileId}/`
        : '/api/mileage-profiles/';
      const profile = await apiFetch<MileageProfile>(path, {
        method: profileId ? 'PATCH' : 'POST',
        body,
      });
      setProfileId(profile.id);
      setMileageStatus('Saved.');
      loadProfiles();
    } catch (err) {
      setMileageStatus((err as Error).message);
    }
  }

  async function handlePriceSubmit(event: FormEvent) {
    event.preventDefault();
    setPriceStatus(null);

    if (!priceEffectiveTo) {
      setPriceStatus('Effective to is required — prices are set per week.');
      return;
    }
    const daySpan =
      (new Date(priceEffectiveTo).getTime() -
        new Date(priceEffectiveFrom).getTime()) /
      86400000;
    if (daySpan !== 6) {
      setPriceStatus('Gas prices must cover exactly one week (7 days).');
      return;
    }
    const overlapsAnother = priceEntries.some(
      (entry) =>
        entry.id !== priceId &&
        entry.effective_from <= priceEffectiveTo &&
        (entry.effective_to === null ||
          entry.effective_to >= priceEffectiveFrom)
    );
    if (overlapsAnother) {
      setPriceStatus('That week overlaps an existing gas price entry.');
      return;
    }

    try {
      const body = {
        renter: renterId,
        price_per_gallon: pricePerGallon,
        effective_from: priceEffectiveFrom,
        effective_to: priceEffectiveTo,
      };
      const path = priceId
        ? `/api/gas-price-entries/${priceId}/`
        : '/api/gas-price-entries/';
      await apiFetch<GasPriceEntry>(path, {
        method: priceId ? 'PATCH' : 'POST',
        body,
      });
      if (presetRange) {
        onCancel();
        return;
      }
      setPriceStatus('Saved.');
      loadPriceEntries();
      startNewPriceEntry();
    } catch (err) {
      setPriceStatus((err as Error).message);
    }
  }

  const showMileage = section === 'mileage' || section === 'both';
  const showPrice = section === 'price' || section === 'both';
  const presetMonth = presetRange?.from.slice(0, 7);
  const visiblePriceEntries = presetMonth
    ? priceEntries.filter((entry) =>
        entry.effective_from.startsWith(presetMonth)
      )
    : priceEntries;

  return (
    <div>
      {showMileage && (
        <>
          <h3>Mileage profile</h3>
          {profiles.length > 0 && (
            <ul>
              {profiles.map((profile) => (
                <li key={profile.id}>
                  {profile.one_way_miles} mi one-way, {profile.mpg} MPG —
                  effective {profile.effective_from} (
                  {profile.full_day_miles} mi/day)
                </li>
              ))}
            </ul>
          )}
          <form onSubmit={handleMileageSubmit}>
            <label htmlFor="one_way_miles">One-way commute miles</label>
            <input
              id="one_way_miles"
              type="number"
              step="0.01"
              required
              value={oneWayMiles}
              onChange={(e) => setOneWayMiles(e.target.value)}
            />
            <label htmlFor="mpg">Vehicle MPG</label>
            <input
              id="mpg"
              type="number"
              step="0.01"
              required
              value={mpg}
              onChange={(e) => setMpg(e.target.value)}
            />
            <label htmlFor="mileage_effective_from">Effective from</label>
            <input
              id="mileage_effective_from"
              type="date"
              required
              value={mileageEffectiveFrom}
              onChange={(e) => setMileageEffectiveFrom(e.target.value)}
            />
            <button type="submit">
              {profileId ? 'Update mileage profile' : 'Save mileage profile'}
            </button>
            <button type="button" onClick={onCancel}>
              Cancel
            </button>
            {mileageStatus && <p>{mileageStatus}</p>}
          </form>
        </>
      )}

      {showPrice && (
        <>
          <h3>Gas price</h3>
          {visiblePriceEntries.length > 0 && (
            <ul>
              {visiblePriceEntries.map((entry) => (
                <li key={entry.id}>
                  ${entry.price_per_gallon}/gal — {entry.effective_from}
                  {' to '}
                  {entry.effective_to ?? 'ongoing'}{' '}
                  {priceId !== entry.id && (
                    <button
                      type="button"
                      onClick={() => editPriceEntry(entry)}
                    >
                      Edit
                    </button>
                  )}{' '}
                  <button
                    type="button"
                    onClick={() => deletePriceEntry(entry)}
                  >
                    Delete
                  </button>
                </li>
              ))}
            </ul>
          )}
          <form onSubmit={handlePriceSubmit}>
            <label htmlFor="price_per_gallon">Price per gallon</label>
            <input
              id="price_per_gallon"
              type="number"
              step="0.001"
              required
              value={pricePerGallon}
              onChange={(e) => setPricePerGallon(e.target.value)}
            />
            <label htmlFor="price_effective_from">Effective from</label>
            <input
              id="price_effective_from"
              type="date"
              required
              value={priceEffectiveFrom}
              onChange={(e) => setPriceEffectiveFrom(e.target.value)}
            />
            <label htmlFor="price_effective_to">Effective to</label>
            <input
              id="price_effective_to"
              type="date"
              required
              value={priceEffectiveTo}
              onChange={(e) => setPriceEffectiveTo(e.target.value)}
            />
            <button type="submit">
              {priceId ? 'Update gas price' : 'Save gas price'}
            </button>
            <button type="button" onClick={onCancel}>
              Cancel
            </button>
            {priceStatus && <p>{priceStatus}</p>}
          </form>
        </>
      )}
    </div>
  );
}
