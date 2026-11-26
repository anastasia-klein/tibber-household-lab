"""Detect repeated load shapes as evidence, never as certified meter provenance."""
import argparse
import math
from collections import defaultdict
from datetime import timedelta
from pathlib import Path
from statistics import mean, median
from zoneinfo import ZoneInfo
from .analysis import instant
from . import storage


def fit_shape(actual, reference):
    """Fit one positive scale; return error relative to mean observed load."""
    if len(actual) != len(reference) or not actual or min(actual) < 0 or min(reference) < 0:
        return None
    denominator = sum(x*x for x in reference)
    level = mean(actual)
    if denominator <= 0 or level <= 0:
        return None
    scale = sum(a*b for a,b in zip(actual, reference)) / denominator
    errors = [a-scale*b for a,b in zip(actual, reference)]
    return {"scale": scale, "relative_rmse": math.sqrt(mean([e*e for e in errors]))/level,
            "max_absolute_error_kwh": max(abs(e) for e in errors)}


def inspect_history(rows, zone_name, threshold=.005):
    zone = ZoneInfo(zone_name)
    days = defaultdict(list)
    seen = set()
    for row in sorted(rows, key=lambda r: instant(r['from'])):
        t = instant(row['from'])
        if t in seen:
            raise ValueError('Duplicate UTC interval in provenance input.')
        seen.add(t)
        if (instant(row['to'])-t).total_seconds()!=3600:
            raise ValueError('Provenance audit expects hourly intervals.')
        local = t.astimezone(zone)
        days[local.date()].append({"utc":t,"local":local,"kwh":row.get('consumption')})
    # DST days are preserved in source and reported separately, never collapsed.
    complete = {d:[r['kwh'] for r in records] for d,records in days.items()
                if len(records)==24 and [r['local'].hour for r in records]==list(range(24))
                and all(isinstance(r['kwh'],(int,float)) and math.isfinite(r['kwh']) for r in records)}
    daily = []
    for day, actual in complete.items():
        matches=[]
        for other,reference in complete.items():
            if day==other:
                continue
            fit=fit_shape(actual,reference)
            if fit:
                matches.append({"date":other.isoformat(), **fit})
        matches.sort(key=lambda r:r['relative_rmse'])
        count=sum(m['relative_rmse']<threshold for m in matches)
        daily.append({"date":day.isoformat(),"matching_days":count,
                      "profile_like":count>=3,"nearest_matches":matches[:3]})
    daily.sort(key=lambda r:r['date'])
    flags=[r for r in daily if r['profile_like']]
    boundary=None
    if flags:
        first=next(d for d in complete if d.isoformat()==flags[0]['date'])
        previous=first-timedelta(days=1)
        if previous in complete:
            actual=complete[previous]
            reference_days=[d for d in complete if first<=d<=first+timedelta(days=14)
                            and any(f['date']==d.isoformat() for f in flags)]
            candidates=[]
            for start_hour in range(19):
                for refday in reference_days:
                    reference=complete[refday]
                    fitted=fit_shape(actual[start_hour:],reference[start_hour:])
                    if fitted and fitted['relative_rmse']<threshold and fitted['max_absolute_error_kwh']<=.0015:
                        prefix=fit_shape(actual[:start_hour],reference[:start_hour])
                        if start_hour and prefix and prefix['relative_rmse']>threshold*10:
                            candidates.append({"local_start":days[previous][start_hour]['local'].isoformat(),
                                "utc_start":days[previous][start_hour]['utc'].isoformat(),"start_hour":start_hour,
                                "reference_date":refday.isoformat(),"matching_suffix_hours":24-start_hour,
                                "prefix_relative_rmse":prefix['relative_rmse'],**fitted})
            if candidates:
                boundary=min(candidates,key=lambda c:(c['start_hour'],c['relative_rmse']))
    lag_monthly=defaultdict(list)
    for d,values in complete.items():
        prior=complete.get(d-timedelta(days=7))
        if prior:
            fit=fit_shape(values,prior)
            if fit:lag_monthly[d.strftime('%Y-%m')].append(fit['relative_rmse'])
    ordered=[r for records in days.values() for r in records]
    ordered.sort(key=lambda r:r['utc'])
    zero_runs=[];run=[]
    for r in ordered+[None]:
        if r and r['kwh']==0 and (not run or r['utc']-run[-1]['utc']==timedelta(hours=1)):
            run.append(r)
        else:
            if len(run)>=3:
                zero_runs.append({"local_start":run[0]['local'].isoformat(),
                    "local_end_exclusive":(run[-1]['utc']+timedelta(hours=1)).astimezone(zone).isoformat(),"hours":len(run)})
            run=[r] if r and r['kwh']==0 else []
    return {"timezone":zone_name,"hourly_rows":len(rows),"first_local_date":min(days).isoformat() if days else None,
        "last_local_date":max(days).isoformat() if days else None,
        "method":"One-scale daily shape matching; 3 other dates below 0.5% relative RMSE; a diagnostic, not a supplier quality flag.",
        "source_quality_flag_available":False,"certified_measured_periods":[],
        "first_profile_like_full_day":flags[0]['date'] if flags else None,"candidate_intraday_boundary":boundary,
        "complete_24_hour_days":len(complete),"profile_like_full_days":len(flags),
        "daily":daily,"nonstandard_or_incomplete_days":[{"date":d.isoformat(),"physical_hours":len(v)} for d,v in sorted(days.items()) if d not in complete],
        "weekly_shape_error_by_month":[{"month":m,"median_relative_rmse":median(v),"pairs":len(v)} for m,v in sorted(lag_monthly.items())],
        "consecutive_zero_runs":zero_runs,
        "limitations":["Irregular data is consistent with measurements but is not proof of measured provenance.",
        "Repeated shapes strongly suggest allocation or estimation but do not identify an official SLP code.",
        "The first profile-like hour does not establish a tariff or settlement-method activation date.",
        "Native sub-hourly timing and isolated estimated intervals require supplier or meter evidence.",
        "DST days retain physical UTC intervals and are excluded from 24-element shape fitting."]}


def main():
    parser=argparse.ArgumentParser(description='Private diagnostic of repeated hourly consumption shapes')
    parser.parse_args()
    conf=storage.config()
    with storage.connect() as db:rows=storage.read_rows(db,'consumption')
    report=inspect_history(rows,conf.get('timezone','Europe/Berlin'))
    storage.private_json(storage.data_dir()/'provenance_audit.json',report)
    print('Private provenance audit saved outside the repository. No period is certified as measured by this diagnostic.')


if __name__=='__main__':main()
