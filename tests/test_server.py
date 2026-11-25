import http.client
import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from tibber_local.__main__ import Handler
from tibber_local import storage
from tibber_local.demo import create_demo


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        cls.old=os.environ.get('TIBBER_LOCAL_DATA_DIR')
        os.environ['TIBBER_LOCAL_DATA_DIR']=cls.temp.name
        create_demo()
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=cls.server.serve_forever,daemon=True).start()
        cls.port=cls.server.server_port

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.temp.cleanup()
        if cls.old is None:os.environ.pop('TIBBER_LOCAL_DATA_DIR',None)
        else:os.environ['TIBBER_LOCAL_DATA_DIR']=cls.old

    def get(self,path,headers=None):
        conn=http.client.HTTPConnection('127.0.0.1',self.port)
        conn.request('GET',path,headers=headers or {})
        response=conn.getresponse();body=response.read();result=(response.status,dict(response.getheaders()),body);conn.close();return result

    def test_private_api_requires_session(self):
        self.assertEqual(self.get('/api/analysis')[0],403)

    def test_rebinding_host_blocked(self):
        self.assertEqual(self.get('/',{'Host':'attacker.invalid'})[0],403)

    def test_session_data_and_no_credential_fields(self):
        status,headers,_=self.get('/')
        self.assertEqual(status,200)
        cookie=headers['Set-Cookie'].split(';')[0]
        self.assertIn('HttpOnly',headers['Set-Cookie'])
        status,_,body=self.get('/api/analysis',{'Cookie':cookie})
        self.assertEqual(status,200)
        result=json.loads(body)
        self.assertEqual(result['summary']['hours'],8760)
        self.assertNotIn('home_id',body.decode())
        self.assertNotIn('token',body.decode())

    def test_cross_origin_write_blocked(self):
        _,headers,_=self.get('/')
        conn=http.client.HTTPConnection('127.0.0.1',self.port)
        conn.request('POST','/api/settings',body='{"hours":24}',headers={'Content-Type':'application/json','Cookie':headers['Set-Cookie'].split(';')[0],'Origin':'https://attacker.invalid'})
        response=conn.getresponse();response.read();self.assertEqual(response.status,403);conn.close()
        self.assertEqual(storage.config()['refresh_hours'],0)

    def test_private_paths_not_served(self):
        _,headers,_=self.get('/')
        self.assertEqual(self.get('/../token',{'Cookie':headers['Set-Cookie'].split(';')[0]})[0],404)

if __name__=='__main__':unittest.main()
