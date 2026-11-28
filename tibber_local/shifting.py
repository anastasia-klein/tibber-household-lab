"""Constrained aggregate peak redistribution; not appliance-cycle identification."""
import math
from collections import defaultdict
from datetime import timedelta,timezone
from zoneinfo import ZoneInfo
from .analysis import normalize,quantile,number


def allocate(prices,supply,capacity,budget,delay_only=False):
    """Maximum saving transport with real-valued kWh and optional time ordering."""
    sources=[i for i,v in enumerate(supply) if v>1e-10]
    targets=[i for i,v in enumerate(capacity) if v>1e-10]
    source,gate=0,1;offset=2+len(sources);sink=offset+len(targets)
    graph=[[] for _ in range(sink+1)];links=[]
    def edge(a,b,cap,cost):
        forward=[b,len(graph[b]),cap,cost,cap]
        reverse=[a,len(graph[a]),0.,-cost,0.]
        graph[a].append(forward);graph[b].append(reverse)
        return forward
    edge(source,gate,budget,0)
    for si,i in enumerate(sources):
        edge(gate,2+si,supply[i],-prices[i])
        for tj,j in enumerate(targets):
            if i!=j and (not delay_only or j>i):
                e=edge(2+si,offset+tj,budget,0);links.append((i,j,e))
    for tj,j in enumerate(targets):edge(offset+tj,sink,capacity[j],prices[j])
    # Residual paths can reroute an earlier allocation when a deadline makes it suboptimal.
    for _ in range(1000):
        distances=[math.inf]*len(graph);previous=[None]*len(graph);distances[source]=0
        for _ in range(len(graph)-1):
            changed=False
            for a,edges in enumerate(graph):
                if not math.isfinite(distances[a]):continue
                for ei,e in enumerate(edges):
                    if e[2]>1e-10 and distances[a]+e[3]<distances[e[0]]-1e-12:
                        distances[e[0]]=distances[a]+e[3];previous[e[0]]=(a,ei);changed=True
            if not changed:break
        if not math.isfinite(distances[sink]) or distances[sink]>=-1e-12:break
        path=[];node=sink
        while node!=source:
            a,ei=previous[node];path.append((a,ei));node=a
            if len(path)>len(graph):raise ValueError('Unexpected residual cycle.')
        amount=min(graph[a][ei][2] for a,ei in path)
        for a,ei in path:
            e=graph[a][ei];e[2]-=amount;graph[e[0]][e[1]][2]+=amount
    else:raise ValueError('Peak redistribution did not converge.')
    return [(i,j,e[4]-e[2]) for i,j,e in links if e[4]-e[2]>1e-9]


def simulate_peak_shifting(consumption,prices,zone_name,start,end,daily_fraction,
                           allowed_target_hours=range(24),delay_only=False):
    if not 0<=daily_fraction<=1:raise ValueError('Daily fraction must be between zero and one.')
    zone=ZoneInfo(zone_name);start=start.astimezone(timezone.utc);end=end.astimezone(timezone.utc)
    if end<=start or any((t.astimezone(zone).hour,t.astimezone(zone).minute,t.astimezone(zone).second)!=(0,0,0) for t in (start,end)):
        raise ValueError('Choose a positive period bounded by local midnights.')
    records,_=normalize(consumption,prices)
    records=[r for r in records if start<=r['utc']<end]
    expected={start+timedelta(hours=i) for i in range(int((end-start).total_seconds()/3600))}
    if {r['utc'] for r in records}!=expected:raise ValueError('Every physical interval in the period is required.')
    if any(not number(r['kwh']) or not number(r['price']) or not number(r['cost']) for r in records):
        raise ValueError('Consumption, quote and recorded cost must all be populated.')
    days=defaultdict(list)
    for r in records:days[r['utc'].astimezone(zone).date()].append(r)
    daily=[]
    for date,rows in sorted(days.items()):
        q=[r['kwh'] for r in rows];p=[r['price'] for r in rows]
        floor=quantile(q,.25)
        peaks=set(sorted(range(len(q)),key=lambda i:(-q[i],i))[:3])
        supply=[max(0,(v-floor)*.5) if i in peaks else 0 for i,v in enumerate(q)]
        # Extra hourly load is at most 0.5 kWh, and cannot exceed the original daily peak.
        capacity=[min(.5,max(q)-v) if i not in peaks and rows[i]['utc'].astimezone(zone).hour in allowed_target_hours else 0 for i,v in enumerate(q)]
        moves=allocate(p,supply,capacity,sum(q)*daily_fraction,delay_only)
        shifted=q.copy();saving=0
        for i,j,energy in moves:
            shifted[i]-=energy;shifted[j]+=energy;saving+=energy*(p[i]-p[j])
        if abs(sum(q)-sum(shifted))>1e-8 or min(shifted)<-1e-8 or max(shifted)>max(q)+1e-8:
            raise ValueError('Energy conservation or hourly bounds failed.')
        daily.append({'date':date.isoformat(),'hours':len(q),'kwh':sum(q),
            'budget_kwh':sum(q)*daily_fraction,'shifted_kwh':sum(e for _,_,e in moves),
            'saving_eur':saving,'original_peak_kwh':max(q),'new_peak_kwh':max(shifted),
            'moves':[{'source_utc':rows[i]['utc'].isoformat(),'target_utc':rows[j]['utc'].isoformat(),'kwh':e} for i,j,e in moves]})
    base=sum(r['cost'] for r in records);saving=sum(d['saving_eur'] for d in daily)
    return {'daily_fraction_cap':daily_fraction,'target_local_hours':list(allowed_target_hours),'delay_only':delay_only,
        'hours':len(records),'kwh':sum(r['kwh'] for r in records),'days':len(daily),
        'baseline_recorded_cost':base,'saving_eur':saving,'shifted_cost_estimate':base-saving,
        'shifted_kwh':sum(d['shifted_kwh'] for d in daily),'daily':daily,
        'assumptions':['The three largest observed hourly loads are the source peaks for each local day.',
        'Only half the load above the daily 25th-percentile hourly level can be removed from those peaks.',
        'The background reserve is a modelling assumption, not identified inflexible device load.',
        'Added load is capped at 0.5 kWh per target hour and at the original daily maximum.',
        'Every local day retains exactly the same energy; no energy crosses a day or month boundary.',
        'A free-time run allows both advancement and delay; delay-only runs forbid earlier destinations.',
        'Energy is divisible; whole cycles, device readiness and appliance identity are not represented.',
        'All historical hourly prices are known to this optimization; changes use the same gross quote basis.',
        'This is a constrained theoretical potential, not verified achievable appliance savings.']}


def main():
    import argparse
    from datetime import datetime,date
    from . import storage
    parser=argparse.ArgumentParser(description='Private aggregate same-day peak shifting estimate')
    parser.add_argument('--start',required=True,help='Inclusive local date')
    parser.add_argument('--end',required=True,help='Exclusive local date')
    parser.add_argument('--daily-fraction',type=float,default=.1)
    parser.add_argument('--target-start-hour',type=int,default=0)
    parser.add_argument('--target-end-hour',type=int,default=24,help='Exclusive target-hour bound')
    parser.add_argument('--delay-only',action='store_true')
    args=parser.parse_args()
    if not 0<=args.target_start_hour<args.target_end_hour<=24:
        parser.error('Target hours must form a nonempty interval within 0-24.')
    conf=storage.config();zone=ZoneInfo(conf.get('timezone','Europe/Berlin'))
    start=datetime.combine(date.fromisoformat(args.start),datetime.min.time(),zone)
    end=datetime.combine(date.fromisoformat(args.end),datetime.min.time(),zone)
    with storage.connect() as db:
        consumption=storage.read_rows(db,'consumption');prices=storage.read_rows(db,'prices')
    result=simulate_peak_shifting(consumption,prices,zone.key,start,end,args.daily_fraction,
        range(args.target_start_hour,args.target_end_hour),args.delay_only)
    storage.private_json(storage.data_dir()/'peak_shifting.json',result)
    print('Private aggregate redistribution estimate saved. It does not identify feasible appliance cycles.')


if __name__=='__main__':main()
