import unittest
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
from tibber_local.shifting import allocate,simulate_peak_shifting


class ShiftingTests(unittest.TestCase):
    def test_residual_rerouting_respects_time_order(self):
        prices=[.5,.3,.4,.1]
        moves=allocate(prices,[1,0,1,0],[0,1,0,1],2,True)
        self.assertAlmostEqual(sum(e*(prices[i]-prices[j]) for i,j,e in moves),.5)
        self.assertTrue(all(j>i for i,j,e in moves))
        flow={(i,j):e for i,j,e in moves}
        self.assertAlmostEqual(flow[(0,1)],1);self.assertAlmostEqual(flow[(2,3)],1)

    def test_negative_prices_and_fractional_budget(self):
        p=[.5,.4,-.2,-.4]
        moves=allocate(p,[1,1,0,0],[0,0,1,1],1.5)
        self.assertAlmostEqual(sum(e for _,_,e in moves),1.5)
        self.assertAlmostEqual(sum(e*(p[i]-p[j]) for i,j,e in moves),1.2)

    def test_never_moves_when_price_would_increase(self):
        self.assertEqual(allocate([.1,.5],[1,0],[0,1],1),[])
        self.assertEqual(allocate([.1,.1],[1,0],[0,1],1),[])
        self.assertEqual(allocate([.5,.1],[1,0],[0,1],0),[])

    def test_daily_volume_conservation_and_peak_limits(self):
        start=datetime(2025,1,1,tzinfo=timezone.utc);c=[];p=[]
        for h in range(48):
            t=start+timedelta(hours=h);q=2 if h%24 in (18,19,20) else .1;price=.5 if q==2 else .1
            c.append({'from':t.isoformat(),'to':(t+timedelta(hours=1)).isoformat(),'consumption':q,'consumptionUnit':'kWh','cost':q*price,'unitPrice':price,'currency':'EUR'})
            p.append({'startsAt':t.isoformat(),'total':price,'currency':'EUR'})
        result=simulate_peak_shifting(c,p,'UTC',start,start+timedelta(days=2),.1)
        for d in result['daily']:
            self.assertLessEqual(d['shifted_kwh'],d['budget_kwh']+1e-9)
            self.assertLessEqual(d['new_peak_kwh'],d['original_peak_kwh']+1e-9)
            self.assertTrue(all(m['source_utc'][:10]==m['target_utc'][:10] for m in d['moves']))
        self.assertGreater(result['saving_eur'],0)
        self.assertAlmostEqual(result['shifted_cost_estimate'],result['baseline_recorded_cost']-result['saving_eur'])

    def test_dst_day_is_23_physical_hours(self):
        z=ZoneInfo('Europe/Berlin');start=datetime(2025,3,30,tzinfo=z);end=datetime(2025,3,31,tzinfo=z)
        t=start.astimezone(timezone.utc);c=[];p=[]
        while t<end:
            c.append({'from':t.isoformat(),'to':(t+timedelta(hours=1)).isoformat(),'consumption':1,'consumptionUnit':'kWh','cost':.3,'unitPrice':.3,'currency':'EUR'})
            p.append({'startsAt':t.isoformat(),'total':.3,'currency':'EUR'});t+=timedelta(hours=1)
        result=simulate_peak_shifting(c,p,z.key,start,end,.1)
        self.assertEqual(result['hours'],23);self.assertEqual(result['daily'][0]['hours'],23)
        self.assertEqual(result['saving_eur'],0)
