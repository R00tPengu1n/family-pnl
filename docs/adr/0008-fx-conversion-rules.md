# ADR-0008: Exchange rates and conversion rules

- Status: accepted
- Date: 2026-10-24

## Context

Family members record operations in RUB, BYN and USD and want totals in one currency.
The spec requires the National Bank of Belarus (NBRB) as the source, conversion at the rate
**on the date of the operation**, permanent storage of historical rates, the nearest earlier
rate when a date has none, and the last known rate when NBRB is down.

## Decision

- **Representation.** A rate is BYN per one unit of a currency (`fx_rates`, `NUMERIC(18, 8)`,
  one row per currency and date), as NBRB publishes it; `Cur_Scale` is applied on import
  (RUB is quoted per 100). Cross rates go through BYN: RUB → USD = BYN/RUB ÷ BYN/USD.
- **Exactness.** Rates are parsed from the JSON text straight into `Decimal`. Conversions
  multiply and divide in one step and are not rounded; `Money.rounded()` applies the single
  `ROUND_HALF_UP` step to cents at the end of a calculation (sums of many small conversions
  would drift otherwise). The spec's code example was updated accordingly.
- **Source of a rate for a date**, per currency, in this order:
  1. the stored official rate for that date;
  2. NBRB for that date — stored for good with `INSERT … ON CONFLICT DO NOTHING` (official
     rates never change; concurrent first requests both succeed);
  3. the nearest earlier stored rate (the date is not published yet, e.g. a future date —
     NBRB publishes every calendar day, weekends included);
  4. with nothing stored, earlier days from NBRB, at most seven days back.
- **NBRB unavailable** (network, HTTP error, unexpected payload): the last known stored rate on
  or before the date is used and `fx_rate_source_unavailable` is logged. With nothing stored
  the API answers 503 `rates_unavailable`.
- **Fallbacks are labelled, not stored.** Every quote carries its own `rate_date`; a fallback is
  never written under the requested date, so the real rate can still arrive later.
- The daily refresh of the current rate is a worker job (Task 24); the API fetches on demand.

## Consequences

- Reports are reproducible: the same operation converts with the same stored rate forever.
- A conversion for today before NBRB publishes may use yesterday's rate; the response says so
  through `rate_date`.
- Eight decimal places are enough for current RUB, USD and BYN quotes; a currency quoted per
  10 000 units with many digits would lose precision and needs a wider column.
