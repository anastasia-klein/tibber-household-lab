"""Render private clock-hour consumption and quoted-price comparisons."""
from collections import defaultdict
from datetime import timedelta
from math import isfinite
from pathlib import Path
from statistics import mean
from zoneinfo import ZoneInfo
from .analysis import instant
from .patterns import describe_consumption


def render_price_profiles(consumption, prices, zone_name, start, end, output):
    """Use identical physical intervals for both unweighted clock-hour means."""
    summary = describe_consumption(consumption, zone_name, start, end)
    zone = ZoneInfo(zone_name)
    groups = defaultdict(list)
    for row in consumption:
        t = instant(row['from'])
        if not start <= t < end:
            continue
        price = prices.get(t)
        if price is None or not isfinite(price):
            raise ValueError('Every consumption interval requires a finite quoted total price.')
        local = t.astimezone(zone)
        groups[(local.weekday() >= 5, local.hour)].append((row['consumption'], price * 100))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 1, figsize=(13, 8), sharex=True, layout='constrained')
    fig.patch.set_facecolor('#f5f8fc')
    profiles = {}
    for weekend, ax in zip((False, True), axes):
        kind = 'weekend' if weekend else 'weekday'
        values = [groups[(weekend, h)] for h in range(24)]
        load = [mean(q for q, p in v) if v else float('nan') for v in values]
        price = [mean(p for q, p in v) if v else float('nan') for v in values]
        profiles[kind] = {'mean_kwh': load, 'mean_price_ct_kwh': price,
                          'observations': [len(v) for v in values]}
        right = ax.twinx()
        a, = ax.plot(range(24), load, color='#397de0', marker='o', ms=4, lw=2, label='Mean consumption')
        b, = right.plot(range(24), price, color='#dc8b27', marker='o', ms=4, lw=2, label='Mean quoted total price')
        ax.set_ylabel('Consumption (kWh per hour)', color='#397de0')
        right.set_ylabel('Quoted total price (ct/kWh)', color='#b46c13')
        ax.tick_params(axis='y', colors='#397de0')
        right.tick_params(axis='y', colors='#b46c13')
        ax.set_title(f"{kind.capitalize()}s - {summary['daytypes'][kind]['days']} days", loc='left', weight='bold', color='#20334c')
        ax.set_facecolor('white'); ax.grid(axis='y', color='#e4eaf3'); ax.set_axisbelow(True)
        ax.spines['top'].set_visible(False); right.spines['top'].set_visible(False)
        ax.set_xticks(range(24), [f'{h:02}' for h in range(24)])
        ax.tick_params(axis='x', labelbottom=True); ax.set_xlim(-.5, 23.5)
        ax.legend(handles=[a, b], loc='upper left', frameon=False, ncol=2, fontsize=10)
    load_max = max(v for p in profiles.values() for v in p['mean_kwh'] if isfinite(v))
    for ax in axes:
        ax.set_ylim(0, load_max*1.18 if load_max else 1)
    all_prices = [v for p in profiles.values() for v in p['mean_price_ct_kwh'] if isfinite(v)]
    low, high = min(all_prices), max(all_prices)
    margin = max((high-low)*.2, 1)
    for ax in fig.axes[2:]:
        ax.set_ylim(min(0, low-margin), high+margin)
    axes[1].set_xlabel(f'Local clock hour - {zone_name}')
    last = end.astimezone(zone).date()-timedelta(days=1)
    fig.suptitle(f"Consumption and price by clock hour, {start.astimezone(zone):%d %b} - {last:%d %b %Y}", fontsize=16, weight='bold', color='#20334c')
    fig.supxlabel('Arithmetic means over the same physical hours. Blue: left axis; orange: right axis.\nQuoted API total price, not cost divided by consumption or a verified invoice rate. Weekends: Saturday and Sunday.', fontsize=10, color='#647690')
    output = Path(output); output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fig.savefig(output, dpi=160); output.chmod(0o600); plt.close(fig)
    return profiles
