import random
import unittest
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
from tibber_local.provenance import fit_shape,inspect_history


def row(t,value):
    return {'from':t.isoformat(),'to':(t+timedelta(hours=1)).isoformat(),'consumption':value}


class ProvenanceTests(unittest.TestCase):
    def test_scaling_is_separate_from_shape(self):
        result=fit_shape([2,4,8],[1,2,4])
        self.assertEqual(result['scale'],2)
        self.assertEqual(result['relative_rmse'],0)
        self.assertIsNone(fit_shape([0,0],[0,0]))
        self.assertGreater(fit_shape([1,8,2],[1,2,4])['relative_rmse'],.5)

    def test_mixed_day_boundary_is_a_candidate_not_certification(self):
        rng=random.Random(123);start=datetime(2025,1,1,tzinfo=timezone.utc)
        shape=[.1+.01*h+.3*(h in (7,19)) for h in range(24)]
        rows=[]
        for d in range(18):
            for h in range(24):
                value=.05+rng.random()**2*1.5 if d<5 or (d==5 and h<15) else shape[h]*(1+d*.01)
                rows.append(row(start+timedelta(days=d,hours=h),value))
        r=inspect_history(rows,'UTC')
        self.assertEqual(r['first_profile_like_full_day'],'2025-01-07')
        self.assertEqual(r['candidate_intraday_boundary']['local_start'],'2025-01-06T15:00:00+00:00')
        self.assertEqual(r['certified_measured_periods'],[])
        self.assertFalse(r['source_quality_flag_available'])
        self.assertFalse(any(d['profile_like'] for d in r['daily'] if d['date']<'2025-01-07'))

    def test_dst_hours_remain_physical_intervals(self):
        z=ZoneInfo('Europe/Berlin');start=datetime(2025,10,25,tzinfo=z).astimezone(timezone.utc)
        rows=[row(start+timedelta(hours=h),1) for h in range(49)]
        r=inspect_history(rows,'Europe/Berlin')
        self.assertEqual(r['hourly_rows'],49)
        self.assertEqual(r['complete_24_hour_days'],1)
        self.assertEqual(r['nonstandard_or_incomplete_days'],[{'date':'2025-10-26','physical_hours':25}])

    def test_zero_run_is_reported_without_imputation(self):
        start=datetime(2025,1,1,tzinfo=timezone.utc)
        rows=[row(start+timedelta(hours=h),0 if 19<=h<26 else 1) for h in range(48)]
        r=inspect_history(rows,'UTC')
        self.assertEqual(r['consecutive_zero_runs'],[{'local_start':'2025-01-01T19:00:00+00:00','local_end_exclusive':'2025-01-02T02:00:00+00:00','hours':7}])

    def test_duplicate_utc_keys_are_rejected(self):
        record=row(datetime(2025,1,1,tzinfo=timezone.utc),1)
        with self.assertRaises(ValueError):inspect_history([record,record],'UTC')
