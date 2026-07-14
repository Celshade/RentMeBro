import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { apiFetch } from '../api/client';
import type { GasPriceEntry, MileageProfile } from '../api/types';

/**
 * Landlord form to set (or edit) the mileage profile and gas price
 * for a renter. Gas billing is optional and tied to the renter
 * directly rather than a specific lease, so it persists across
 * lease renewals/changes.
 * @param props.renterId - The renter to configure gas billing for.
 */
export function LeaseSettings({ renterId }: { renterId: number }) {
  const [profiles, setProfiles] = useState<MileageProfile[]>([]);
  const [profileId, setProfileId] = useState<number | null>(null);
  const [oneWayMiles, setOneWayMiles] = useState('');
  const [mpg, setMpg] = useState('');
  const [mileageEffectiveFrom, setMileageEffectiveFrom] = useState('');
  const [mileageStatus, setMileageStatus] = useState<string | null>(null);

  const [priceId, setPriceId] = useState<number | null>(null);
  const [pricePerGallon, setPricePerGallon] = useState('');
  const [priceEffectiveFrom, setPriceEffectiveFrom] = useState('');
  const [priceEffectiveTo, setPriceEffectiveTo] = useState('');
  const [priceStatus, setPriceStatus] = useState<string | null>(null);

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
    apiFetch<GasPriceEntry[]>('/api/gas-price-entries/').then((entries) => {
      const current = entries.find((entry) => entry.renter === renterId);
      if (!current) return;
      setPriceId(current.id);
      setPricePerGallon(current.price_per_gallon);
      setPriceEffectiveFrom(current.effective_from);
      setPriceEffectiveTo(current.effective_to ?? '');
    });
  }, [renterId]);

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
    try {
      const body = {
        renter: renterId,
        price_per_gallon: pricePerGallon,
        effective_from: priceEffectiveFrom,
        effective_to: priceEffectiveTo || null,
      };
      const path = priceId
        ? `/api/gas-price-entries/${priceId}/`
        : '/api/gas-price-entries/';
      const entry = await apiFetch<GasPriceEntry>(path, {
        method: priceId ? 'PATCH' : 'POST',
        body,
      });
      setPriceId(entry.id);
      setPriceStatus('Saved.');
    } catch (err) {
      setPriceStatus((err as Error).message);
    }
  }

  return (
    <div>
      <h3>Mileage profile</h3>
      {profiles.length > 0 && (
        <ul>
          {profiles.map((profile) => (
            <li key={profile.id}>
              {profile.one_way_miles} mi one-way, {profile.mpg} MPG —
              effective {profile.effective_from} ({profile.full_day_miles}{' '}
              mi/day)
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
        {mileageStatus && <p>{mileageStatus}</p>}
      </form>

      <h3>Gas price</h3>
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
        <label htmlFor="price_effective_to">Effective to (optional)</label>
        <input
          id="price_effective_to"
          type="date"
          value={priceEffectiveTo}
          onChange={(e) => setPriceEffectiveTo(e.target.value)}
        />
        <button type="submit">
          {priceId ? 'Update gas price' : 'Save gas price'}
        </button>
        {priceStatus && <p>{priceStatus}</p>}
      </form>
    </div>
  );
}
