"""Local assistant; actual sends require an explicit per-run switch."""

import importlib.util
import json
import os
import threading
from pathlib import Path
import tkinter as tk
from tkinter import messagebox

from ai_auto_reply import AutoReplySystem
from style_samples import StyleSampleStore
from desktop_ui import DesktopUI, C
from app_settings import initialize_local_files

BASE_DIR = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "douyin_gui", BASE_DIR / "抖音私信助手_整合版.py"
)
gui_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gui_module)


class TrialGUI(DesktopUI, gui_module.DouyinGUI):
    def setup_ui(self):
        initialize_local_files()
        self.build_desktop()
        self.log('预览模式已启用。先连接 AI，再扫码登录并开启监听。')
        self.style_status = self.get_style_status()
        self.log("💡 " + self.style_status + "；保存新样本不会自动触发重训。")
        self.preview_ai = None
        self.sample_store = StyleSampleStore(BASE_DIR / 'datas' / 'style_samples.jsonl')
        self.sample_window = None
        self.reply_mode_path = BASE_DIR / 'datas' / 'reply_mode.json'
        # A new session always starts in preview, never automatically sending.
        self.actual_send_enabled = False

    def on_open(self, ws):
        self.ws_connected = True
        return super().on_open(ws)

    def on_close(self, ws, code, message):
        self.ws_connected = False
        return super().on_close(ws, code, message)

    def stop_system(self):
        self.ws_connected = False
        self.starting = False
        return super().stop_system()

    @staticmethod
    def get_style_status():
        return '样本保存在本机，保存不会自动训练模型'

    def change_send_mode(self):
        enabled = self.send_mode.get()
        if enabled and not messagebox.askyesno(
                '启用实际自动回复', '启用后会自动向新收到的一对一私信发送 AI/知识库回复。\n'
                '群聊不回复，之前的预览消息不补发。\n\n确定启用吗？', parent=self.root):
            self.send_mode.set(False)
            return
        self.set_send_mode(enabled)

    def set_send_mode(self, enabled, persist=True):
        if persist:
            try:
                self.reply_mode_path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.reply_mode_path.with_suffix('.tmp')
                temporary.write_text(json.dumps({'actual_send_enabled': bool(enabled)},
                                               ensure_ascii=False), 'utf-8')
                os.replace(temporary, self.reply_mode_path)
            except OSError:
                self.send_mode.set(self.actual_send_enabled)
                self.log('❌ 发送模式无法保存，保留原设置。')
                return
        self.actual_send_enabled = bool(enabled)
        self.send_mode.set(self.actual_send_enabled)
        self.root.title('抖音私信助手 · ' + ('实际自动回复' if enabled else '预览试用'))
        self.reply_mode_label.configure(text=(
            '实际发送已开启，只处理之后的新私信。' if enabled else '预览模式：只显示拟回复，不发送。'))
        self.log('📤 实际自动回复已启用：只发送之后收到的一对一私信回复。' if enabled else
                 '🧪 已切回预览模式：不实际发送。')

    def send_reply(self, conversation_id, conversation_short_id, reply_text,
                   conversation_type=0, send_allowed=False):
        if conversation_type != 1:
            self.log("⏭️ 群聊或未确认的会话不生成拟回复。")
            return
        if getattr(self, 'actual_send_enabled', False) and send_allowed:
            return super().send_reply(conversation_id, conversation_short_id, reply_text,
                                      conversation_type=conversation_type, send_allowed=send_allowed)
        self.log(f"🧪 拟回复（未发送）: {reply_text}")

    def test_local_reply(self):
        if self.sample_window is not None and self.sample_window.winfo_exists():
            self.sample_window.lift()
            return
        window = tk.Toplevel(self.root)
        self.sample_window = window
        window.title('AI 试聊 · 我的风格样本')
        window.geometry('780x600')
        tk.Label(window, text='先试聊，再把答案改成你本人会说的话。这里不会发送消息。',
                 fg='#185b88').pack(anchor='w', padx=16, pady=(14, 8))
        tk.Label(window, text='对方的消息（也可以手写模拟场景）').pack(anchor='w', padx=16)
        incoming = tk.Text(window, height=6, wrap='word', font=('Microsoft YaHei', 11))
        incoming.pack(fill=tk.X, padx=16, pady=6)
        incoming.insert('1.0', '今天有空吗？')
        generate = tk.Button(window, text='让本地模型生成参考回复')
        generate.pack(anchor='w', padx=16, pady=4)
        tk.Label(window, text='你自己的回复（请修改参考答案，或直接手写）').pack(anchor='w', padx=16, pady=(8, 0))
        own_reply = tk.Text(window, height=9, wrap='word', font=('Microsoft YaHei', 11))
        own_reply.pack(fill=tk.BOTH, expand=True, padx=16, pady=6)
        status = tk.StringVar()

        def refresh_count():
            try:
                status.set(f'已保存 {self.sample_store.count()} 组样本 · {self.style_status}')
            except ValueError as error:
                status.set(str(error))

        def finish(reply, error):
            if not window.winfo_exists():
                return
            incoming.configure(state=tk.NORMAL)
            generate.configure(state=tk.NORMAL)
            save.configure(state=tk.NORMAL)
            if reply:
                own_reply.delete('1.0', tk.END)
                own_reply.insert('1.0', reply)
                status.set('参考回复已生成。请改成你自己的话，再保存样本。')
                self.log(f'🧪 本地 AI 参考回复（未发送）: {reply}')
            else:
                status.set(error or '没有收到正文；请检查本地模型服务是否启动。')

        def generate_reply():
            text = incoming.get('1.0', 'end-1c').strip()
            if not text:
                status.set('请先输入对方的消息。')
                return
            incoming.configure(state=tk.DISABLED)
            generate.configure(state=tk.DISABLED)
            save.configure(state=tk.DISABLED)
            status.set('正在生成回复，请稍候…')

            def worker():
                reply, error = None, None
                try:
                    if self.preview_ai is None:
                        self.preview_ai = AutoReplySystem(str(BASE_DIR / 'config_ai.env'))
                    # Each sample is independent, not a continuation of another person's chat.
                    client = self.preview_ai.ai_client
                    with client.session_lock:
                        client.session_history.pop('__style_preview__', None)
                    reply = client.chat(text, '__style_preview__', self.preview_ai.system_prompt, record=False)
                except Exception as exception:
                    error = str(exception)
                try:
                    self.ui_call(lambda: finish(reply, error))
                except (tk.TclError, RuntimeError):
                    pass

            threading.Thread(target=worker, daemon=True).start()

        def save_sample():
            try:
                added, count = self.sample_store.add(
                    incoming.get('1.0', 'end-1c'), own_reply.get('1.0', 'end-1c'))
                status.set(f'{"已保存" if added else "这组已保存过"} · 共 {count} 组 · {self.style_status}；新样本尚未重训')
                self.log(f'📝 训练样本共 {count} 组（仅保存在本机；本次新增样本尚未重训）')
            except (ValueError, OSError) as error:
                messagebox.showerror('保存样本失败', str(error), parent=window)

        save = tk.Button(window, text='这是我会说的话，保存为训练样本', command=save_sample)
        save.pack(anchor='w', padx=16, pady=6)
        generate.configure(command=generate_reply)
        tk.Label(window, textvariable=status, wraplength=740, justify='left').pack(anchor='w', padx=16, pady=(4, 12))
        refresh_count()
        self.theme_window(window)


if __name__ == '__main__':
    from app import main
    main()
