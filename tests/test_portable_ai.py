import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from ai_auto_reply import AIClient, AIConfig, AutoReplySystem
from app_settings import DEFAULTS, initialize_local_files, read_settings, save_settings, validate_settings, read_models
from app import InstanceLock


class PortableAI(unittest.TestCase):
    def test_common_providers_use_standard_payload_without_llama_extensions(self):
        for provider in ['openai', 'ollama', 'lm_studio']:
            response = Mock(status_code=200)
            response.json.return_value = {'choices': [{'finish_reason': 'stop', 'message': {'content': '收到'}}]}
            client = AIClient(AIConfig(provider=provider, base_url='http://localhost:1234/v1', model='test-model'))
            with patch('requests.post', return_value=response) as post:
                self.assertEqual(client.chat('你好', record=False), '收到')
            self.assertEqual(post.call_args.args[0], 'http://localhost:1234/v1/chat/completions')
            self.assertNotIn('chat_template_kwargs', post.call_args.kwargs['json'])
            self.assertNotIn('reasoning_format', post.call_args.kwargs['json'])
            self.assertEqual(client.session_history['default'], [])

    def test_anthropic_v1_path_and_auth_are_correct(self):
        response = Mock(status_code=200)
        response.json.return_value = {'content': [{'type': 'text', 'text': '收到'}], 'stop_reason': 'end_turn'}
        client = AIClient(AIConfig(provider='anthropic', base_url='https://example.com/v1', api_key='synthetic', model='test'))
        with patch('requests.post', return_value=response) as post:
            self.assertEqual(client.chat('你好', record=False), '收到')
        self.assertEqual(post.call_args.args[0], 'https://example.com/v1/messages')
        self.assertEqual(post.call_args.kwargs['headers']['x-api-key'], 'synthetic')

    def test_settings_round_trip_preserves_prompt_and_clears_key(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config_ai.env'
            values = {**DEFAULTS, 'AI_MODEL': 'synthetic-model', 'SYSTEM_PROMPT': "第一行\n含有'引号'和中文", 'AI_API_KEY': 'synthetic'}
            save_settings(values, path)
            self.assertEqual(read_settings(path)['SYSTEM_PROMPT'], values['SYSTEM_PROMPT'])
            values['AI_API_KEY'] = ''
            save_settings(values, path)
            self.assertEqual(read_settings(path)['AI_API_KEY'], '')
            system = AutoReplySystem(str(path))
            self.assertEqual(system.ai_config.model, 'synthetic-model')
            self.assertEqual(system.ai_config.api_key, '')
            self.assertTrue(str(system.blacklist.blacklist_file).startswith(folder))
            system.executor.shutdown(wait=False)

    def test_invalid_and_credential_bearing_urls_are_rejected(self):
        for url in ['file:///tmp/file', 'http://example.com/v1', 'https://user:secret@example.com/v1', 'https://example.com/v1?key=synthetic']:
            with self.assertRaises(ValueError):
                validate_settings({**DEFAULTS, 'AI_MODEL': 'test', 'AI_BASE_URL': url})

    def test_model_discovery_uses_configured_endpoint(self):
        response = Mock()
        response.json.return_value = {'data': [{'id': 'synthetic-model'}]}
        with patch('requests.get', return_value=response) as get:
            self.assertEqual(read_models({**DEFAULTS, 'AI_BASE_URL': 'http://localhost:11434/v1'}), ['synthetic-model'])
        self.assertEqual(get.call_args.args[0], 'http://localhost:11434/v1/models')

    def test_duplicate_instance_cannot_acquire_same_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            first, second = InstanceLock(Path(folder) / 'app.lock'), InstanceLock(Path(folder) / 'app.lock')
            try:
                self.assertTrue(first.acquire())
                self.assertFalse(second.acquire())
                first.release()
                self.assertTrue(second.acquire())
            finally:
                first.release()
                second.release()

    def test_initializer_never_overwrites_existing_credentials(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / '.env.example').write_text('DY_COOKIES=\n', 'utf-8')
            (root / '.env').write_text('synthetic-existing-content', 'utf-8')
            initialize_local_files(root)
            self.assertEqual((root / '.env').read_text('utf-8'), 'synthetic-existing-content')
