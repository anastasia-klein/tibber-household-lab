"""Hourly research metrics, with explicit coverage and tariff limitations."""
import calendar
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import mean, median
from zoneinfo import ZoneInfo

UTC = timezone.utc


def instant(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Every interval must include a UTC offset.")
    return result.astimezone(UTC)


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def normalize(consumption, prices):
    price_map = {}
    for row in prices:
        key = instant(row["startsAt"])
        if key in price_map and row != price_map[key]:
            raise ValueError("Conflicting price intervals.")
        price_map[key] = row
    starts = sorted(price_map)
    if any((b-a).total_seconds() < 3600 for a, b in zip(starts, starts[1:])):
        raise ValueError("Sub-hourly prices require a separate settlement model; request hourly aggregated prices.")
    rows, seen = [], set()
    for row in consumption:
        start, end = instant(row["from"]), instant(row["to"])
        if start in seen:
            raise ValueError("Duplicate consumption interval.")
        seen.add(start)
        if (end - start).total_seconds() != 3600:
            raise ValueError("This release requires hourly consumption; sub-hourly data must not be treated as hourly.")
        if row.get("consumptionUnit") not in (None, "kWh"):
            raise ValueError("Unsupported consumption unit; expected kWh.")
        values = [row.get(k) for k in ("consumption", "cost", "unitPrice")]
        if any(v is not None and not number(v) for v in values):
            raise ValueError("Invalid numeric consumption field.")
        if row.get("consumption") is not None and row["consumption"] < 0:
            raise ValueError("Negative consumption needs separate production accounting.")
        price = price_map.get(start, {})
        if price.get("currency") and row.get("currency") and price["currency"] != row["currency"]:
            raise ValueError("Consumption and prices use different currencies.")
        if price.get("total") is not None and not number(price["total"]):
            raise ValueError("Invalid price field.")
        rows.append({"utc": start, "end": end, "kwh": row.get("consumption"),
                     "cost": row.get("cost"), "applied": row.get("unitPrice"),
                     "price": price.get("total"), "currency": row.get("currency") or price.get("currency")})
    currencies = {r["currency"] for r in rows if r["currency"]}
    if len(currencies) > 1:
        raise ValueError("Mixed currencies cannot be aggregated.")
    return sorted(rows, key=lambda r: r["utc"]), price_map


def month_bounds(month, zone):
    year, m = map(int, month.split("-"))
    start = datetime(year, m, 1, tzinfo=zone)
    end = datetime(year + (m == 12), 1 if m == 12 else m + 1, 1, tzinfo=zone)
    return start.astimezone(UTC), end.astimezone(UTC)


def expected_hours(month, zone):
    start, end = month_bounds(month, zone)
    return int((end - start).total_seconds() / 3600)


def total_or_none(rows, field):
    return sum(r[field] for r in rows) if rows and all(number(r[field]) for r in rows) else None


def quantile(values, q):
    if not values:
        return None
    values = sorted(values)
    x = (len(values) - 1) * q
    lo = int(x)
    return values[lo] + (values[min(lo + 1, len(values) - 1)] - values[lo]) * (x - lo)


def analyze(consumption, prices, zone_name, year="all", month="all", daytype="all", rates=None):
    zone = ZoneInfo(zone_name)
    rows, price_map = normalize(consumption, prices)
    rates = rates or {}
    for r in rows:
        local = r["utc"].astimezone(zone)
        r.update(month=local.strftime("%Y-%m"), day=local.date().isoformat(), hour=local.hour,
                 weekend=local.weekday() >= 5)
    years = sorted({r["day"][:4] for r in rows})
    selected = [r for r in rows if (year == "all" or r["day"][:4] == year)
                and (month == "all" or r["month"][5:] == month)
                and (daytype == "all" or r["weekend"] == (daytype == "weekend"))]
    monthly_prices = defaultdict(dict)
    for when, p in price_map.items():
        if number(p.get("total")):
            monthly_prices[when.astimezone(zone).strftime("%Y-%m")][when] = p["total"]
    months = []
    groups = defaultdict(list)
    for r in selected:
        groups[r["month"]].append(r)
    comparison_rows = []
    for m, records in sorted(groups.items()):
        start, end = month_bounds(m, zone)
        expected = expected_hours(m, zone)
        keys = {start + timedelta(hours=i) for i in range(expected)}
        complete_prices = set(monthly_prices[m]) == keys
        average = mean(monthly_prices[m].values()) if complete_prices else None
        valid = [r for r in records if number(r["kwh"]) and number(r["price"])]
        complete_selected = len(valid) == len(records)
        recorded = total_or_none(records, "cost")
        kwh = total_or_none(records, "kwh")
        dynamic = sum(r["kwh"] * r["price"] for r in valid) if complete_selected else None
        baseline = kwh * average if kwh is not None and average is not None else None
        custom = kwh * rates[m] if kwh is not None and m in rates else None
        entry = {"month": m, "hours": len(records), "expected_hours": expected,
                 "consumption_complete": len(records) == expected and kwh is not None,
                 "price_month_complete": complete_prices, "kwh": kwh, "api_cost": recorded,
                 "hourly_cost": dynamic, "monthly_mean_rate": average,
                 "monthly_mean_cost": baseline, "custom_rate": rates.get(m), "custom_cost": custom,
                 "hourly_minus_mean": dynamic - baseline if dynamic is not None and baseline is not None else None,
                 "applied_price_count": len({r["applied"] for r in records if number(r["applied"])})}
        months.append(entry)
        if baseline is not None and dynamic is not None:
            comparison_rows.extend(valid)
    daily = []
    byday = defaultdict(list)
    for r in selected:
        byday[r["day"]].append(r)
    for day, records in sorted(byday.items()):
        daily.append({"day": day, "kwh": total_or_none(records, "kwh"),
                      "api_cost": total_or_none(records, "cost"),
                      "price": mean([r["price"] for r in records if number(r["price"])]) if any(number(r["price"]) for r in records) else None})
    profiles = []
    for weekend in (False, True):
        for hour in range(24):
            records = [r for r in selected if r["hour"] == hour and r["weekend"] == weekend]
            energy = [r["kwh"] for r in records if number(r["kwh"])]
            p = [r["price"] for r in records if number(r["price"])]
            profiles.append({"hour": hour, "weekend": weekend, "samples": len(energy),
                             "mean_kwh": mean(energy) if energy else None,
                             "median_kwh": median(energy) if energy else None,
                             "p10_kwh": quantile(energy, .1), "p90_kwh": quantile(energy, .9),
                             "mean_price": mean(p) if p else None})
    heatmap = []
    for m, records in sorted(groups.items()):
        for hour in range(24):
            v = [r["kwh"] for r in records if r["hour"] == hour and number(r["kwh"])]
            heatmap.append({"month": m, "hour": hour, "kwh": mean(v) if v else None, "samples": len(v)})
    valid = [r for r in selected if number(r["kwh"]) and number(r["price"])]
    diffs = [abs(r["price"]-r["applied"]) for r in valid if number(r["applied"])]
    comparison = [m for m in months if m["hourly_minus_mean"] is not None]
    top = sorted([r for r in selected if number(r["kwh"])], key=lambda r: r["kwh"], reverse=True)[:12]
    return {"years": years, "currency": next((r["currency"] for r in rows if r["currency"]), "EUR"),
            "timezone": zone_name, "coverage": {"first": rows[0]["day"] if rows else None,
            "last": rows[-1]["day"] if rows else None, "saved_hours": len(rows),
            "gap_hours": sum(max(0, round((b["utc"]-a["end"]).total_seconds()/3600)) for a,b in zip(rows, rows[1:]))},
            "summary": {"hours": len(selected), "known_consumption_hours": sum(number(r["kwh"]) for r in selected),
            "matched_price_hours": len(valid), "kwh": total_or_none(selected, "kwh"),
            "api_cost": total_or_none(selected, "cost"),
            "comparable_hours": len(comparison_rows),
            "hourly_cost": sum(m["hourly_cost"] for m in comparison) if comparison else None,
            "mean_cost": sum(m["monthly_mean_cost"] for m in comparison) if comparison else None,
            "hourly_minus_mean": sum(m["hourly_minus_mean"] for m in comparison) if comparison else None,
            "max_price_rounding_difference": max(diffs) if diffs else None},
            "monthly": months, "daily": daily, "profiles": profiles, "heatmap": heatmap,
            "peaks": [{"start": r["utc"].astimezone(zone).isoformat(), "kwh": r["kwh"], "price": r["price"]} for r in top]}
