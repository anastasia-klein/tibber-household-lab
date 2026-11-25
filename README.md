# Tibber Household Lab

A local dashboard for exploring your own Tibber electricity history: when you use energy, how consumption timing affects cost, and how an hourly price scenario compares with a monthly average.

**Public code. Private household history.** The application runs on your computer, at `127.0.0.1`. There is no hosted dashboard or shared backend. Bring your own Tibber API token; no account data is included in this repository.

Related research: [Germany Power & Renewables](https://github.com/anastasia-klein/germany-power-renewables), which examines the public German electricity market using SMARD, Microsoft Fabric and Power BI.

## Run locally

Requires **Python 3.11 or newer** and a browser. Download this repository as a ZIP and extract it, or clone it:

```sh
git clone https://github.com/anastasia-klein/tibber-household-lab.git
cd tibber-household-lab
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
python -m tibber_local
```

On Windows, use `py -3.11 -m venv .venv` followed by `.venv\Scripts\activate` instead of the two environment commands above. Then run the same installation and launch commands. The package installs timezone data on Windows.

The browser opens at **http://127.0.0.1:8767**. In **Connection**, enter your [personal Tibber token](https://developer.tibber.com/settings/access-token), choose a home and a historical start date. The initial download runs in the background; saved history remains available without an internet connection. Leave the terminal running while using the dashboard; press Ctrl+C to stop it.

Try synthetic data first, with no account or API calls:

```sh
python -m tibber_local --demo
```

Demo history is isolated from real history. Restart without `--demo` to connect your account. If port 8767 is already in use, add `--port 8768`.

An environment variable `TIBBER_API_TOKEN` or an ignored checkout-local `.env` file can also supply the token; see [.env.example](.env.example). Do not put a real key in a command-line argument, commit, issue or screenshot. After changing source code, rerun `python -m pip install .`, or use `python -m pip install -e .` for development.

## Explore and update

- **History & cost:** monthly consumption, API-recorded variable costs, hourly and monthly-average scenarios, daily consumption and optional known monthly rates.
- **Daily patterns:** mean hourly consumption and prices for weekdays versus weekends, a month/hour heatmap and the largest observed hourly loads.
- **Data & methods:** history coverage, missing intervals, calculation definitions and refresh settings.

Year, month and weekday/weekend filters apply across pages. Calendar grouping uses the home's timezone; UTC identifies intervals, preserving both repeated autumn hours. Missing observations remain missing, not zero.

Use **Refresh history** for an incremental update. This rechecks the latest 45 days for revisions and loads through yesterday. Choose **Recheck all history** for older gaps or corrections. Automatic refresh can run every 6, 12, 24 or 168 hours **while the application is running**; the default is manual. Years are discovered from saved data, so new years appear as history grows.

For an external OS scheduler, the same local environment can run:

```sh
python -m tibber_local --refresh
python -m tibber_local --refresh --full
```

No scheduler or background service is installed automatically. Failed refreshes retain the previous saved history; consumption and prices are committed together after validation. Multi-home accounts choose one home per data directory; changing homes requires a separate directory.

## What the scenarios mean

For hour `h`, consumption is `q_h` in kWh and the subscription price is `p_h` in currency units per kWh:

- **Recorded API cost:** sum of `consumption.cost`. Tibber defines this as consumption × applied unit price, including VAT where applicable, excluding fees where applicable, production reward and Grid Rewards. It is not a complete electricity bill.
- **Hourly scenario:** `sum(q_h * p_h)`, using `currentSubscription.priceInfoRange.total` at hourly resolution. Historical prices relate to the current/latest subscription; they are not proof of historic contract terms or a guaranteed quote for another tariff.
- **Monthly-average scenario:** for each local calendar month, multiply your selected consumption by the arithmetic mean of **all** hourly subscription prices in that month. Sum the monthly results. A complete price month is required; an unfinished current month is omitted from this comparison. Applying a weekday filter does not change the month's reference rate.
- **Hourly minus monthly average:** positive means the hypothetical monthly-average scenario costs less, negative means hourly costs less. Both totals and the difference use identical comparable hours. Other recorded costs may cover a larger period.
- **Known monthly rate:** optionally enter a bill/contract rate for a month, on the same tax and variable-charge basis. This separate comparator is not inferred from the API and does not include fixed fees.

The hypothetical monthly average is **not necessarily Tibber's billed monthly-average tariff**. A tariff recommendation needs contract or invoice reconciliation, including any different fees and settlement rules. Changing API prices alone does not prove how a contract is billed.

This release requests **hourly consumption and hourly aggregated prices**, including in years when the market uses quarter-hourly prices. It cannot reconstruct exact quarter-hourly settlement or simulate quarter-hourly device control. Unsupported sub-hourly inputs are rejected rather than silently misaligned.

Hourly profiles are descriptive. They do not identify appliances, confirm whether readings are measured or estimated, or establish how much energy can actually be shifted. Feasible load-shifting scenarios are deferred until household constraints and metering provenance are understood.

Field definitions and pagination limits: [official Tibber GraphQL reference](https://developer.tibber.com/api/reference.md). Read-only queries are used; this app never changes your Tibber tariff or device settings.

## Where private files live

Runtime history, known rates and configuration stay outside the source checkout:

| Platform | Default directory |
| --- | --- |
| macOS | `~/Library/Application Support/Tibber Household Lab` |
| Linux | `${XDG_DATA_HOME:-~/.local/share}/tibber-household-lab` |
| Windows | `%LOCALAPPDATA%\TibberHouseholdLab` |

`history.sqlite3` stores fetched intervals and rates; `config.json` stores the chosen home and update settings; `token` stores the locally entered credential. Environment/`.env` tokens take precedence over the saved token. Set `TIBBER_LOCAL_DATA_DIR` to choose another private directory **outside your Git checkout**. Back up that directory privately to move your history to another computer; using only the public repository and your own token is sufficient for a fresh download.

The token file is not encrypted by this application. POSIX file permissions restrict local access; Windows users should keep the directory in their own protected user profile. The server accepts loopback connections only, checks Host and write origins, requires a session for data access, serves only allowlisted assets and sends no telemetry. No external fonts, chart libraries or analytics are loaded. This is a single-user local application, not a hardened multi-user server; do not expose its port publicly.

The ignore rules exclude credentials and common data formats. These rules do not replace reviewing files before a public commit. Never upload your runtime directory, real-data screenshots, bills or debug exports to this repository or GitHub Actions. CI uses synthetic data only.

## Development checks

```sh
python -m unittest discover -s tests -v
node --check tibber_local/static/app.js
```

Tests cover consumption weighting, negative prices, DST, incomplete months, missing values, pagination, separate tariff rates, session access, cross-origin requests and DNS-rebinding Host checks. GitHub Actions also checks installation on macOS, Linux and Windows. The UI uses HTML, CSS, JavaScript and SVG; the backend uses Python's standard library and SQLite.
