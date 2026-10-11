import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app_settings import DEFAULTS
from check_repo_secrets import scan_file
from trial_launcher import TrialGUI, gui_module


class StartupAndExport(unittest.TestCase):
    def test_rapid_start_clicks_create_only_one_connection_attempt(self):
        app = object.__new__(TrialGUI)
        app.running = app.starting = app.login_in_progress = False
        app.log = Mock()
        with patch('desktop_ui.read_session', return_value=SimpleNamespace(has_session=True)), \
             patch('desktop_ui.read_settings', return_value={**DEFAULTS, 'AI_MODEL': 'synthetic'}), \
             patch.object(gui_module.DouyinGUI, 'start_system') as start:
            app.start_system()
            app.start_system()
        start.assert_called_once()
        self.assertTrue(app.starting)

    def test_stop_during_ai_startup_prevents_late_websocket_connection(self):
        app = object.__new__(TrialGUI)
        app.listen_epoch = 0
        app.running = False
        app.log = Mock()
        app.configure_history = Mock()
        system = Mock()
        system.ai_fallback = True
        system.ai_config.requires_api_key = False
        def stop_during_test():
            app.listen_epoch += 1
            return True
        system.test_ai_connection.side_effect = stop_during_test
        auth = Mock()
        auth.get_uid.return_value = '900000001'
        auth.cookie = {'sessionid': 'synthetic-session'}
        with patch('trial_launcher.gui_module.load_dotenv'), \
             patch('trial_launcher.gui_module.DouyinAuth', return_value=auth), \
             patch('dy_apis.douyin_api.DouyinAPI.get_device_id', return_value='900000006'), \
             patch('trial_launcher.gui_module.AutoReplySystem', return_value=system), \
             patch('trial_launcher.gui_module.WebSocketApp') as websocket:
            gui_module.DouyinGUI.run_system(app)
        websocket.assert_not_called()
        app.log.assert_any_call('启动期间已停止，取消本次连接。')
        self.assertFalse(app.running)

    def test_fallback_knowledge_does_not_match_substrings(self):
        knowledge = object.__new__(gui_module.KnowledgeBaseManager)
        knowledge.knowledge_base = [{'question': '你好', 'answer': '你好呀'}]
        self.assertEqual(knowledge.match_knowledge(' 你好 '), '你好呀')
        self.assertIsNone(knowledge.match_knowledge('你'))
        self.assertIsNone(knowledge.match_knowledge('你好，今天忙吗'))
        self.assertIsNone(knowledge.match_knowledge(''))

    def test_export_rejects_runtime_files_and_detects_synthetic_secrets(self):
        for path in ['.env', 'accounts.json', 'datas/style_samples.jsonl', '.venv/config.py', 'model.gguf']:
            self.assertTrue(scan_file(path, b''))
        synthetic_token = b'ghp_' + b'a' * 25
        self.assertIn('GitHub token', scan_file('code.py', synthetic_token))
        self.assertTrue(scan_file('config_ai.env.example', b'AI_API_KEY=synthetic-value'))
        self.assertEqual(scan_file('config_ai.env.example', b"AI_API_KEY=''\n"), [])
