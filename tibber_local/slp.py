"""Explicit H0 counterfactual with native UTC intervals and full-month pricing."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from .analysis import instant, month_bounds, normalize, number

SOURCE_URL='https://www.bdew.de/media/documents/Profile.zip'
METHOD_URL='https://www.bdew.de/media/documents/2000131_Anwendung-repraesentativen_Lastprofile-Step-by-step.pdf'


def read_h0_workbook(path):
    import xlrd
    book=xlrd.open_workbook(str(path))
    name='Profil' if 'Profil' in book.sheet_names() else 'H0'
    sheet=book.sheet_by_name(name)
    table={}
    for season_index,season in enumerate(('winter','summer','transition')):
        for day_index,daytype in enumerate(('saturday','sunday','weekday')):
            column=1+season_index*3+day_index
            values=[sheet.cell_value(3+i,column) for i in range(96)]
            if any(not number(v) or v<=0 for v in values):
                raise ValueError('Expected 96 positive numeric H0 profile values per day type.')
            table[(season,daytype)]=values
    return table


def season_for(day):
    md=(day.month,day.day)
    if md<=(3,20) or md>=(11,1):return 'winter'
    if (5,15)<=md<=(9,14):return 'summer'
    return 'transition'


def daytype_for(day,holidays):
    if day in holidays or day.weekday()==6:return 'sunday'
    if day.weekday()==5 or (day.month,day.day) in ((12,24),(12,31)):return 'saturday'
    return 'weekday'


def dynamization(day,round_factor=True):
    t=day.timetuple().tm_yday
    factor=-3.92e-10*t**4+3.2e-7*t**3-7.02e-5*t**2+2.1e-3*t+1.24
    return round(factor,4) if round_factor else factor


def quarter_weights(start,end,table,zone_name,holidays,round_factor=True):
    zone=ZoneInfo(zone_name)
    t=start.astimezone(timezone.utc);end=end.astimezone(timezone.utc)
    weights={}
    while t<end:
        local=t.astimezone(zone);day=local.date()
        index=local.hour*4+local.minute//15
        watts=table[(season_for(day),daytype_for(day,holidays))][index]
        weights[t]=watts*dynamization(day,round_factor)*.25/1000
        t+=timedelta(minutes=15)
    return weights


def compare_slp(consumption,prices,table,zone_name,start,end,holidays,quarter_prices=None,round_factor=True):
    zone=ZoneInfo(zone_name)
    start=start.astimezone(timezone.utc);end=end.astimezone(timezone.utc)
    rows,price_map=normalize(consumption,prices)
    selected=[r for r in rows if start<=r['utc']<end]
    expected=int((end-start).total_seconds()/3600)
    if len(selected)!=expected or {r['utc'] for r in selected}!={start+timedelta(hours=i) for i in range(expected)}:
        raise ValueError('Comparison needs every physical hour in the requested period.')
    if any(not number(r['kwh']) or not number(r['cost']) or not number(r['price']) for r in selected):
        raise ValueError('Comparison needs populated consumption, recorded cost and hourly prices.')
    native={instant(r['startsAt']):r for r in (quarter_prices or [])}
    native_months={t.astimezone(zone).strftime('%Y-%m') for t in native}
    groups=defaultdict(list)
    for r in selected:groups[r['utc'].astimezone(zone).strftime('%Y-%m')].append(r)
    monthly=[]
    for month,records in sorted(groups.items()):
        a,b=month_bounds(month,zone)
        weights=quarter_weights(a,b,table,zone_name,holidays,round_factor)
        weighted_total=0
        for t,w in weights.items():
            if month in native_months:
                p=native.get(t)
            else:
                p=price_map.get(t.replace(minute=0,second=0,microsecond=0))
            if not p or not number(p.get('total')):
                raise ValueError('A complete calendar month of prices is required for SLP pricing.')
            if p.get('currency') != records[0]['currency']:
                raise ValueError('SLP and consumption currencies differ.')
            weighted_total+=w*p['total']
        rate=weighted_total/sum(weights.values())
        kwh=sum(r['kwh'] for r in records)
        actual=sum(r['cost'] for r in records)
        quote=sum(r['kwh']*r['price'] for r in records)
        monthly.append({'month':month,'consumption_hours':len(records),'kwh':kwh,
            'recorded_interval_cost':actual,'hourly_quote_cost':quote,'slp_rate':rate,
            'slp_cost':kwh*rate,'interval_minus_slp':actual-kwh*rate,
            'reference_price_quarters':len(weights),'native_quarter_prices':month in native_months})
    actual=sum(m['recorded_interval_cost'] for m in monthly);slp=sum(m['slp_cost'] for m in monthly)
    return {'start_inclusive_utc':start.isoformat(),'end_exclusive_utc':end.isoformat(),
            'profile':'BDEW H0 1999, dynamized','account_profile_assignment_confirmed':False,
            'timezone':zone_name,'holiday_dates':sorted(d.isoformat() for d in holidays),
            'hours':len(selected),'kwh':sum(m['kwh'] for m in monthly),
            'recorded_interval_cost':actual,'slp_cost':slp,'interval_minus_slp':actual-slp,
            'interval_saving_percent_of_slp':(slp-actual)/slp*100 if slp else None,
            'monthly':monthly,'fixed_charges':'Assumed identical and excluded from both alternatives.',
            'limitations':['This is an H0 counterfactual, not an independently verified historical invoice.',
            'Subscription total prices supply the same variable-charge basis in both alternatives.',
            'Native quarter-hour prices can price the SLP baseline; measured sub-hourly consumption is not supplied here.',
            'Recorded consumption cost is the interval-tariff reference; hourly quote products are retained as a separate check.']}


def main():
    import argparse,json
    from datetime import date
    from . import storage
    parser=argparse.ArgumentParser(description='Compare recorded interval cost with an explicit dynamized H0 monthly counterfactual')
    parser.add_argument('--profile-xls',required=True,help='Official BDEW H0 workbook downloaded from Profile.zip')
    parser.add_argument('--holidays-json',required=True,help='JSON list of ISO holiday dates for the applicable region and years')
    parser.add_argument('--start',required=True,help='Inclusive local date, YYYY-MM-DD')
    parser.add_argument('--end',required=True,help='Exclusive local date, YYYY-MM-DD')
    parser.add_argument('--quarter-prices-json',help='Private native quarter-hour subscription price nodes, where applicable')
    parser.add_argument('--allow-hourly-price-approximation',action='store_true',help='Explicitly allow hourly SLP price approximation after the DE quarter-hour change')
    args=parser.parse_args()
    conf=storage.config();zone=ZoneInfo(conf.get('timezone','Europe/Berlin'))
    start=datetime.combine(date.fromisoformat(args.start),datetime.min.time(),zone)
    end=datetime.combine(date.fromisoformat(args.end),datetime.min.time(),zone)
    if end<=start:parser.error('End must be after start.')
    holidays={date.fromisoformat(d) for d in json.loads(open(args.holidays_json,encoding='utf-8').read())}
    quarters=json.loads(open(args.quarter_prices_json,encoding='utf-8').read()) if args.quarter_prices_json else []
    # For German market periods after the product change, require native prices by default.
    if end>datetime(2025,10,1,tzinfo=zone) and not args.allow_hourly_price_approximation:
        month=datetime(start.year,start.month,1,tzinfo=zone)
        native_months={instant(r['startsAt']).astimezone(zone).strftime('%Y-%m') for r in quarters}
        while month<end:
            if month>=datetime(2025,10,1,tzinfo=zone) and month.strftime('%Y-%m') not in native_months:
                parser.error('Supply native quarter-hour prices for every affected month, or explicitly allow hourly approximation.')
            month=datetime(month.year+(month.month==12),1 if month.month==12 else month.month+1,1,tzinfo=zone)
    with storage.connect() as db:
        consumption=storage.read_rows(db,'consumption');prices=storage.read_rows(db,'prices')
    result=compare_slp(consumption,prices,read_h0_workbook(args.profile_xls),zone.key,start,end,holidays,quarters)
    storage.private_json(storage.data_dir()/'slp_comparison.json',result)
    print('Private H0 counterfactual saved. It does not certify the assigned account profile or an alternative tariff quote.')


if __name__=='__main__':main()
