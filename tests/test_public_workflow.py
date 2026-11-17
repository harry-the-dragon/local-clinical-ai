"""Fictional parsing and HTTP boundary checks; no model inference."""
import base64
import json
from pathlib import Path
import secrets
import sys
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, build_opener, ProxyHandler
from http.server import ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
from app import Handler
from core import parse_document
from correspondence import evidence
from source_structure import cases
from state import State


class PublicWorkflowChecks(unittest.TestCase):
    def test_fictional_case_structure(self):
        doc = parse_document('demo.txt', (ROOT / 'app/assets/demo.txt').read_bytes())
        parsed = cases(doc)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(len(parsed[0].encounters), 3)
        ctx = evidence(parsed[0])
        self.assertEqual(ctx['latest_date'], '2026-10-01')
        self.assertEqual(ctx['comparison_date'], '2026-09-15')
        self.assertFalse(ctx['discharge_documented'])

    def test_unsupported_file_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_document('scan.jpg', b'fictional image bytes')

    def test_unidentified_document_is_rejected(self):
        with self.assertRaises(ValueError):
            cases(parse_document('anonymous.txt', b'S/ Neck stiffness.\nO/ Extension 30 degrees.'))

    def test_local_http_authentication_and_demo(self):
        with tempfile.TemporaryDirectory() as directory:
            server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            server.token = secrets.token_hex(24)
            server.state = State(Path(directory)/'missing.gguf', Path(directory)/'missing.exe', auto_run=False, diagnostics_dir=Path(directory)/'diagnostics')
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            base = f'http://127.0.0.1:{server.server_port}'
            urlopen = build_opener(ProxyHandler({})).open
            try:
                with urlopen(base) as response:
                    self.assertIn(b'Try fictional three-visit sample', response.read())
                with self.assertRaises(HTTPError) as blocked:
                    urlopen(base + '/api/state')
                self.assertEqual(blocked.exception.code, 403)
                request = Request(base+'/api/demo', data=b'{}', headers={'Content-Type':'application/json','X-Session-Key':server.token})
                with urlopen(request) as response:
                    snapshot = json.load(response)
                self.assertEqual(snapshot['status'], 'imported')
                self.assertEqual(len(snapshot['cases']), 1)
                self.assertFalse(snapshot['model_ready'])
                request = Request(base+'/api/demo', data=b'{}', headers={'Content-Type':'application/json','X-Session-Key':server.token,'Origin':'https://example.invalid'})
                with self.assertRaises(HTTPError) as blocked:
                    urlopen(request)
                self.assertEqual(blocked.exception.code, 403)
            finally:
                server.shutdown()
                worker.join(timeout=5)
                server.server_close()


if __name__ == '__main__':
    unittest.main()
