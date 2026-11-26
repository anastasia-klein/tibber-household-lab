# Monthly billing: SLP weighting, not an equal-hour mean

Verified against Tibber Germany's public documentation on 2026-11-25. This describes the supplier's stated billing method; it does not certify an individual account's tariff or meter transition date.

## Confirmed supplier method

For monthly dynamic billing without interval settlement, Tibber states that market prices are weighted by a standard load profile (Standardlastprofil, SLP). Meter readings determine the billed consumption; where readings are missing, consumption is estimated and later corrected.

For a month with market prices `p_t` and the applicable standard-profile interval energy weights `s_t`, the weighted market-price component is:

```
slp_market_rate = sum(p_t * s_t) / sum(s_t)
```

This is a mathematical expression of the stated weighting method. The complete billed variable rate must also include the applicable retail charges and taxes on a consistent net/gross basis. Fixed fees and billing adjustments are accounted for separately. If charges or settlement methods change within a month, reconcile the relevant subperiods rather than applying one annual rate.

The weights represent a typical customer-group load curve. They are neither the household's measured interval consumption nor Germany's aggregate grid load. Do not assume a generic H0 or H25 profile matches a particular account without confirmation.

## What the application currently calculates

`monthly_mean_rate` is an **unweighted research benchmark**: the arithmetic mean of the available hourly subscription prices over a complete local calendar month. `monthly_mean_cost` applies that rate to selected household consumption. These values do **not** implement SLP billing and must not be described as a saving against the actual monthly tariff.

The optional **known monthly rate** input can use a variable rate verified against a bill, with the same currency and tax basis as the hourly comparison. Do not enter the total bill divided by kWh if it includes fixed fees, corrections, or unrelated periods.

No verified account-specific SLP weights or invoice rates are distributed with this project. An unreconciled API consumption curve must not be silently substituted for the standard profile.

## Evidence needed for an account-specific comparison

1. A bill from a complete month settled on the monthly dynamic method, including the variable price breakdown, net/gross treatment, billed consumption, fixed fees and corrections.
2. The applicable profile identifier, actual profile series/calendar rules, and its effective dates, or a confirmed supplier monthly rate for each comparison month.
3. The effective dates of interval settlement versus monthly settlement; a running subscription alone does not identify these transitions.
4. Independent measured household interval consumption for the dynamic counterfactual. If API consumption is already an SLP allocation, it cannot demonstrate how the actual household would have performed on interval pricing.

The current hourly export cannot reproduce exact quarter-hourly settlement after a resolution change. A precise reconstruction needs matched native interval prices and measured consumption, or the supplier's verified monthly rate for the monthly baseline.

## Sources

- [Tibber: how the electricity bill is calculated](https://support.tibber.com/hc/de/articles/48142921846673-So-wird-deine-Stromrechnung-berechnet) — monthly dynamic pricing uses an SLP-weighted market average.
- [Tibber: consumption displayed in the app](https://support.tibber.com/hc/de/articles/48143836792849-Deinen-Stromverbrauch-in-der-Tibber-App-ansehen) — measured and estimated/profiled data, and their replacement when final data arrives.
- [Tibber: how dynamic prices work](https://support.tibber.com/hc/de/articles/48143572102033-So-funktionieren-dynamische-Strompreise) — moving consumption within the day does not reduce the monthly SLP bill for unchanged monthly energy.
- [Tibber: from smart-meter installation to interval billing](https://support.tibber.com/hc/de/articles/50493239194257-Vom-Smart-Meter-Einbau-bis-zur-dynamischen-Abrechnung) — meter installation and the actual settlement-method activation are separate steps.

Public documentation changes over time. Historical bills and the applicable contract version take precedence for reconstructing earlier periods.

## Reconstruct an explicit H0 counterfactual

The optional `tibber_local.slp` module reads the original BDEW H0 workbook from [the official profile archive](https://www.bdew.de/media/documents/Profile.zip). It applies the nine season/day-type curves and the daily H0 dynamization polynomial from [BDEW's method document](https://www.bdew.de/media/documents/2000131_Anwendung-repraesentativen_Lastprofile-Step-by-step.pdf), including regional holidays supplied explicitly as ISO dates, Sunday treatment of holidays, Saturday treatment of 24/31 December, and physical DST intervals.

For each calendar month it weights the subscription's gross variable prices by H0 interval energy, then applies that monthly rate to the household's selected consumption. A partial consumption month still uses the complete calendar month's reference prices. Recorded API interval costs are retained separately from hourly price-times-volume estimates. Fixed charges are assumed identical and excluded from both options.

Install the optional XLS reader and provide local input paths:

```sh
python -m pip install '.[slp]'
python -m tibber_local.slp --profile-xls /path/to/Haushalt-Lastprofil.xls --holidays-json /private/path/holidays.json --start 2025-01-01 --end 2025-10-01
```

The end date is exclusive. The holiday file is a JSON array of ISO dates for the appropriate region and years; an explicitly empty array represents no public holidays. For Baden-Württemberg, consult the [state's official holiday list](https://im.baden-wuerttemberg.de/de/service/feiertage). The raw BDEW workbook is downloaded separately rather than redistributed in this repository.

For German market months from October 2025, supply a private JSON array of native quarter-hour subscription-price nodes using `--quarter-prices-json`. Alternatively, `--allow-hourly-price-approximation` explicitly permits an hourly-price approximation. Incomplete native-price months are rejected rather than silently filled with hourly prices. Native quarter-hour prices improve the SLP baseline but do not reconstruct unavailable quarter-hour household measurements.

Results are saved to `slp_comparison.json` in the private runtime directory. They remain a model-based H0 counterfactual until the assigned profile and applicable tariff components are confirmed. Close matching against observed allocated curves is evidence for the profile choice, not a substitute for account documentation. Do not store reconstructed rates as bill-verified rates. Where savings are small, report them as estimates and show assumptions rather than claiming an exact invoice or a decisive tariff winner.
