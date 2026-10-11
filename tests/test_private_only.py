"""Offline checks: only explicitly identified private messages may be replied to."""

import inspect
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT
sys.path.insert(0, str(PROJECT))

# Import the GUI class without reading .env/config files or constructing Tk.
with patch('dotenv.load_dotenv', return_value=False):
    from trial_launcher import TrialGUI, gui_module
from static import Live_pb2, Response_pb2
from ai_auto_reply import AIClient, AIConfig


OWN_UID = '900000001'
OTHER_UID = 900000002
CONVERSATION_ID = '0:1:900000001:900000002'
CONVERSATION_SHORT_ID = 900000003
PRIVATE_TEXT = 'synthetic-private-message'
BLOCKED_TEXT = 'synthetic-group-body-must-not-appear-in-logs'


def wrap_response(response):
    frame = Live_pb2.PushFrame()
    frame.payloadType = 'pb'
    frame.payload = response.SerializeToString()
    return frame.SerializeToString()


def make_message(notify_type, message_type, text=BLOCKED_TEXT):
    response = Response_pb2.Response()
    notify = response.body.new_message_notify
    notify.conversation_id = CONVERSATION_ID
    notify.conversation_type = notify_type
    message = notify.message
    message.conversation_id = CONVERSATION_ID
    message.conversation_short_id = CONVERSATION_SHORT_ID
    message.conversation_type = message_type
    message.sender = OTHER_UID
    message.message_type = 7
    message.content = json.dumps({'text': text})
    return wrap_response(response)


class PrivateOnlyCases(unittest.TestCase):
    def setUp(self):
        self.app = object.__new__(TrialGUI)
        self.app.my_uid = OWN_UID
        self.app.actual_send_enabled = False
        self.logs = []
        self.app.log = self.logs.append
        self.app.system = Mock()
        self.app.system.ai_client = AIClient(AIConfig())
        self.app.reply_executor = Mock()
        self.app.system.min_delay = 0
        self.app.system.max_delay = 0
        self.app.kb_manager = Mock()
        self.app.send_reply = Mock()

    def assert_no_processing_error(self):
        self.assertFalse(any('消息处理错误' in line for line in self.logs), self.logs)

    def test_both_private_types_start_one_reply_with_explicit_private_type(self):
        self.app.on_message(None, make_message(1, 1, PRIVATE_TEXT))
        self.app.reply_executor.submit.assert_called_once()
        target, *args = self.app.reply_executor.submit.call_args.args
        self.assertEqual(target, self.app.reply_async)
        call = inspect.signature(self.app.reply_async).bind(*args)
        call.apply_defaults()
        self.assertEqual(call.arguments['text'], PRIVATE_TEXT)
        self.assertEqual(call.arguments['conversation_id'], CONVERSATION_ID)
        self.assertEqual(call.arguments['sender'], OTHER_UID)
        self.assertEqual(call.arguments['conversation_short_id'], CONVERSATION_SHORT_ID)
        self.assertEqual(call.arguments['conversation_type'], 1)
        self.assert_no_processing_error()
        self.app.system.process_message.assert_not_called()
        self.app.send_reply.assert_not_called()

    def test_missing_group_conflicting_and_unknown_types_never_start_reply(self):
        # Zero-valued proto3 scalar fields are omitted from the serialized
        # message, so these also exercise genuinely missing type fields.
        rejected_types = (
            (1, 0), (0, 1), (0, 0), (2, 2), (1, 2), (2, 1),
            (99, 1), (-1, 1), (1, 99), (1, -1),
        )
        for notify_type, message_type in rejected_types:
            with self.subTest(notify_type=notify_type, message_type=message_type):
                self.logs.clear()
                with patch('trial_launcher.gui_module.threading.Thread') as thread:
                    self.app.on_message(None, make_message(notify_type, message_type))
                thread.assert_not_called()
                self.assertNotIn(BLOCKED_TEXT, '\n'.join(self.logs))
                self.assert_no_processing_error()
        self.app.reply_executor.submit.assert_not_called()
        self.app.system.process_message.assert_not_called()
        self.app.send_reply.assert_not_called()

    def test_non_message_notification_is_ignored(self):
        for notification in ('empty', 'create_conversation_v2_body'):
            with self.subTest(notification=notification):
                response = Response_pb2.Response()
                if notification != 'empty':
                    getattr(response.body, notification).SetInParent()
                self.logs.clear()
                with patch('trial_launcher.gui_module.threading.Thread') as thread:
                    self.app.on_message(None, wrap_response(response))
                thread.assert_not_called()
                self.assert_no_processing_error()

    def test_notification_without_message_is_ignored(self):
        response = Response_pb2.Response()
        response.body.new_message_notify.conversation_type = 1
        response.body.new_message_notify.conversation_id = CONVERSATION_ID
        self.assertFalse(response.body.new_message_notify.HasField('message'))
        with patch('trial_launcher.gui_module.threading.Thread') as thread:
            self.app.on_message(None, wrap_response(response))
        thread.assert_not_called()
        self.assert_no_processing_error()

    def test_direct_reply_rejects_default_unknown_and_group_types_before_ai_or_send(self):
        for conversation_type in (None, 0, 2):
            with self.subTest(conversation_type=conversation_type):
                options = {} if conversation_type is None else {
                    'conversation_type': conversation_type,
                }
                with patch('trial_launcher.gui_module.time.sleep') as sleep:
                    self.app.reply_async(
                        BLOCKED_TEXT, CONVERSATION_ID, OTHER_UID,
                        CONVERSATION_SHORT_ID, **options)
                sleep.assert_not_called()
                self.app.system.process_message.assert_not_called()
                self.app.kb_manager.match_knowledge.assert_not_called()
                self.app.send_reply.assert_not_called()
                self.assertNotIn(BLOCKED_TEXT, '\n'.join(self.logs))

    def test_send_entry_points_reject_group_and_unconfirmed_types(self):
        base_gui = gui_module.DouyinGUI
        for send in (base_gui.send_reply, TrialGUI.send_reply):
            for conversation_type in (0, 2, 99):
                with self.subTest(entry=send.__qualname__, conversation_type=conversation_type):
                    self.logs.clear()
                    send(self.app, CONVERSATION_ID, CONVERSATION_SHORT_ID,
                         BLOCKED_TEXT, conversation_type=conversation_type)
                    self.assertNotIn(BLOCKED_TEXT, '\n'.join(self.logs))
                    self.assertFalse(any('拟回复（未发送）' in line for line in self.logs))
                    self.assertFalse(any('发送失败' in line for line in self.logs))

    def test_private_reply_reaches_preview_without_sending(self):
        def generate(message):
            self.app.system.ai_client.remember(message.conversation_id, 'user', message.content)
            return 'synthetic-ai-reply'
        self.app.system.process_message.side_effect = generate
        self.app.system.knowledge_first = False
        self.app.send_reply = TrialGUI.send_reply.__get__(self.app)
        self.app.reply_async(PRIVATE_TEXT, CONVERSATION_ID, OTHER_UID,
                             CONVERSATION_SHORT_ID, conversation_type=1)
        self.app.system.process_message.assert_called_once()
        self.assertTrue(any('拟回复（未发送）: synthetic-ai-reply' in line for line in self.logs))
        self.assertFalse(any('回复错误' in line for line in self.logs))


if __name__ == '__main__':
    unittest.main(verbosity=2)
