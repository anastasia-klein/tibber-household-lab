import unittest
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
from tibber_local.patterns import describe_consumption,monthly_shift_summary


def records(start,end,fn=lambda t:1):
    rows=[];t=start.astimezone(timezone.utc)
    while t<end:
        q=fn(t);rows.append({'from':t.isoformat(),'to':(t+timedelta(hours=1)).isoformat(),'consumption':q,'consumptionUnit':'kWh','cost':q*.2});t+=timedelta(hours=1)
    return rows


class PatternTests(unittest.TestCase):
    def test_tied_peaks_split_one_vote_per_day(self):
        start=datetime(2025,1,1,tzinfo=timezone.utc);end=start+timedelta(days=1)
        r=describe_consumption(records(start,end,lambda t:2 if t.hour in (13,20) else 1),'UTC',start,end)
        p=r['profiles']['all']
        self.assertEqual(p[13]['daily_peak_share'],.5);self.assertEqual(p[20]['daily_peak_share'],.5)
        self.assertAlmostEqual(sum(x['daily_peak_share'] for x in p),1)
        self.assertEqual(r['tied_daily_maximum_days'],1)

    def test_dst_changes_exposure_not_identity(self):
        z=ZoneInfo('Europe/Berlin');start=datetime(2025,3,30,tzinfo=z);end=datetime(2025,3,31,tzinfo=z)
        r=describe_consumption(records(start,end),z.key,start,end)
        self.assertEqual(r['hours'],23);self.assertEqual(r['kwh'],23)
        self.assertEqual(r['profiles']['all'][2]['observations'],0)
        self.assertIsNone(r['monthly'][0]['mean_hourly_kwh'][2])
        self.assertAlmostEqual(sum(x['daily_peak_share'] for x in r['profiles']['all']),1)

    def test_partial_month_uses_covered_days(self):
        start=datetime(2025,1,31,tzinfo=timezone.utc);end=datetime(2025,2,3,tzinfo=timezone.utc)
        r=describe_consumption(records(start,end),'UTC',start,end)
        self.assertEqual([m['days'] for m in r['monthly']],[1,2])
        self.assertEqual([m['mean_daily_kwh'] for m in r['monthly']],[24,24])
        self.assertEqual(r['seasons'][0]['days'],3)

    def test_missing_hour_not_replaced_by_zero(self):
        start=datetime(2025,1,1,tzinfo=timezone.utc);end=start+timedelta(days=1)
        rows=records(start,end);rows.pop(5)
        with self.assertRaisesRegex(ValueError,'Every physical hour'):describe_consumption(rows,'UTC',start,end)

    def test_scenario_months_reconcile_and_reject_wrong_period(self):
        start=datetime(2025,1,31,tzinfo=timezone.utc);end=datetime(2025,2,2,tzinfo=timezone.utc)
        r=describe_consumption(records(start,end),'UTC',start,end)
        scenario={'hours':48,'kwh':48,'saving_eur':3,'daily':[{'date':'2025-01-31','shifted_kwh':2,'saving_eur':1},{'date':'2025-02-01','shifted_kwh':3,'saving_eur':2}]}
        out=monthly_shift_summary(r,[scenario])[0]['monthly']
        self.assertEqual([m['saving_eur'] for m in out],[1,2])
        self.assertAlmostEqual(sum(m['shifted_cost'] for m in out),48*.2-3)
        scenario['daily'][0]['date']='2025-01-30'
        with self.assertRaisesRegex(ValueError,'dates do not match'):monthly_shift_summary(r,[scenario])
        scenario['daily'][0]['date']='2025-01-31';scenario['baseline_recorded_cost']=999
        with self.assertRaisesRegex(ValueError,'different recorded-cost baseline'):monthly_shift_summary(r,[scenario])
