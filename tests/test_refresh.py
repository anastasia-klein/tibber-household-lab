import json
import os
import tempfile
import unittest
from unittest.mock import patch
from tibber_local import storage
from tibber_local.__main__ import refresh, STATE


class RefreshTests(unittest.TestCase):
    def test_price_failure_leaves_consumption_transaction_unchanged(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,{'TIBBER_LOCAL_DATA_DIR':folder}):
            storage.save_config({'home_id':'synthetic-home','timezone':'Europe/Berlin','start':'2025-01-01'})
            row={'from':'2025-01-01T00:00:00+01:00','to':'2025-01-01T01:00:00+01:00',
                 'consumption':1,'consumptionUnit':'kWh','cost':.2,'unitPrice':.2,'currency':'EUR'}
            with storage.connect() as db:storage.write_rows(db,'consumption',[row])
            revision={**row,'consumption':2,'cost':.4}
            with patch('tibber_local.storage.token',return_value='synthetic-token'), patch('tibber_local.api.history',side_effect=[[revision],ValueError('Synthetic price failure')]):
                refresh(full=True)
            with storage.connect() as db:saved=storage.read_rows(db,'consumption')
            self.assertEqual(saved,[row])
            self.assertEqual(STATE['error'],'Synthetic price failure')
            self.assertNotIn('last_refresh',storage.config())

    def test_storage_upsert_preserves_utc_identity(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,{'TIBBER_LOCAL_DATA_DIR':folder}):
            first={'from':'2025-10-26T02:00:00+02:00','consumption':1}
            second={'from':'2025-10-26T02:00:00+01:00','consumption':2}
            revised={'from':'2025-10-26T00:00:00Z','consumption':3}
            with storage.connect() as db:
                storage.write_rows(db,'consumption',[first,second]);storage.write_rows(db,'consumption',[revised])
            with storage.connect() as db:rows=storage.read_rows(db,'consumption')
            self.assertEqual(len(rows),2)
            self.assertEqual([r['consumption'] for r in rows],[3,2])
