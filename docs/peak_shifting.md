# Same-day aggregate peak shifting

This diagnostic estimates a constrained potential from the saved hourly household curve. It does not identify devices, locate appliance cycles, or certify achievable savings.

```sh
python -m tibber_local.shifting --start 2025-01-01 --end 2025-10-01 --daily-fraction 0.10
```

The local end date is exclusive. Results, including detailed energy transfers, are written to `peak_shifting.json` in the private runtime directory. For a daylight-only destination window, add `--target-start-hour 7 --target-end-hour 23`. Add `--delay-only` to prohibit moving energy to an earlier physical hour. The default permits night hours and both advancement and delay within the same local day.

## Explicit assumptions

- The source peaks are the three largest physical hourly loads in each local day, selected by energy, not price.
- A daily 25th-percentile hourly consumption level is retained as a modelling reserve. It is not an identified refrigerator, standby load, or certified inflexible demand.
- At most half the energy above that reserve may be removed from each source peak. The selected daily fraction is an additional total energy cap, not a promise that the cap can be reached.
- Destinations are other allowed hours within that local day. At most 0.5 kWh may be added to an hour, and the resulting hourly load must not exceed the original daily maximum.
- Every day's kWh remains identical. Therefore monthly volume is unchanged; a fixed monthly SLP rate would produce the same cost before and after these transfers.
- Only profitable transfers are made. Negative prices retain their sign. No energy is moved between local days or calendar months.

The optimizer solves a fractional transport problem with these source, destination, daily-budget and time-order constraints. Residual rerouting avoids a greedy choice blocking a better later allocation. DST identities remain UTC-based; a 23- or 25-hour day retains its physical intervals.

Savings are the transferred kWh multiplied by the original minus destination gross hourly subscription quote. The reported shifted cost is recorded API variable cost minus that estimated change, keeping the small recorded-cost/quoted-price reconciliation difference intact. Fixed fees are unchanged and excluded.

## Interpretation

This is retrospective optimization over observed peaks and prices. It assumes the selected energy could have been made available in the allowed destination window; actual device readiness is unknown. The free-time mode can move evening energy to earlier hours, which is infeasible for a device loaded only after dinner. The delay-only mode is stricter but still permits divisible energy and does not represent an uninterrupted cycle, weekly use frequency, washing/drying precedence or a completion deadline.

Use it to assess the scale of a possible opportunity and compare constraints. For personalized appliance savings, replace divisible transfers with measured cycle profiles and actual ready times, deadlines, program choices and usage frequency. Do not interpret the daily reserve or flexible fraction as measured appliance attribution. Hourly data also cannot reconstruct exact within-hour settlement after a market resolution change.
