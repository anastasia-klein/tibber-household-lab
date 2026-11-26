import unittest
from datetime import datetime,timedelta,timezone,date
from zoneinfo import ZoneInfo
from tibber_local.slp import compare_slp,quarter_weights,season_for,daytype_for,dynamization


def table(values=None):
    return {(s,d):list(values or [1]*96) for s in ('winter','summer','transition') for d in ('weekday','saturday','sunday')}


def january():
    start=datetime(2025,1,1,tzinfo=timezone.utc);c=[];p=[]
    for h in range(744):
        t=start+timedelta(hours=h);price=.1 if h%2==0 else .9;kwh=1 if h%2==0 else 3
        c.append({'from':t.isoformat(),'to':(t+timedelta(hours=1)).isoformat(),'consumption':kwh,'consumptionUnit':'kWh','cost':kwh*price,'unitPrice':price,'currency':'EUR'})
        p.append({'startsAt':t.isoformat(),'total':price,'currency':'EUR'})
    return start,c,p


class SLPTests(unittest.TestCase):
    def test_partial_consumption_uses_full_month_rate(self):
        start,c,p=january()
        result=compare_slp(c,p,table(),'UTC',start,start+timedelta(days=1),set())
        self.assertEqual(result['hours'],24)
        self.assertAlmostEqual(result['recorded_interval_cost'],33.6)
        self.assertAlmostEqual(result['slp_cost'],24)
        self.assertEqual(result['monthly'][0]['reference_price_quarters'],2976)
        self.assertFalse(result['account_profile_assignment_confirmed'])

    def test_native_quarter_prices_use_quarter_weights(self):
        start,c,p=january();qp=[]
        for i in range(2976):qp.append({'startsAt':(start+timedelta(minutes=15*i)).isoformat(),'total':[.1,.2,.3,.4][i%4],'currency':'EUR'})
        result=compare_slp(c,p,table([1,1,1,9]*24),'UTC',start,start+timedelta(days=1),set(),qp)
        self.assertAlmostEqual(result['monthly'][0]['slp_rate'],.35)
        self.assertAlmostEqual(result['slp_cost'],16.8)
        self.assertTrue(result['monthly'][0]['native_quarter_prices'])

    def test_missing_reference_price_outside_selected_day_is_rejected(self):
        start,c,p=january();p.pop()
        with self.assertRaisesRegex(ValueError,'complete calendar month'):
            compare_slp(c,p,table(),'UTC',start,start+timedelta(days=1),set())

    def test_partial_native_month_cannot_fall_back_silently(self):
        start,c,p=january()
        with self.assertRaisesRegex(ValueError,'complete calendar month'):
            compare_slp(c,p,table(),'UTC',start,start+timedelta(days=1),set(),[{'startsAt':start.isoformat(),'total':.1,'currency':'EUR'}])

    def test_dst_quarters_are_preserved(self):
        z=ZoneInfo('Europe/Berlin')
        spring=quarter_weights(datetime(2025,3,1,tzinfo=z),datetime(2025,4,1,tzinfo=z),table(),z.key,set())
        autumn=quarter_weights(datetime(2025,10,1,tzinfo=z),datetime(2025,11,1,tzinfo=z),table(),z.key,set())
        self.assertEqual(len(spring),2972);self.assertEqual(len(autumn),2980)
        repeats=[t for t in autumn if t.astimezone(z).date()==date(2025,10,26) and t.astimezone(z).hour==2]
        self.assertEqual(len(repeats),8)

    def test_calendar_and_dynamization(self):
        holiday=date(2025,1,6)
        self.assertEqual(daytype_for(holiday,{holiday}),'sunday')
        self.assertEqual(daytype_for(holiday,set()),'weekday')
        self.assertEqual(daytype_for(date(2025,12,24),set()),'saturday')
        self.assertEqual(season_for(date(2025,3,20)),'winter')
        self.assertEqual(season_for(date(2025,3,21)),'transition')
        self.assertEqual(season_for(date(2025,5,15)),'summer')
        self.assertEqual(dynamization(date(2025,12,31)),1.2572)
