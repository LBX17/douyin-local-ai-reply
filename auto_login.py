#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Open the official Douyin page; the user completes QR/phone login manually."""
import argparse
import asyncio
import json
import os
import re
import tempfile
import time
from pathlib import Path

from dotenv import set_key
from playwright.async_api import async_playwright, Error as PlaywrightError

from login_session import LOGIN_TIMEOUT_SECONDS, has_session_cookie, profile_for_account

BASE_DIR = Path(__file__).resolve().parent


class AutoLogin:
    def __init__(self, profile_dir=None, env_path=None, timeout=LOGIN_TIMEOUT_SECONDS,
                 poll_interval=1.0, force_login=False):
        self.profile_dir = Path(profile_dir or profile_for_account()).resolve()
        self.env_path = Path(env_path or BASE_DIR / '.env').resolve()
        self.state_path = self.profile_dir / 'assistant-auth.json'
        self.timeout = float(timeout)
        self.poll_interval = poll_interval
        self.force_login = force_login
        self.playwright = self.browser = self.context = self.page = None
        self.cookies = []
        self.web_protect = self.keys = ''
        self.login_success = False
        self.browser_closed = False
        self.exit_code = 1

    def log(self, message):
        print(message, flush=True)

    async def init_browser(self, headless=False):
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.playwright = await async_playwright().start()
        self.context = await self.playwright.chromium.launch_persistent_context(
            str(self.profile_dir), headless=headless,
            executable_path=os.getenv('DOUYIN_BROWSER_PATH') or None,
            viewport={'width': 1280, 'height': 800},
        )
        self.browser = self.context.browser
        self.context.on('close', lambda _: setattr(self, 'browser_closed', True))
        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
        self.page.set_default_timeout(10000)
        if self.force_login:
            # Only this assistant's dedicated account profile is affected.
            await self.context.clear_cookies()
            self.state_path.unlink(missing_ok=True)
            self.log('🔑 已清除本次账号浏览器的旧登录状态，请重新扫码。')
        elif self.state_path.exists():
            try:
                state = json.loads(self.state_path.read_text('utf-8'))
                cookies = [cookie for cookie in state.get('cookies', [])
                           if (cookie.get('domain') or '').lstrip('.') == 'douyin.com'
                           or (cookie.get('domain') or '').endswith('.douyin.com')]
                if cookies:
                    await self.context.add_cookies(cookies)
            except (ValueError, TypeError, PlaywrightError):
                self.log('⚠️ 已保存的登录状态无法恢复，请在网页重新登录。')

    async def get_all_cookies(self):
        # This is a dedicated profile; export only cookies applicable to Douyin.
        cookies = await self.context.cookies(['https://www.douyin.com/', 'https://sso.douyin.com/'])
        by_name = {c['name']: c['value'] for c in cookies if c['value']}
        return '; '.join(f'{name}={value}' for name, value in by_name.items()), cookies

    async def check_login_status(self):
        cookie_text, _ = await self.get_all_cookies()
        return has_session_cookie(cookie_text)

    async def get_local_storage_data(self, page=None):
        page = page or self.page
        values = await page.evaluate('''() => [
            localStorage.getItem('security-sdk/s_sdk_sign_data_key/web_protect') || '',
            localStorage.getItem('security-sdk/s_sdk_crypt_sdk') || ''
        ]''')
        return values[0], values[1]

    async def collect_parameters(self):
        # A session cookie can arrive before the site's SDK finishes loading.
        # Keep the same browser/context throughout login and parameter reading.
        for _ in range(16):
            if self.browser_closed:
                break
            for page in list(self.context.pages):
                if page.is_closed() or not page.url.startswith('https://www.douyin.com/'):
                    continue
                try:
                    web_protect, keys = await self.get_local_storage_data(page)
                    self.web_protect = web_protect or self.web_protect
                    self.keys = keys or self.keys
                    if self.web_protect and self.keys:
                        return
                except PlaywrightError:
                    pass
            await asyncio.sleep(0.5)

    async def save_to_env(self, cookie_text, web_protect='', keys=''):
        if not has_session_cookie(cookie_text):
            raise ValueError('没有有效 sessionid，未保存登录信息')
        self.env_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix='.login-', suffix='.tmp',
                                                       dir=str(self.env_path.parent))
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            original = self.env_path.read_text('utf-8') if self.env_path.exists() else ''
            temporary.write_text(original, encoding='utf-8')
            # Empty values clear parameters left by a different/older session.
            for name, value in [('DY_COOKIES', cookie_text), ('WEB_PROTECT', web_protect), ('KEYS', keys)]:
                set_key(str(temporary), name, value)
            os.replace(temporary, self.env_path)
        finally:
            temporary.unlink(missing_ok=True)

    async def save_browser_state(self):
        # Chromium may drop session-only cookies on a clean restart. Preserve
        # the same account's browser state explicitly as well as its profile.
        state = await self.context.storage_state()
        descriptor, name = tempfile.mkstemp(prefix='.auth-', suffix='.tmp',
                                            dir=str(self.profile_dir))
        os.close(descriptor)
        temporary = Path(name)
        try:
            temporary.write_text(json.dumps(state, ensure_ascii=False), 'utf-8')
            os.replace(temporary, self.state_path)
        finally:
            temporary.unlink(missing_ok=True)

    async def wait_for_login(self):
        deadline = time.monotonic() + self.timeout
        next_progress = time.monotonic()
        while time.monotonic() < deadline:
            if self.browser_closed or not self.context.pages:
                self.exit_code = 3
                self.log('⚠️ 登录浏览器已关闭，登录未完成。')
                return False
            try:
                cookie_text, cookies = await self.get_all_cookies()
            except PlaywrightError:
                if self.browser_closed:
                    self.exit_code = 3
                    self.log('⚠️ 登录浏览器已关闭，登录未完成。')
                    return False
                raise
            if has_session_cookie(cookie_text):
                self.log('✅ 检测到登录会话，正在保存登录信息…')
                self.cookies = cookies
                await self.collect_parameters()
                await self.save_browser_state()
                await self.save_to_env(cookie_text, self.web_protect, self.keys)
                self.login_success = True
                self.exit_code = 0
                self.log('✅ 登录成功，Cookie 已保存到助手。')
                self.log(f'签名参数：WEB_PROTECT={bool(self.web_protect)}，KEYS={bool(self.keys)}')
                if not (self.web_protect and self.keys):
                    self.log('⚠️ 已保存登录会话，但签名参数尚不完整；发送功能需要另行检查。')
                return True
            now = time.monotonic()
            if now >= next_progress:
                elapsed = int(self.timeout - (deadline - now))
                self.log(f'⏳ 等待你在网页扫码，并在手机确认（{elapsed}秒 / {int(self.timeout)}秒）')
                next_progress = now + 15
            await asyncio.sleep(self.poll_interval)
        self.exit_code = 2
        self.log(f'⚠️ 等待扫码/手机确认超时（{int(self.timeout)}秒）。')
        return False

    async def run(self, headless=False):
        try:
            self.log('🌐 正在打开抖音网页登录窗口…')
            await self.init_browser(headless=headless)
            await self.page.goto('https://www.douyin.com/', wait_until='domcontentloaded', timeout=45000)
            self.log('📱 请在这个浏览器窗口点“登录”，扫描网页二维码，并在手机确认。')
            self.log('💡 确认后会自动检测；请保留这个窗口，无需再次点助手的登录按钮。')
            await self.wait_for_login()
        except Exception as error:
            # Browser errors can contain long call logs/URLs. Keep credentials
            # and tokens out of the GUI and diagnostics.
            detail = str(error).split('Call log:')[0].strip()
            detail = re.sub(r'https?://[^\s\"\']+', '[网页地址]', detail)
            self.log(f'❌ 登录流程失败（{type(error).__name__}）：{detail[:500]}')
            self.exit_code = 3 if self.browser_closed else 1
        finally:
            if self.context and not self.browser_closed:
                await self.context.close()
            if self.playwright:
                await self.playwright.stop()
        return self.exit_code


def main():
    parser = argparse.ArgumentParser(description='在抖音网页中手动扫码，自动保存本地登录状态')
    parser.add_argument('--profile-dir', type=Path)
    parser.add_argument('--env-path', type=Path)
    parser.add_argument('--force-login', action='store_true')
    parser.add_argument('--timeout', type=float, default=LOGIN_TIMEOUT_SECONDS)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error('--timeout must be positive')
    return asyncio.run(AutoLogin(profile_dir=args.profile_dir, env_path=args.env_path,
                                timeout=args.timeout, force_login=args.force_login).run())


if __name__ == '__main__':
    raise SystemExit(main())
