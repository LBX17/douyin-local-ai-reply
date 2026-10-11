#!/usr/bin/env python3
"""
AI智能回复系统 - 支持MiniMax API
"""

import os
import sys
import json
import time
import random
import logging
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
import hashlib
import re

# 加载环境变量
from dotenv import load_dotenv
from account_manager import safe_print

@dataclass
class Message:
    """消息结构"""
    sender: str
    content: str
    conversation_id: str
    timestamp: float = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = time.time()

@dataclass
class AIConfig:
    """AI配置"""
    provider: str = "openai"
    api_key: str = ""
    base_url: str = "http://127.0.0.1:8080/v1"
    model: str = ""
    max_tokens: int = 1000
    temperature: float = 0.7
    timeout: int = 180
    thinking: bool = False
    reasoning_effort: str = 'low'
    top_p: float = 0.95
    top_k: int = 20
    personal_fact_guard: bool = False

    @property
    def requires_api_key(self) -> bool:
        return self.provider.lower() == "anthropic"

class KnowledgeBase:
    """知识库"""
    
    def __init__(self, kb_file: str):
        self.kb_file = kb_file
        self.knowledge = []
        self.load()
    
    def load(self):
        """加载知识库"""
        try:
            if os.path.exists(self.kb_file):
                with open(self.kb_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.knowledge = data.get('knowledge_base', [])
                safe_print(f"✅ 知识库加载成功，共 {len(self.knowledge)} 条")
            else:
                safe_print(f"⚠️ 知识库文件不存在: {self.kb_file}")
        except Exception as e:
            safe_print(f"❌ 知识库加载失败: {e}")
            self.knowledge = []
    
    def find_match(self, question: str, threshold: float = 0.7) -> Optional[str]:
        """查找匹配的知识"""
        question = question.lower().strip()
        
        if not question:
            return None
        for item in self.knowledge:
            q = item.get('question', '').lower().strip()
            # Short phrases must match exactly: e.g. 好 must not match 你好.
            if q and q == question:
                return item.get('answer', '')
        
        return None

class Blacklist:
    """黑名单管理"""
    
    def __init__(self, blacklist_file: str):
        self.blacklist_file = blacklist_file
        self.blocked_users = set()
        self.lock = Lock()
        self.load()
    
    def load(self):
        """加载黑名单"""
        try:
            if os.path.exists(self.blacklist_file):
                with open(self.blacklist_file, 'r', encoding='utf-8') as f:
                    self.blocked_users = set(line.strip() for line in f if line.strip())
                safe_print(f"✅ 黑名单加载成功，共 {len(self.blocked_users)} 个用户")
            else:
                # 创建空的黑名单文件
                Path(self.blacklist_file).parent.mkdir(parents=True, exist_ok=True)
                with open(self.blacklist_file, 'w', encoding='utf-8') as f:
                    f.write("")
                safe_print("✅ 黑名单文件已创建")
        except Exception as e:
            safe_print(f"❌ 黑名单加载失败: {e}")
    
    def is_blocked(self, user_id: str) -> bool:
        """检查用户是否在黑名单中"""
        with self.lock:
            return user_id in self.blocked_users
    
    def add(self, user_id: str):
        """添加用户到黑名单"""
        with self.lock:
            self.blocked_users.add(user_id)
            self.save()
    
    def remove(self, user_id: str):
        """从黑名单移除用户"""
        with self.lock:
            self.blocked_users.discard(user_id)
            self.save()
    
    def save(self):
        """保存黑名单"""
        try:
            with open(self.blacklist_file, 'w', encoding='utf-8') as f:
                f.write('\n'.join(sorted(self.blocked_users)))
        except Exception as e:
            safe_print(f"❌ 保存黑名单失败: {e}")

class AIClient:
    """Anthropic/MiniMax and local llama.cpp chat client."""
    
    def __init__(self, config: AIConfig):
        self.config = config
        self.session_history = {}  # Keyed by conversation, not just sender.
        self.session_lock = Lock()
        self.session_revision = {}
        self.pending_replies = {}
        self.history_path = None
        self.history_updated = {}
        self.expected_outgoing = {}

    def use_history_store(self, path):
        """Account-specific local memory; retain only the last 24 hours."""
        with self.session_lock:
            self.history_path = Path(path)
            self.history_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                saved = json.loads(self.history_path.read_text('utf-8'))
                for key, session in saved.get('sessions', {}).items():
                    if time.time() - float(session['updated']) > 86400:
                        continue
                    history = session['history'][-24:]
                    if all(item.get('role') in ('user', 'assistant') and isinstance(item.get('content'), str)
                           for item in history):
                        for item in history:
                            if item['role'] == 'assistant' and 'origin' not in item:
                                item['origin'] = 'unknown'
                        self.session_history[key] = history
                        self.history_updated[key] = session['updated']
            except FileNotFoundError:
                pass
            except (OSError, ValueError, TypeError, KeyError, AttributeError):
                safe_print('⚠️ 本地会话记忆无法读取，本次从新上下文开始')

    def _save_history_locked(self):
        if self.history_path is None:
            return
        recent = sorted(self.history_updated, key=self.history_updated.get, reverse=True)[:200]
        payload = {'version': 1, 'sessions': {
            key: {'updated': self.history_updated[key], 'history': self.session_history[key]}
            for key in recent if time.time() - self.history_updated[key] <= 86400}}
        temporary = self.history_path.with_suffix('.tmp')
        try:
            temporary.write_text(json.dumps(payload, ensure_ascii=False), 'utf-8')
            temporary.replace(self.history_path)
        except OSError:
            safe_print('⚠️ 会话记忆未能保存，当前进程仍保留上下文')

    def revision(self, conversation_id):
        with self.session_lock:
            return self.session_revision.get(conversation_id, 0)

    def expect_outgoing(self, conversation_id, content):
        with self.session_lock:
            self.expected_outgoing[conversation_id] = (content, time.monotonic())

    def remember(self, conversation_id, role, content, origin=None):
        if not content:
            return
        with self.session_lock:
            history = self.session_history.setdefault(conversation_id, [])
            expected = self.expected_outgoing.get(conversation_id)
            if role == 'assistant' and origin is None:
                if (expected and expected[0] == content and time.monotonic() - expected[1] < 120
                        or self.pending_replies.get(conversation_id) == content):
                    origin = 'generated'
                    self.expected_outgoing.pop(conversation_id, None)
                else:
                    origin = 'owner'
            # A confirmed send may subsequently be echoed by the WebSocket.
            if role == 'assistant' and history and history[-1]['role'] == role and history[-1]['content'] == content:
                return
            item = {'role': role, 'content': content}
            if origin:
                item['origin'] = origin
            history.append(item)
            history = history[-24:]
            while len(history) > 1 and sum(len(item['content']) for item in history) > 16000:
                history.pop(0)
            self.session_history[conversation_id] = history
            self.history_updated[conversation_id] = time.time()
            self.session_revision[conversation_id] = self.session_revision.get(conversation_id, 0) + 1
            if role == 'assistant' and self.pending_replies.get(conversation_id) == content:
                self.pending_replies.pop(conversation_id, None)
            self._save_history_locked()

    def remember_send_result(self, conversation_id, reply, status):
        if status == 'accepted':
            self.remember(conversation_id, 'assistant', reply, origin='generated')
        elif status == 'unconfirmed':
            with self.session_lock:
                history = self.session_history.get(conversation_id, [])
                if not history or history[-1]['role'] != 'assistant' or history[-1]['content'] != reply:
                    self.pending_replies[conversation_id] = reply

    def unknown_personal_fact_reply(self, message, history):
        """Common live-state questions require an owner-provided fact."""
        if not self.config.personal_fact_guard:
            return None
        rules = (
            (r'吃(?:过)?(?:早饭|午饭|晚饭|饭)?了?[吗没]|吃[的得]啥|吃了什么|吃啥饭',
             r'吃|饭|早餐|午餐|晚餐', '你呢，吃饭了没？'),
            (r'你(?:现在|这会儿)?(?:在|到)哪[儿里]?|你现在的位置|你现在在哪',
             r'在|到|去|位置', '怎么啦，找我有啥事呀？'),
            (r'睡了[吗没]|睡醒了?[吗没]|起床了?[吗没]',
             r'睡|醒|起床', '怎么啦，有啥事呀？'),
        )
        # Questions about the peer's own situation do not ask for owner facts.
        if message.strip().startswith(('我', '他', '她', '他们')):
            return None
        for question, evidence, fallback in rules:
            if re.search(question, message):
                known = any(item.get('origin') == 'owner' and re.search(evidence, item['content'])
                            for item in history[-8:] if item['role'] == 'assistant')
                if not known and re.search(r'吃[的得]啥|吃了什么|吃啥饭', message):
                    fallback = '你吃的啥呀？'
                return None if known else fallback
        return None
    
    def chat(self, message: str, user_id: str = "default", system_prompt: str = "", record: bool = True) -> str:
        """发送对话请求"""
        try:
            import requests
            
            # 获取或创建对话历史
            with self.session_lock:
                if user_id not in self.session_history:
                    self.session_history[user_id] = []
                
                history = list(self.session_history[user_id])
                pending = self.pending_replies.get(user_id)
            guarded_reply = self.unknown_personal_fact_reply(message, history)
            if guarded_reply:
                if record:
                    self.remember(user_id, 'user', message)
                    self.remember(user_id, 'assistant', guarded_reply, origin='generated')
                return guarded_reply
            if pending:
                system_prompt += ('\n上一条拟回复已提交，但平台尚未确认发送：' + pending +
                                  '\n它仅供话题衔接，不代表对方已收到，也不能作为个人事实的证据。')
            
            # 构建消息列表
            messages = []
            
            # 添加系统提示
            if system_prompt:
                messages.append({
                    "role": "system",
                    "content": system_prompt
                })
            
            # 添加历史对话（保留最近10条）
            for item in history[-24:]:
                content = item['content']
                if item['role'] == 'assistant':
                    content = ('[本人手动发送]\n' if item.get('origin') == 'owner'
                               else '[此前自动回复或来源未确认，不是主人事实证据]\n') + content
                messages.append({'role': item['role'], 'content': content})
            
            # 添加当前消息
            if record or not history or history[-1] != {'role': 'user', 'content': message}:
                messages.append({'role': 'user', 'content': message})
            
            # 调用API
            headers = {"Content-Type": "application/json"}
            if self.config.api_key:
                headers["Authorization"] = f"Bearer {self.config.api_key}"
            
            data = {
                "model": self.config.model,
                "messages": messages,
                "max_tokens": self.config.max_tokens,
                "temperature": self.config.temperature
            }

            provider = self.config.provider.lower()
            base_url = self.config.base_url.rstrip('/')
            if provider in {'openai', 'ollama', 'lm_studio', 'llama_cpp'}:
                # This local provider speaks the OpenAI-compatible protocol.
                url = base_url + ('/chat/completions' if base_url.endswith('/v1') else '/v1/chat/completions')
                data['stream'] = False
                data['top_p'] = self.config.top_p
                if provider == 'llama_cpp':
                    data['chat_template_kwargs'] = {'enable_thinking': self.config.thinking}
                    data['reasoning_effort'] = self.config.reasoning_effort if self.config.thinking else 'none'
                    data['reasoning_format'] = 'deepseek'
                    data['top_k'] = self.config.top_k
                    data['min_p'] = 0.0
                    data['presence_penalty'] = 0.0
            elif provider == 'anthropic':
                url = base_url + ('/messages' if base_url.endswith('/v1') else '/v1/messages')
                headers['anthropic-version'] = '2023-06-01'
                headers['x-api-key'] = self.config.api_key
                data['messages'] = [item for item in messages if item['role'] != 'system']
                if system_prompt:
                    data['system'] = system_prompt
            else:
                raise ValueError(f'Unsupported AI provider: {self.config.provider}')
            
            response = requests.post(
                url,
                headers=headers,
                json=data,
                timeout=self.config.timeout
            )
            
            if response.status_code == 200:
                result = response.json()
                
                # MiniMax API 返回格式：{"content":[{"text":"...","type":"text"}]}
                reply = ""
                if provider in {'openai', 'ollama', 'lm_studio', 'llama_cpp'}:
                    choices = result.get('choices', [])
                    if choices:
                        if choices[0].get('finish_reason') != 'stop':
                            safe_print('⚠️ AI 回复未完整结束，取消这条拟回复')
                            return None
                        reply = (choices[0].get('message', {}).get('content') or '').strip()
                else:
                    content = result.get('content', [])
                    if isinstance(content, list):
                        reply = '\n'.join(
                            item.get('text', '') for item in content if item.get('type') == 'text'
                        ).strip()
                
                if not reply or '<think' in reply.lower() or '</think' in reply.lower() or len(reply) > 300:
                    safe_print("⚠️ AI 未返回回复正文")
                    return None
                
                # 保存对话历史
                if record:
                    self.remember(user_id, 'user', message)
                    self.remember(user_id, 'assistant', reply, origin='generated')
                
                return reply
            else:
                safe_print(f"❌ API调用失败: HTTP {response.status_code}；请检查地址、模型名称和密钥。")
                return None
                
        except ImportError:
            safe_print("❌ 请安装requests库: pip install requests")
            return None
        except Exception as e:
            safe_print(f"❌ AI调用失败: {e}")
            traceback.print_exc()
            return None

class ReplyLogger:
    """日志记录"""
    
    def __init__(self, log_file: str, keep_days: int = 30):
        self.log_file = log_file
        self.keep_days = keep_days
        self.lock = Lock()
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        
        # 设置日志格式
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file, encoding='utf-8', delay=True),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
    
    def log(self, level: str, message: str, **kwargs):
        """记录日志"""
        log_data = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "level": level,
            "message": message
        }
        log_data.update(kwargs)
        
        log_msg = json.dumps(log_data, ensure_ascii=False)
        
        with self.lock:
            if level == "INFO":
                self.logger.info(log_msg)
            elif level == "ERROR":
                self.logger.error(log_msg)
            elif level == "WARNING":
                self.logger.warning(log_msg)

class AutoReplySystem:
    """自动回复系统"""
    
    def __init__(self, config_file: str = "config_ai.env"):
        from app_settings import read_settings, validate_settings
        values = read_settings(config_file)
        validate_settings(values)
        provider = values['AI_PROVIDER'].lower()
        api_key = values.get('AI_API_KEY', '').strip()
        base_url = values['AI_BASE_URL'].strip()
        def setting(name, default=''):
            return values.get(name, default)

        # 初始化配置
        self.ai_config = AIConfig(
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            model=setting('AI_MODEL', 'MiniMax-M2.7'),
            max_tokens=int(setting('MAX_TOKENS', '1000')),
            temperature=float(setting('TEMPERATURE', '0.7')),
            timeout=int(setting('AI_TIMEOUT', '180')),
            thinking=setting('AI_THINKING', 'false').lower() == 'true',
            reasoning_effort=setting('AI_REASONING_EFFORT', 'low'),
            top_p=float(setting('TOP_P', '0.95')),
            top_k=int(setting('TOP_K', '20')),
            personal_fact_guard=setting('PERSONAL_FACT_GUARD', 'false').lower() == 'true'
        )
        
        # 初始化组件
        self.ai_client = AIClient(self.ai_config)
        self.knowledge_base = KnowledgeBase(str(Path(config_file).resolve().parent / setting('KNOWLEDGE_BASE_PATH', 'datas/knowledge_base.json')))
        self.blacklist = Blacklist(str(Path(config_file).resolve().parent / setting('BLACKLIST_FILE', 'datas/blacklist.txt')))
        self.logger = ReplyLogger(
            str(Path(config_file).resolve().parent / setting('LOG_FILE', 'datas/reply_log.txt')),
            int(setting('LOG_KEEP_DAYS', '30')))
        
        # 线程池
        self.executor = ThreadPoolExecutor(max_workers=int(setting('MAX_CONCURRENT', '10')))
        
        # 系统提示词
        self.system_prompt = setting('SYSTEM_PROMPT', 
            '你是一个智能客服助手，请用友好、专业的态度回复用户的问题。'
            '如果不确定答案，请诚实地告诉用户你会转人工处理。'
            '保持回答简洁明了，不超过200字。')
        
        # 配置项
        self.min_delay = int(setting('MIN_REPLY_DELAY', '2'))
        self.max_delay = int(setting('MAX_REPLY_DELAY', '8'))
        self.max_retry = int(setting('MAX_RETRY', '3'))
        self.retry_delay = int(setting('RETRY_DELAY', '5'))
        self.auto_reply_enabled = setting('AUTO_REPLY_ENABLED', 'true').lower() == 'true'
        self.knowledge_first = setting('KNOWLEDGE_FIRST', 'false').lower() == 'true'
        self.ai_fallback = setting('AI_FALLBACK', 'true').lower() == 'true'
        
        safe_print("=" * 60)
        safe_print("🤖 AI自动回复系统初始化完成！")
        safe_print("=" * 60)
        safe_print(f"AI服务商: {self.ai_config.provider}")
        safe_print(f"API地址: {self.ai_config.base_url}")
        safe_print(f"模型: {self.ai_config.model}")
        safe_print(f"自动回复: {'启用' if self.auto_reply_enabled else '禁用'}")
        safe_print(f"知识库优先: {'是' if self.knowledge_first else '否'}")
        safe_print(f"AI降级: {'启用' if self.ai_fallback else '禁用（纯知识库模式）'}")
        safe_print(f"API Key: {'已配置' if self.ai_config.api_key else '未配置'}")
        safe_print(f"并发数: {setting('MAX_CONCURRENT', '10')}")
        safe_print("=" * 60)
    
    def test_ai_connection(self) -> bool:
        """测试 AI API 是否可用"""
        if self.ai_config.requires_api_key and not self.ai_config.api_key:
            safe_print("❌ 未配置 API Key")
            return False
        reply = self.ai_client.chat("你好", user_id="__api_test__", system_prompt="请用一句话回复", record=False)
        if reply:
            safe_print(f"✅ AI 连接测试成功: {reply[:50]}")
            return True
        safe_print("❌ AI 连接测试失败，请检查服务是否启动及配置是否正确")
        return False
    
    def process_message(self, message: Message) -> Optional[str]:
        """处理单条消息"""
        # 检查黑名单
        if self.blacklist.is_blocked(message.sender):
            self.logger.log("INFO", "用户在黑名单中，跳过", user_id=message.sender)
            return None
        
        # 检查自动回复是否启用
        if not self.auto_reply_enabled:
            self.logger.log("INFO", "自动回复已禁用，跳过", user_id=message.sender)
            return None

        # Knowledge replies and AI replies share the same incoming context.
        # Outgoing text is recorded separately, after send/echo confirmation.
        conversation_key = message.conversation_id or message.sender
        self.ai_client.remember(conversation_key, 'user', message.content)
        
        # 知识库优先模式
        if self.knowledge_first:
            kb_reply = self.knowledge_base.find_match(message.content)
            if kb_reply:
                self.logger.log("INFO", "知识库命中", user_id=message.sender, 
                             content=message.content, reply=kb_reply)
                return kb_reply
            
            if not self.ai_fallback:
                self.logger.log("INFO", "知识库未命中且关闭AI降级，跳过", user_id=message.sender)
                return None
        
        # 调用AI
        for attempt in range(self.max_retry):
            try:
                self.logger.log("INFO", "调用AI", user_id=message.sender, 
                             content=message.content, attempt=attempt + 1)
                
                reply = self.ai_client.chat(
                    message=message.content,
                    user_id=conversation_key,
                    system_prompt=self.system_prompt,
                    record=False
                )
                
                if reply:
                    self.logger.log("INFO", "AI回复成功", user_id=message.sender, reply=reply)
                    return reply
                
                self.logger.log("WARNING", "AI未返回有效回复", user_id=message.sender,
                             attempt=attempt + 1)
                
            except Exception as e:
                self.logger.log("ERROR", "AI调用失败", user_id=message.sender, 
                             error=str(e), attempt=attempt + 1)
                if attempt < self.max_retry - 1:
                    time.sleep(self.retry_delay)
        
        # 所有重试都失败
        return None
    
    def auto_reply_with_delay(self, message: Message) -> Optional[str]:
        """带延迟的自动回复"""
        # 模拟人工回复延迟
        delay = random.uniform(self.min_delay, self.max_delay)
        safe_print(f"⏱️  延迟 {delay:.1f} 秒后回复...")
        time.sleep(delay)
        
        return self.process_message(message)
    
    def handle_received_message(self, sender: str, content: str, conversation_id: str):
        """处理接收到的消息"""
        message = Message(
            sender=sender,
            content=content,
            conversation_id=conversation_id
        )
        
        safe_print(f"\n📩 收到消息 from {sender}: {content}")
        
        # 提交到线程池处理
        future = self.executor.submit(self.auto_reply_with_delay, message)
        return future

# 主程序入口
if __name__ == '__main__':
    safe_print("=" * 60)
    safe_print("🚀 AI自动回复系统")
    safe_print("=" * 60)
    
    # 初始化系统
    system = AutoReplySystem()
    
    # 测试AI连接
    safe_print("\n🧪 测试AI连接...")
    test_reply = system.ai_client.chat("你好", user_id="test")
    safe_print(f"AI回复: {test_reply}")
    
    safe_print("\n" + "=" * 60)
    safe_print("✅ 系统初始化完成！")
    safe_print("=" * 60)
    safe_print("\n使用方法：")
    safe_print("1. 配置 config_ai.env 中的 API 密钥")
    safe_print("2. 运行 抖音私信助手_整合版.py")
    safe_print("3. 修改知识库 datas/knowledge_base.json")
    safe_print("\n或直接运行此文件进行测试")
