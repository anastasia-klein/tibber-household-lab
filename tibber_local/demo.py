"""Deterministic synthetic demo, unrelated to any actual household."""
import math
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from . import storage


def create_demo():
    zone = ZoneInfo("Europe/Berlin")
    start = datetime(2025, 1, 1, tzinfo=zone).astimezone(timezone.utc)
    end = datetime(2026, 1, 1, tzinfo=zone).astimezone(timezone.utc)
    consumption, prices = [], []
    i = 0
    while start < end:
        local = start.astimezone(zone)
        price = .24 + .09*math.cos((local.hour-19)*math.pi/12) + .04*math.cos(i/300)
        kwh = .12 + (.4 if local.hour in (7,18,19,20) else .02) + .03*(1+math.sin(i))
        consumption.append({"from": start.isoformat(), "to": (start+timedelta(hours=1)).isoformat(),
            "consumption": kwh, "consumptionUnit": "kWh", "unitPrice": price,
            "unitPriceVAT": None, "cost": kwh*price, "currency": "EUR"})
        prices.append({"startsAt": start.isoformat(), "total": price, "energy": None, "tax": None, "currency": "EUR"})
        start += timedelta(hours=1)
        i += 1
    with storage.connect() as db:
        storage.write_rows(db, "consumption", consumption)
        storage.write_rows(db, "prices", prices)
    storage.save_config({"demo": True, "timezone": "Europe/Berlin", "start": "2025-01-01", "refresh_hours": 0})
