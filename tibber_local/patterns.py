"""Descriptive household patterns with explicit time and peak denominators."""
from collections import defaultdict,Counter
from datetime import timedelta,timezone
from statistics import mean,median
from zoneinfo import ZoneInfo
from .analysis import instant,number,quantile


def describe_consumption(consumption,zone_name,start,end):
    zone=ZoneInfo(zone_name);start=start.astimezone(timezone.utc);end=end.astimezone(timezone.utc)
    if end<=start or any((t.astimezone(zone).hour,t.astimezone(zone).minute,t.astimezone(zone).second)!=(0,0,0) for t in (start,end)):
        raise ValueError('Choose a positive period bounded by local midnights.')
    rows=[];seen=set()
    for source in consumption:
        t=instant(source['from'])
        if not start<=t<end:continue
        if t in seen:raise ValueError('Duplicate UTC observation.')
        seen.add(t)
        if (instant(source['to'])-t).total_seconds()!=3600:raise ValueError('Hourly observations are required.')
        if not number(source.get('consumption')) or source['consumption']<0:raise ValueError('Missing or invalid consumption.')
        if source.get('consumptionUnit') not in (None,'kWh'):raise ValueError('Expected kWh consumption.')
        local=t.astimezone(zone)
        rows.append({'utc':t,'local':local,'date':local.date(),'hour':local.hour,
                     'kwh':source['consumption'],'cost':source.get('cost'),'weekend':local.weekday()>=5})
    rows.sort(key=lambda r:r['utc'])
    expected={start+timedelta(hours=i) for i in range(int((end-start).total_seconds()/3600))}
    if seen!=expected:raise ValueError('Every physical hour in the requested period is required.')
    days=defaultdict(list)
    for r in rows:days[r['date']].append(r)
    threshold=quantile([r['kwh'] for r in rows],.95)
    peaks=defaultdict(float);monthly_peaks=defaultdict(lambda:defaultdict(float));ties=0
    for day,observations in days.items():
        maximum=max(r['kwh'] for r in observations)
        maxima=[r for r in observations if r['kwh']==maximum]
        ties+=len(maxima)>1
        for r in maxima:
            vote=1/len(maxima);peaks[r['hour']]+=vote;monthly_peaks[day.strftime('%Y-%m')][r['hour']]+=vote
    monthly=[]
    for month in sorted({d.strftime('%Y-%m') for d in days}):
        dd={d:v for d,v in days.items() if d.strftime('%Y-%m')==month}
        values=[r for v in dd.values() for r in v];totals=[sum(r['kwh'] for r in v) for v in dd.values()]
        costs=[r['cost'] for r in values]
        monthly.append({'month':month,'days':len(dd),'hours':len(values),'kwh':sum(totals),
            'mean_daily_kwh':mean(totals),'median_daily_kwh':median(totals),
            'api_cost':sum(costs) if all(number(c) for c in costs) else None,
            'daily_peak_hour_share':[monthly_peaks[month][h]/len(dd) for h in range(24)],
            'mean_hourly_kwh':[mean([r['kwh'] for r in values if r['hour']==h]) if any(r['hour']==h for r in values) else None for h in range(24)]})
    profiles={};daytypes={}
    for kind in ('all','weekday','weekend'):
        selected=[r for r in rows if kind=='all' or r['weekend']==(kind=='weekend')]
        selected_days={d:v for d,v in days.items() if kind=='all' or (d.weekday()>=5)==(kind=='weekend')}
        votes=defaultdict(float)
        for observations in selected_days.values():
            maximum=max(r['kwh'] for r in observations);maxima=[r for r in observations if r['kwh']==maximum]
            for r in maxima:votes[r['hour']]+=1/len(maxima)
        profiles[kind]=[]
        for h in range(24):
            observations=[r for r in selected if r['hour']==h];v=[r['kwh'] for r in observations]
            profiles[kind].append({'hour':h,'observations':len(v),'mean_kwh':mean(v) if v else None,
                'median_kwh':median(v) if v else None,'p10_kwh':quantile(v,.1),'p90_kwh':quantile(v,.9),
                'daily_peak_share':votes[h]/len(selected_days) if selected_days else None,
                'high_load_hours':sum(x>=threshold for x in v),
                'high_load_probability':sum(x>=threshold for x in v)/len(v) if v else None})
        totals=[sum(r['kwh'] for r in v) for v in selected_days.values()]
        daytypes[kind]={'days':len(totals),'mean_daily_kwh':mean(totals) if totals else None,'median_daily_kwh':median(totals) if totals else None}
    seasons=[]
    for name,months in [('winter',(12,1,2)),('spring',(3,4,5)),('summer',(6,7,8)),('autumn',(9,10,11))]:
        selected={d:v for d,v in days.items() if d.month in months};totals=[sum(r['kwh'] for r in v) for v in selected.values()]
        if totals:seasons.append({'season':name,'days':len(totals),'observed_months':sorted({d.strftime('%Y-%m') for d in selected}),
                                 'mean_daily_kwh':mean(totals),'median_daily_kwh':median(totals)})
    return {'timezone':zone_name,'start_inclusive_utc':start.isoformat(),'end_exclusive_utc':end.isoformat(),
        'hours':len(rows),'days':len(days),'local_dates':sorted(d.isoformat() for d in days),'kwh':sum(r['kwh'] for r in rows),'monthly':monthly,
        'profiles':profiles,'daytypes':daytypes,'seasons':seasons,'high_load_threshold_kwh':threshold,
        'high_load_hours':sum(r['kwh']>=threshold for r in rows),'tied_daily_maximum_days':ties,
        'largest_hours':[{'local_start':r['local'].isoformat(),'kwh':r['kwh']} for r in sorted(rows,key=lambda r:-r['kwh'])[:10]],
        'definitions':{'hourly_load':'Energy in a physical one-hour interval, not instantaneous peak power.',
        'daily_peak_share':'Fraction of observed local days whose maximum hourly consumption occurs here; ties split one vote equally.',
        'high_load_probability':'Physical observations at this clock hour at or above the period-wide 95th-percentile hourly kWh threshold, divided by observed physical intervals at this clock hour.',
        'monthly_comparison':'Average kWh per covered local day; no extrapolation of partial months.',
        'seasonal_comparison':'Meteorological month groups; only observed days are used. Incomplete annual coverage does not establish a full-year seasonal effect.'}}


def monthly_shift_summary(patterns,scenarios):
    output=[]
    for index,scenario in enumerate(scenarios):
        dates=[d['date'] for d in scenario['daily']]
        if len(set(dates))!=len(dates) or set(dates)!=set(patterns['local_dates']):
            raise ValueError('Shift scenario dates do not match the consumption period.')
        if scenario['hours']!=patterns['hours'] or abs(scenario['kwh']-patterns['kwh'])>1e-6:
            raise ValueError('Shift scenario coverage or volume does not match.')
        if abs(sum(d['saving_eur'] for d in scenario['daily'])-scenario['saving_eur'])>1e-8:
            raise ValueError('Daily savings do not reconcile to the scenario total.')
        costs=[m['api_cost'] for m in patterns['monthly']]
        if 'baseline_recorded_cost' in scenario and all(number(c) for c in costs) and abs(scenario['baseline_recorded_cost']-sum(costs))>1e-6:
            raise ValueError('Shift scenario uses a different recorded-cost baseline.')
        months=[]
        for base in patterns['monthly']:
            rows=[d for d in scenario['daily'] if d['date'].startswith(base['month'])]
            energy=sum(d['shifted_kwh'] for d in rows);saving=sum(d['saving_eur'] for d in rows)
            months.append({'month':base['month'],'days':base['days'],'kwh':base['kwh'],
                'shifted_kwh':energy,'saving_eur':saving,'baseline_api_cost':base['api_cost'],
                'shifted_cost':base['api_cost']-saving if base['api_cost'] is not None else None,
                'saving_per_day':saving/base['days'],
                'saving_per_shifted_kwh':saving/energy if energy else None})
        output.append({'scenario':scenario.get('scenario',f'scenario_{index+1}'),'monthly':months})
    return output


def main():
    import argparse
    from datetime import datetime,date
    from . import storage
    parser=argparse.ArgumentParser(description='Private descriptive hourly consumption research')
    parser.add_argument('--start',required=True);parser.add_argument('--end',required=True,help='Exclusive local date')
    parser.add_argument('--shifting-json',help='Optional private single scenario or scenarios collection')
    args=parser.parse_args();conf=storage.config();zone=ZoneInfo(conf.get('timezone','Europe/Berlin'))
    start=datetime.combine(date.fromisoformat(args.start),datetime.min.time(),zone)
    end=datetime.combine(date.fromisoformat(args.end),datetime.min.time(),zone)
    with storage.connect() as db:consumption=storage.read_rows(db,'consumption')
    result=describe_consumption(consumption,zone.key,start,end)
    if args.shifting_json:
        import json
        from pathlib import Path
        data=json.loads(Path(args.shifting_json).read_text())
        result['shifting_monthly']=monthly_shift_summary(result,data.get('scenarios',[data]))
    storage.private_json(storage.data_dir()/'consumption_patterns.json',result)
    print('Private consumption pattern report saved outside the repository.')


if __name__=='__main__':main()
