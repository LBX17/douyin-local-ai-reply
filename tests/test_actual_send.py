"""No network writes: test explicit sending mode and conservative API results."""
import sys
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT
sys.path.insert(0, str(PROJECT))
with patch('dotenv.load_dotenv', return_value=False):
    from trial_launcher import TrialGUI
from send_result import SendResult, parse_send_result
from static import Response_pb2


class ResultCases(unittest.TestCase):
    def test_only_explicit_zero_result_codes_are_accepted(self):
        for payload in (b'{"status_code":0}', b'{"data":{"error_code":"0"}}'):
            self.assertEqual(parse_send_result(SimpleNamespace(status_code=200, content=payload)).status,
                             'accepted')
        for payload in (b'{"status_code":1}', b'{"status_code":0,"data":{"error_code":7}}'):
            self.assertEqual(parse_send_result(SimpleNamespace(status_code=200, content=payload)).status,
                             'failed')

    def test_empty_unknown_and_incomplete_ack_are_not_success(self):
        ack = Response_pb2.Response(cmd=100).SerializeToString()
        for payload in (b'', b'<html>challenge</html>', b'{"message":"unknown"}', ack):
            self.assertEqual(parse_send_result(SimpleNamespace(status_code=200, content=payload)).status,
                             'unconfirmed')
        self.assertEqual(parse_send_result(SimpleNamespace(status_code=403, content=b'')).status, 'failed')
        error = Response_pb2.Response(cmd=100, error_desc='synthetic-error').SerializeToString()
        self.assertEqual(parse_send_result(SimpleNamespace(status_code=200, content=error)).status, 'failed')


class SendModeCases(unittest.TestCase):
    def setUp(self):
        self.app = object.__new__(TrialGUI)
        self.app.my_uid = '900000001'
        self.app.running = True
        self.app.actual_send_enabled = False
        self.app.auth = SimpleNamespace(private_key='synthetic', client_cert='synthetic',
                                        ts_sign='synthetic', ticket='synthetic')
        self.logs = []
        self.app.log = self.logs.append

    def send(self, **options):
        self.app.send_reply('0:1:900000001:900000002', 900000003, 'synthetic-reply',
                             conversation_type=1, **options)

    def test_preview_and_old_queued_preview_messages_cannot_send(self):
        with patch('dy_apis.douyin_api.DouyinAPI.send_msg') as api:
            self.send(send_allowed=True)
            self.app.actual_send_enabled = True
            self.send(send_allowed=False)
        api.assert_not_called()
        self.assertEqual(sum('拟回复（未发送）' in line for line in self.logs), 2)

    def test_new_authorized_private_message_calls_api_once(self):
        self.app.actual_send_enabled = True
        with patch('dy_apis.douyin_api.DouyinAPI.send_msg',
                   return_value=SendResult('accepted', 'synthetic-confirmed')) as api:
            self.send(send_allowed=True)
        api.assert_called_once()
        self.assertIn('✅ synthetic-confirmed', self.logs)

    def test_stopped_or_unknown_account_cannot_send(self):
        self.app.actual_send_enabled = True
        with patch('dy_apis.douyin_api.DouyinAPI.send_msg') as api:
            self.app.running = False
            self.send(send_allowed=True)
            self.app.running = True
            self.app.my_uid = None
            self.send(send_allowed=True)
        api.assert_not_called()

    def test_failed_and_uncertain_requests_are_not_reported_successful_or_retried(self):
        self.app.actual_send_enabled = True
        for status in ('failed', 'unconfirmed'):
            with self.subTest(status=status):
                self.logs.clear()
                with patch('dy_apis.douyin_api.DouyinAPI.send_msg',
                           return_value=SendResult(status, 'synthetic-result')) as api:
                    self.send(send_allowed=True)
                api.assert_called_once()
                self.assertFalse(any('✅' in line for line in self.logs))

    def test_send_mode_is_persisted_and_can_be_disabled(self):
        with tempfile.TemporaryDirectory(prefix='send-mode-test-') as directory:
            self.app.reply_mode_path = Path(directory) / 'reply_mode.json'
            self.app.send_mode = Mock()
            self.app.root = Mock()
            self.app.reply_mode_label = Mock()
            self.app.set_send_mode(True)
            self.assertTrue(self.app.actual_send_enabled)
            self.assertEqual(json.loads(self.app.reply_mode_path.read_text('utf-8')),
                             {'actual_send_enabled': True})
            self.app.set_send_mode(False)
            self.assertFalse(self.app.actual_send_enabled)
            self.assertEqual(json.loads(self.app.reply_mode_path.read_text('utf-8')),
                             {'actual_send_enabled': False})


if __name__ == '__main__':
    unittest.main(verbosity=2)
