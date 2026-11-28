import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from tibber_local.analysis import analyze, expected_hours, normalize, instant
from tibber_local import api
from unittest.mock import patch


def fixture(start, count, kwh=1):
    c, p = [], []
    for i in range(count):
        t = start + timedelta(hours=i)
        price = .1 if i % 2 == 0 else .9
        c.append({'from':t.isoformat(), 'to':(t+timedelta(hours=1)).isoformat(),
                  'consumption':kwh, 'consumptionUnit':'kWh','cost':kwh*price,
                  'unitPrice':price,'currency':'EUR'})
        p.append({'startsAt':t.isoformat(),'total':price,'currency':'EUR'})
    return c,p


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.start = datetime(2025, 1, 1, tzinfo=ZoneInfo('Europe/Berlin')).astimezone(timezone.utc)

    def test_monthly_scenario_uses_consumption_weights(self):
        c,p=fixture(self.start,744)
        for i,r in enumerate(c):
            r['consumption']=1 if i%2==0 else 3
            r['cost']=r['consumption']*r['unitPrice']
        result=analyze(c,p,'Europe/Berlin')
        self.assertAlmostEqual(result['summary']['hourly_cost'],372*(.1+2.7))
        self.assertAlmostEqual(result['summary']['mean_cost'],744)
        self.assertAlmostEqual(result['summary']['hourly_minus_mean'],297.6)

    def test_price_load_profiles_match_intervals_and_month_filter(self):
        start = instant('2025-01-31T12:00:00+01:00')
        c,p = fixture(start, 49)
        c[24]['consumption'] = None
        result = analyze(c,p,'Europe/Berlin',year='2025',month='02')
        noon = next(r for r in result['profiles'] if r['weekend'] and r['hour']==12)
        self.assertEqual(noon['samples'], 1)
        self.assertEqual(noon['matched_samples'], 1)
        self.assertEqual(noon['matched_mean_kwh'], 1)
        self.assertEqual(noon['matched_mean_price'], .1)
        self.assertTrue(all(r['matched_samples']==0 for r in result['profiles'] if not r['weekend']))
        missing = analyze(c,[], 'Europe/Berlin',year='2025',month='02')
        self.assertTrue(all(r['matched_mean_kwh'] is None and r['matched_mean_price'] is None for r in missing['profiles']))

    def test_dst_expected_hours(self):
        self.assertEqual(expected_hours('2025-03',ZoneInfo('Europe/Berlin')),743)
        self.assertEqual(expected_hours('2025-10',ZoneInfo('Europe/Berlin')),745)

    def test_autumn_repeated_hour_preserved(self):
        start=instant('2025-10-26T02:00:00+02:00')
        c,p=fixture(start,2)
        result=analyze(c,p,'Europe/Berlin')
        self.assertEqual(result['summary']['hours'],2)
        profile=next(r for r in result['profiles'] if r['weekend'] and r['hour']==2)
        self.assertEqual(profile['samples'],2)
        self.assertEqual(len({r['start'] for r in result['peaks']}),2)

    def test_partial_price_month_has_no_monthly_comparison(self):
        c,p=fixture(self.start,100)
        result=analyze(c,p,'Europe/Berlin')
        self.assertIsNone(result['summary']['mean_cost'])
        self.assertIsNone(result['summary']['hourly_minus_mean'])
        self.assertIsNotNone(result['monthly'][0]['hourly_cost'])

    def test_month_average_ignores_weekday_filter(self):
        c,p=fixture(self.start,744)
        all_days=analyze(c,p,'Europe/Berlin')
        weekdays=analyze(c,p,'Europe/Berlin',daytype='weekday')
        self.assertEqual(all_days['monthly'][0]['monthly_mean_rate'],weekdays['monthly'][0]['monthly_mean_rate'])
        self.assertLess(weekdays['summary']['hours'],744)

    def test_null_consumption_is_not_zero(self):
        c,p=fixture(self.start,744);c[3]['consumption']=None;c[3]['cost']=None
        r=analyze(c,p,'Europe/Berlin')
        self.assertIsNone(r['summary']['kwh'])
        self.assertIsNone(r['summary']['api_cost'])
        self.assertIsNone(r['summary']['hourly_minus_mean'])
        self.assertEqual(r['summary']['known_consumption_hours'],743)

    def test_missing_price_is_not_zero(self):
        c,p=fixture(self.start,744);p.pop(5)
        r=analyze(c,p,'Europe/Berlin')
        self.assertEqual(r['summary']['matched_price_hours'],743)
        self.assertIsNone(r['summary']['hourly_minus_mean'])

    def test_negative_prices_keep_their_sign(self):
        c,p=fixture(self.start,744)
        for r in p:r['total']=-.2
        result=analyze(c,p,'Europe/Berlin')
        self.assertAlmostEqual(result['summary']['hourly_cost'],-148.8)
        self.assertAlmostEqual(result['summary']['hourly_minus_mean'],0)

    def test_mixed_currency_rejected(self):
        c,p=fixture(self.start,2);p[0]['currency']='NOK'
        with self.assertRaises(ValueError):normalize(c,p)

    def test_subhourly_rejected(self):
        c,p=fixture(self.start,2);c[0]['to']=(self.start+timedelta(minutes=15)).isoformat()
        with self.assertRaises(ValueError):normalize(c,p)
        c,p=fixture(self.start,2);p[1]['startsAt']=(self.start+timedelta(minutes=15)).isoformat()
        with self.assertRaises(ValueError):normalize(c,p)

    def test_duplicate_and_naive_timestamp_rejected(self):
        c,p=fixture(self.start,2)
        with self.assertRaises(ValueError):normalize(c+c[:1],p)
        with self.assertRaises(ValueError):instant('2025-01-01T00:00:00')

    def test_zero_and_empty_history(self):
        c,p=fixture(self.start,744,kwh=0)
        self.assertEqual(analyze(c,p,'Europe/Berlin')['summary']['hourly_cost'],0)
        self.assertIsNone(analyze([],[],'Europe/Berlin')['summary']['kwh'])

    def test_custom_rate_separate_from_hypothetical_mean(self):
        c,p=fixture(self.start,744)
        r=analyze(c,p,'Europe/Berlin',rates={'2025-01':.3})
        self.assertAlmostEqual(r['monthly'][0]['custom_cost'],223.2)
        self.assertEqual(r['monthly'][0]['monthly_mean_rate'],.5)

    def test_gap_report(self):
        c,p=fixture(self.start,744);c.pop(4)
        r=analyze(c,p,'Europe/Berlin')
        self.assertEqual(r['coverage']['gap_hours'],1)
        self.assertFalse(r['monthly'][0]['consumption_complete'])

    def test_api_pagination_dedupes_overlap(self):
        c,_=fixture(self.start,3)
        def response(nodes,next_page,cursor):
            return {'viewer':{'home':{'consumption':{'nodes':nodes,'pageInfo':{'hasNextPage':next_page,'endCursor':cursor}}}}}
        with patch.object(api,'query',side_effect=[response(c[:2],True,'next'),response(c[1:],False,None)]):
            result=api.history('synthetic-token','synthetic-home','consumption',self.start,self.start+timedelta(hours=3))
        self.assertEqual(len(result),3)

    def test_api_repeated_cursor_stops(self):
        c,_=fixture(self.start,2)
        response={'viewer':{'home':{'consumption':{'nodes':c,'pageInfo':{'hasNextPage':True,'endCursor':'same'}}}}}
        with patch.object(api,'query',return_value=response):
            with self.assertRaisesRegex(ValueError,'repeated a cursor'):
                api.history('synthetic-token','synthetic-home','consumption',self.start,self.start+timedelta(days=3))

if __name__=='__main__':unittest.main()
