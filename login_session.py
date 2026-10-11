"""Local login state and the GUI's single login subprocess controller."""
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

BASE_DIR = Path(__file__).resolve().parent
LOGIN_TIMEOUT_SECONDS = 300


def has_session_cookie(cookie_text):
    for item in (cookie_text or '').split(';'):
        name, separator, value = item.strip().partition('=')
        if separator and name == 'sessionid' and value.strip():
            return True
    return False


@dataclass(repr=False)
class LoginCredentials:
    cookies: str = ''
    web_protect: str = ''
    keys: str = ''

    @property
    def has_session(self):
        return has_session_cookie(self.cookies)


def read_session(env_path):
    values = dotenv_values(env_path) if Path(env_path).exists() else {}
    return LoginCredentials(values.get('DY_COOKIES') or '',
                            values.get('WEB_PROTECT') or '', values.get('KEYS') or '')


def profile_for_account(account_id=None):
    name = re.sub(r'[^a-zA-Z0-9_-]', '_', account_id or 'default')[:64] or 'default'
    return BASE_DIR / 'datas' / 'browser_profiles' / name


@dataclass
class LoginOutcome:
    status: str
    message: str
    log_path: Path
    credentials: LoginCredentials = None


class LoginSessionRunner:
    def __init__(self, project_dir=BASE_DIR, timeout=LOGIN_TIMEOUT_SECONDS):
        self.project_dir = Path(project_dir)
        self.timeout = timeout
        self.process = None

    def run(self, profile_dir, on_log, force_login=False):
        result_root = self.project_dir / 'datas'
        result_root.mkdir(parents=True, exist_ok=True)
        # Each child owns its result; switching accounts cannot replace it.
        with tempfile.TemporaryDirectory(prefix='.login-result-', dir=result_root) as directory:
            return self._run(profile_dir, on_log, Path(directory) / 'session.env', force_login)

    def _run(self, profile_dir, on_log, result_path, force_login):
        # A pythonw parent must use its sibling console interpreter so failures
        # and browser progress reach the GUI rather than disappearing.
        python = Path(sys.executable)
        if python.name.lower() == 'pythonw.exe':
            python = python.with_name('python.exe')
        log_path = self.project_dir / 'datas' / 'login.latest.log'
        log_path.parent.mkdir(parents=True, exist_ok=True)
        command = [str(python), '-X', 'utf8', '-u', str(self.project_dir / 'auto_login.py'),
                   '--profile-dir', str(profile_dir), '--timeout', str(self.timeout),
                   '--env-path', str(result_path)]
        if force_login:
            command.append('--force-login')
        with log_path.open('w', encoding='utf-8') as log:
            self.process = subprocess.Popen(
                command, cwd=str(self.project_dir), stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding='utf-8', errors='replace', bufsize=1,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            )
            lines = queue.Queue()

            def collect_output():
                try:
                    for line in self.process.stdout:
                        lines.put(line.rstrip())
                finally:
                    lines.put(None)

            reader = threading.Thread(target=collect_output, daemon=True)
            reader.start()
            deadline = time.monotonic() + self.timeout + 90
            last_line = ''
            stream_ended = False
            watchdog_expired = False
            while not (stream_ended and self.process.poll() is not None):
                try:
                    line = lines.get(timeout=0.2)
                    if line is None:
                        stream_ended = True
                    elif line:
                        last_line = line
                        log.write(line + '\n')
                        log.flush()
                        on_log(line)
                except queue.Empty:
                    pass
                if time.monotonic() >= deadline and self.process.poll() is None:
                    watchdog_expired = True
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                    break
            code = self.process.wait()
            reader.join(timeout=2)
        credentials = read_session(result_path)
        if watchdog_expired:
            return LoginOutcome('failed', '登录进程长时间无响应，已结束；请查看登录日志。', log_path)
        if code == 0 and credentials.has_session:
            return LoginOutcome('success', '登录会话已保存。', log_path, credentials)
        if code == 2:
            return LoginOutcome('timeout', f'等待扫码/手机确认超时（{self.timeout}秒）。', log_path)
        if code == 3:
            return LoginOutcome('closed', '登录浏览器已关闭，登录未完成。', log_path)
        if code == 0:
            last_line = '进程已结束，但未保存有效登录会话。'
        return LoginOutcome('failed', last_line or f'登录进程退出（代码 {code}）。', log_path)
