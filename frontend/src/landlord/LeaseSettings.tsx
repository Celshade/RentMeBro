import { useState, type FormEvent } from 'react';
import { apiFetch } from '../api/client';

/**
 * Landlord form to set the mileage profile and log a gas price for a
 * lease.
 * @param props.leaseId - The lease to configure.
 */
export function LeaseSettings({ leaseId }: { leaseId: number }) {
  const [oneWayMiles, setOneWayMiles] = useState('');
  const [mpg, setMpg] = useState('');
  const [mileageEffectiveFrom, setMileageEffectiveFrom] = useState('');
  const [mileageStatus, setMileageStatus] = useState<string | null>(null);

  const [pricePerGallon, setPricePerGallon] = useState('');
  const [priceEffectiveFrom, setPriceEffectiveFrom] = useState('');
  const [priceEffectiveTo, setPriceEffectiveTo] = useState('');
  const [priceStatus, setPriceStatus] = useState<string | null>(null);

  async function handleMileageSubmit(event: FormEvent) {
    event.preventDefault();
    setMileageStatus(null);
    try {
      await apiFetch('/api/mileage-profiles/', {
        method: 'POST',
        body: {
          lease: leaseId,
          one_way_miles: oneWayMiles,
          mpg,
          effective_from: mileageEffectiveFrom,
        },
      });
      setMileageStatus('Saved.');
    } catch (err) {
      setMileageStatus((err as Error).message);
    }
  }

  async function handlePriceSubmit(event: FormEvent) {
    event.preventDefault();
    setPriceStatus(null);
    try {
      await apiFetch('/api/gas-price-entries/', {
        method: 'POST',
        body: {
          lease: leaseId,
          price_per_gallon: pricePerGallon,
          effective_from: priceEffectiveFrom,
          effective_to: priceEffectiveTo || null,
        },
      });
      setPriceStatus('Saved.');
    } catch (err) {
      setPriceStatus((err as Error).message);
    }
  }

  return (
    <div>
      <h3>Mileage profile</h3>
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
        <button type="submit">Save mileage profile</button>
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
        <button type="submit">Save gas price</button>
        {priceStatus && <p>{priceStatus}</p>}
      </form>
    </div>
  );
}
