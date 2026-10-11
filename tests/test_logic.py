import json, sys, time, unittest, tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
with patch('dotenv.load_dotenv', return_value=False):
    from trial_launcher import TrialGUI
from ai_auto_reply import AIClient, AIConfig, AutoReplySystem, KnowledgeBase, Message
from send_result import SendResult
from static import Live_pb2, Response_pb2


class LogicCases(unittest.TestCase):
    def client(self):
        return AIClient(AIConfig(provider='llama_cpp', base_url='http://127.0.0.1:8080/v1',
                                 thinking=True, max_tokens=1536, temperature=1.0))

    def app(self):
        app = object.__new__(TrialGUI)
        client = self.client()
        def generate(message):
            client.remember(message.conversation_id, 'user', message.content)
            return 'reply-' + message.content
        app.system = SimpleNamespace(ai_client=client, min_delay=0, max_delay=0,
                                     knowledge_first=False, process_message=Mock(side_effect=generate))
        app.logs = []
        app.log = app.logs.append
        app.running = True
        app.listen_epoch = 0
        app.actual_send_enabled = True
        app.my_uid = '900000001'
        app.kb_manager = Mock()
        app.send_reply = Mock(return_value=SendResult('accepted', 'synthetic'))
        return app

    def test_thinking_payload_excludes_reasoning_from_reply(self):
        client = self.client()
        response = Mock(status_code=200)
        response.json.return_value = {'choices': [{'finish_reason': 'stop', 'message': {
            'content': '明天下午四点', 'reasoning_content': 'hidden reasoning'}}]}
        with patch('requests.post', return_value=response) as post:
            self.assertEqual(client.chat('几点？', 'one', 'prompt'), '明天下午四点')
        payload = post.call_args.kwargs['json']
        self.assertTrue(payload['chat_template_kwargs']['enable_thinking'])
        self.assertEqual(payload['reasoning_format'], 'deepseek')
        self.assertGreater(payload['max_tokens'], 512)
        self.assertNotIn('hidden reasoning', str(client.session_history))

    def test_partial_empty_and_raw_thinking_outputs_never_enter_history(self):
        for finish, content in [('length', '半截回复'), ('stop', ''), ('stop', '<think>分析</think>回答')]:
            client = self.client()
            response = Mock(status_code=200)
            response.json.return_value = {'choices': [{'finish_reason': finish, 'message': {'content': content}}]}
            with patch('requests.post', return_value=response):
                self.assertIsNone(client.chat('synthetic', 'one'))
            self.assertEqual(client.session_history['one'], [])

    def test_failed_preview_and_unconfirmed_sends_are_not_confirmed_history(self):
        client = self.client()
        client.remember('one', 'user', '啥事')
        client.remember_send_result('one', '失败回复', 'failed')
        client.remember_send_result('one', '待确认回复', 'unconfirmed')
        self.assertEqual(client.session_history['one'], [{'role': 'user', 'content': '啥事'}])
        self.assertEqual(client.pending_replies['one'], '待确认回复')
        client.remember('one', 'assistant', '待确认回复')
        self.assertNotIn('one', client.pending_replies)
        client.remember_send_result('one', '待确认回复', 'accepted')
        self.assertEqual(len(client.session_history['one']), 2)
        self.assertNotIn('two', client.session_history)

    def test_recent_local_memory_survives_restart_and_expired_sessions_are_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'account-one.json'
            first = self.client()
            first.use_history_store(path)
            first.remember('one', 'user', '改成周日下午四点')
            first.remember('one', 'assistant', '好，四点见')
            second = self.client()
            second.use_history_store(path)
            self.assertEqual(first.session_history, second.session_history)
            other = self.client()
            other.use_history_store(Path(directory) / 'account-two.json')
            self.assertEqual(other.session_history, {})
            saved = json.loads(path.read_text('utf-8'))
            saved['sessions']['one']['updated'] = time.time() - 90000
            path.write_text(json.dumps(saved), 'utf-8')
            expired = self.client()
            expired.use_history_store(path)
            self.assertEqual(expired.session_history, {})

    def test_knowledge_reply_and_incoming_share_context(self):
        system = object.__new__(AutoReplySystem)
        system.ai_client = self.client()
        system.blacklist = SimpleNamespace(is_blocked=lambda sender: False)
        system.logger = Mock()
        system.auto_reply_enabled = True
        system.knowledge_first = True
        system.knowledge_base = Mock()
        system.knowledge_base.find_match.return_value = '嗨~'
        self.assertEqual(system.process_message(Message('peer', '你好', 'one')), '嗨~')
        system.ai_client.remember_send_result('one', '嗨~', 'accepted')
        self.assertEqual(system.ai_client.session_history['one'], [
            {'role': 'user', 'content': '你好'}, {'role': 'assistant', 'content': '嗨~', 'origin': 'generated'}])

    def test_short_knowledge_phrase_does_not_match_unrelated_question(self):
        kb = object.__new__(KnowledgeBase)
        kb.knowledge = [{'question': '你好', 'answer': '嗨'}]
        self.assertEqual(kb.find_match('你好'), '嗨')
        for text in ('', '好', '你好吗', '之前你好像说过地址'):
            self.assertIsNone(kb.find_match(text))

    def test_owner_reply_during_delay_cancels_obsolete_auto_reply(self):
        app = self.app()
        def owner_reply(_):
            app.system.ai_client.remember('one', 'assistant', '我已经手动回了')
        with patch('trial_launcher.gui_module.time.sleep', side_effect=owner_reply):
            app.reply_async('旧问题', 'one', 'peer', 10, 1, True)
        app.system.process_message.assert_not_called()
        app.send_reply.assert_not_called()

    def test_owner_reply_during_generation_cancels_obsolete_draft(self):
        app = self.app()
        def generate(message):
            app.system.ai_client.remember('one', 'user', message.content)
            app.system.ai_client.remember('one', 'assistant', '本人已回复')
            return '过时的自动回复'
        app.system.process_message.side_effect = generate
        app.reply_async('问题', 'one', 'peer', 10, 1, True)
        app.send_reply.assert_not_called()

    def test_disabled_or_failed_ai_does_not_bypass_to_old_knowledge_fallback(self):
        app = self.app()
        app.system.process_message.side_effect = None
        app.system.process_message.return_value = None
        app.reply_async('问题', 'one', 'peer', 10, 1, True)
        app.send_reply.assert_not_called()
        app.kb_manager.match_knowledge.assert_not_called()

    def test_pre_stop_queue_cannot_send_after_restart(self):
        app = self.app()
        app.listen_epoch = 2
        app.reply_async('旧消息', 'one', 'peer', 10, 1, True, listen_epoch=1)
        app.system.process_message.assert_not_called()
        app.send_reply.assert_not_called()

    def test_real_protobuf_replies_use_fifo_and_owner_echo_updates_context(self):
        app = self.app()
        def frame(text, sender=900000002):
            response = Response_pb2.Response()
            notify = response.body.new_message_notify
            notify.conversation_type = 1
            msg = notify.message
            msg.conversation_type = 1
            msg.conversation_id = 'one'
            msg.conversation_short_id = 10
            msg.sender = sender
            msg.message_type = 7
            msg.content = json.dumps({'text': text})
            push = Live_pb2.PushFrame(payloadType='pb', payload=response.SerializeToString())
            return push.SerializeToString()
        with ThreadPoolExecutor(max_workers=1) as executor:
            app.reply_executor = executor
            for text in ['first', 'second', 'third']:
                app.on_message(None, frame(text))
        self.assertEqual([call.args[2] for call in app.send_reply.call_args_list],
                         ['reply-first', 'reply-second', 'reply-third'])
        self.assertEqual(app.system.ai_client.session_history['one'][-2:], [
            {'role': 'user', 'content': 'third'}, {'role': 'assistant', 'content': 'reply-third', 'origin': 'generated'}])
        app.on_message(None, frame('我在图书馆', sender=900000001))
        self.assertEqual(app.system.ai_client.session_history['one'][-1],
                         {'role': 'assistant', 'content': '我在图书馆', 'origin': 'owner'})
        self.assertEqual(app.send_reply.call_count, 3)
        self.assertFalse(any('错误' in line for line in app.logs), app.logs)

    def test_confirmed_auto_echo_keeps_generated_origin(self):
        client = self.client()
        client.expect_outgoing('one', '吃了')
        client.remember('one', 'assistant', '吃了')
        self.assertEqual(client.session_history['one'][0]['origin'], 'generated')
        client.remember_send_result('one', '吃了', 'unconfirmed')
        self.assertNotIn('one', client.pending_replies)

    def test_unknown_live_state_does_not_invent_owner_facts(self):
        client = self.client()
        client.config.personal_fact_guard = True
        client.remember('one', 'assistant', '吃了', origin='generated')
        with patch('requests.post') as post:
            self.assertEqual(client.chat('吃的啥饭', 'one'), '你吃的啥呀？')
            self.assertEqual(client.chat('你现在在哪儿', 'two'), '怎么啦，找我有啥事呀？')
        post.assert_not_called()
        client.remember('three', 'assistant', '我在图书馆', origin='owner')
        self.assertIsNone(client.unknown_personal_fact_reply('你现在在哪儿', client.session_history['three']))
        self.assertIsNone(client.unknown_personal_fact_reply('我吃饭了吗', []))


if __name__ == '__main__':
    unittest.main(verbosity=2)
