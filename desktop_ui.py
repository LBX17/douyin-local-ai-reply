"""Reusable desktop layout and AI onboarding, with no account data bundled."""
import queue
import threading
import time
import tkinter as tk
from tkinter import scrolledtext, ttk
from app_settings import read_settings, read_models, save_settings, validate_settings, BASE_DIR
from ai_auto_reply import AutoReplySystem
from login_session import read_session

C = {'bg': '#020617', 'panel': '#0E1223', 'nav': '#0F172A', 'field': '#1E293B',
     'text': '#F8FAFC', 'muted': '#94A3B8', 'line': '#334155', 'accent': '#22C55E',
     'warning': '#FBBF24', 'error': '#FCA5A5'}


class DesktopUI:
    def label(self, parent, text='', size=10, muted=False, bold=False, **kwargs):
        return tk.Label(parent, text=text, bg=parent.cget('bg'), fg=C['muted' if muted else 'text'],
                        font=('Microsoft YaHei UI', size, 'bold' if bold else 'normal'), **kwargs)

    def button(self, parent, text, command, primary=False):
        return tk.Button(parent, text=text, command=command, relief='flat', cursor='hand2',
            bg=C['accent' if primary else 'field'], fg=C['nav' if primary else 'text'],
            activebackground=C['line'], activeforeground=C['text'], disabledforeground=C['muted'],
            font=('Microsoft YaHei UI', 10), padx=14, pady=10, highlightthickness=1,
            highlightbackground=C['line'], highlightcolor=C['text'], takefocus=True)

    def build_desktop(self):
        self.ui_events = queue.Queue()
        self.ai_busy = self.ai_connected = self.ws_connected = self.starting = False
        self.root.title('抖音私信助手 · 预览模式')
        self.root.geometry('1120x800')
        self.root.minsize(960, 720)
        self.root.configure(bg=C['bg'])
        self.root.option_add('*Font', ('Microsoft YaHei UI', 10))
        self.root.option_add('*TCombobox*Listbox.background', C['field'])
        self.root.option_add('*TCombobox*Listbox.foreground', C['text'])
        style = ttk.Style(self.root)
        style.theme_use('clam')
        style.configure('.', background=C['panel'], foreground=C['text'], fieldbackground=C['field'], bordercolor=C['line'])
        style.configure('TNotebook', background=C['bg'], borderwidth=0)
        style.configure('TNotebook.Tab', padding=(18, 12), background=C['field'])
        style.map('TNotebook.Tab', background=[('selected', C['panel'])], foreground=[('selected', C['accent'])])
        style.map('TCombobox', fieldbackground=[('readonly', C['field'])], foreground=[('readonly', C['text'])])
        nav = tk.Frame(self.root, bg=C['nav'], width=182)
        nav.pack(side=tk.LEFT, fill=tk.Y)
        nav.pack_propagate(False)
        self.label(nav, 'DY / REPLY', size=17, bold=True).pack(anchor='w', padx=20, pady=(28, 4))
        self.label(nav, '让回复更从容', muted=True).pack(anchor='w', padx=20, pady=(0, 32))
        for name, index in [('工作台', 0), ('AI 设置', 1)]:
            self.button(nav, name, lambda i=index: self.tabs.select(i)).pack(fill=tk.X, padx=16, pady=5)
        for name, callback in [('试聊与风格', self.test_local_reply), ('账号管理', self.open_account_manager), ('知识库', self.open_knowledge_base)]:
            self.button(nav, name, callback).pack(fill=tk.X, padx=16, pady=5)
        self.label(nav, '仅一对一私信\n群聊始终跳过', muted=True, justify='left').pack(side=tk.BOTTOM, anchor='w', padx=20, pady=24)
        main = tk.Frame(self.root, bg=C['bg'])
        main.pack(fill=tk.BOTH, expand=True, padx=24, pady=24)
        self.label(main, '私信工作台', size=22, bold=True).pack(anchor='w')
        self.label(main, '先登录 → 连接 AI → 试聊 → 开启监听', muted=True).pack(anchor='w', pady=(6, 20))
        cards = tk.Frame(main, bg=C['bg'])
        cards.pack(fill=tk.X, pady=(0, 18))
        labels = []
        for index, title in enumerate(['抖音账号', 'AI 模型', '私信监听']):
            cards.columnconfigure(index, weight=1, uniform='card')
            card = tk.Frame(cards, bg=C['panel'], highlightthickness=1, highlightbackground=C['line'])
            card.grid(row=0, column=index, sticky='ew', padx=(0 if index == 0 else 8, 0))
            self.label(card, title, muted=True).pack(anchor='w', padx=16, pady=(12, 6))
            label = self.label(card, ['未登录', '未测试', '未开启'][index], size=13, bold=True)
            label.pack(anchor='w', padx=16, pady=(0, 14))
            labels.append(label)
        self.status_label, self.model_label, self.listen_label = labels
        self.label(main, '本机保存登录和聊天数据 · 退出后停止监听', muted=True, size=9).pack(side=tk.BOTTOM, anchor='w', pady=(12, 0))
        self.tabs = ttk.Notebook(main)
        self.tabs.pack(fill=tk.BOTH, expand=True)
        console = tk.Frame(self.tabs, bg=C['panel'])
        settings = tk.Frame(self.tabs, bg=C['panel'])
        self.tabs.add(console, text='消息动态')
        self.tabs.add(settings, text='AI 连接')
        toolbar = tk.Frame(console, bg=C['panel'])
        toolbar.pack(fill=tk.X, padx=16, pady=16)
        self.login_button = self.button(toolbar, '扫码登录', lambda: self.auto_login(force_login=True))
        self.login_button.pack(side=tk.LEFT)
        self.start_button = self.button(toolbar, '开启监听', self.start_system, primary=True)
        self.start_button.pack(side=tk.LEFT, padx=8)
        self.button(toolbar, '停止', self.stop_system).pack(side=tk.LEFT)
        self.button(toolbar, '清空显示', self.clear_log).pack(side=tk.RIGHT)
        mode = tk.Frame(console, bg=C['field'])
        mode.pack(fill=tk.X, padx=16, pady=(0, 12))
        self.send_mode = tk.BooleanVar(value=False)
        tk.Checkbutton(mode, text='实际发送回复', variable=self.send_mode, command=self.change_send_mode,
            bg=C['field'], fg=C['text'], selectcolor=C['nav'], activebackground=C['field'],
            activeforeground=C['text'], padx=12, pady=10).pack(side=tk.LEFT)
        self.reply_mode_label = self.label(mode, '预览模式：只显示拟回复，不发送。', muted=True)
        self.reply_mode_label.pack(side=tk.LEFT, padx=8)
        self.log_area = scrolledtext.ScrolledText(console, height=12, wrap='word', bg=C['bg'], fg=C['text'],
            insertbackground=C['text'], selectbackground=C['line'], relief='flat',
            font=('Microsoft YaHei UI', 10), padx=14, pady=12)
        self.log_area.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 16))
        self.build_ai_settings(settings)
        self.root.bind('<Control-Key-1>', lambda event: self.tabs.select(0))
        self.root.bind('<Control-Key-2>', lambda event: self.tabs.select(1))
        self.root.after(100, self.drain_events)
        self.root.after(500, self.poll_ui)
        self.root.protocol('WM_DELETE_WINDOW', self.close_app)

    def build_ai_settings(self, parent):
        self.settings = read_settings()
        self.form = {}
        footer = tk.Frame(parent, bg=C['panel'])
        footer.pack(side=tk.BOTTOM, fill=tk.X, padx=20, pady=(8, 14))
        content = tk.Frame(parent, bg=C['panel'])
        content.pack(fill=tk.BOTH, expand=True, padx=20, pady=(16, 0))
        canvas = tk.Canvas(content, bg=C['panel'], highlightthickness=0)
        scrollbar = ttk.Scrollbar(content, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        box = tk.Frame(canvas, bg=C['panel'])
        item = canvas.create_window((0, 0), window=box, anchor='nw')
        box.bind('<Configure>', lambda event: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda event: canvas.itemconfigure(item, width=event.width))

        def scroll_form(event):
            widget = event.widget
            while widget is not None:
                if widget is box:
                    canvas.yview_scroll(-int(event.delta / 120), 'units')
                    return 'break'
                widget = getattr(widget, 'master', None)
        self.root.bind('<MouseWheel>', scroll_form, add='+')

        def reveal_field(event):
            widget = event.widget
            top = canvas.canvasy(0)
            bottom = top + canvas.winfo_height()
            y = widget.winfo_rooty() - box.winfo_rooty()
            height = widget.winfo_height()
            if y < top:
                canvas.yview_moveto(y / max(1, box.winfo_height()))
            elif y + height > bottom:
                canvas.yview_moveto((y + height - canvas.winfo_height()) / max(1, box.winfo_height()))

        box.columnconfigure(1, weight=1)
        for row, (name, key) in enumerate([('接口类型', 'AI_PROVIDER'), ('API 根地址', 'AI_BASE_URL'),
                ('模型名称', 'AI_MODEL'), ('API Key（本机可留空）', 'AI_API_KEY'), ('生成上限 / tokens', 'MAX_TOKENS')]):
            self.label(box, name).grid(row=row, column=0, sticky='w', padx=(0, 14), pady=5)
            value = tk.StringVar(value=self.settings[key])
            self.form[key] = value
            if key in {'AI_PROVIDER', 'AI_MODEL'}:
                widget = ttk.Combobox(box, textvariable=value, values=['openai', 'ollama', 'lm_studio', 'llama_cpp', 'anthropic'] if key == 'AI_PROVIDER' else [], state='readonly' if key == 'AI_PROVIDER' else 'normal')
                if key == 'AI_MODEL':
                    self.model_combo = widget
            else:
                widget = tk.Entry(box, textvariable=value, bg=C['field'], fg=C['text'], insertbackground=C['text'], relief='flat', show='•' if key == 'AI_API_KEY' else '')
            widget.grid(row=row, column=1, sticky='ew', ipady=4, pady=4)
            widget.bind('<FocusIn>', reveal_field, add='+')
        self.form['AI_PROVIDER'].trace_add('write', self.provider_changed)
        self.label(box, 'Ollama: 127.0.0.1:11434/v1   ·   LM Studio: 127.0.0.1:1234/v1', muted=True, size=9).grid(row=5, column=0, columnspan=2, sticky='w', pady=(4, 10))
        self.label(box, '回复风格与规则').grid(row=6, column=0, sticky='nw', pady=6)
        self.prompt_text = scrolledtext.ScrolledText(box, height=5, wrap='word', bg=C['field'], fg=C['text'], insertbackground=C['text'], relief='flat', padx=8, pady=8)
        self.prompt_text.insert('1.0', self.settings['SYSTEM_PROMPT'])
        self.prompt_text.grid(row=6, column=1, sticky='nsew', pady=6)
        self.prompt_text.bind('<FocusIn>', reveal_field, add='+')
        self.thinking = tk.BooleanVar(value=self.settings['AI_THINKING'] == 'true')
        tk.Checkbutton(box, text='开启模型思考（仅 llama.cpp 扩展）', variable=self.thinking,
            bg=C['panel'], fg=C['text'], selectcolor=C['nav'], activebackground=C['panel'], activeforeground=C['text']).grid(row=7, column=0, columnspan=2, sticky='w', pady=6)
        actions = tk.Frame(footer, bg=C['panel'])
        actions.pack(fill=tk.X)
        self.ai_buttons = []
        for name, callback, primary in [('读取模型列表', self.fetch_models, False), ('保存配置', self.save_ai_settings, False), ('测试 AI 连接', self.test_ai, True)]:
            button = self.button(actions, name, callback, primary)
            button.pack(side=tk.LEFT, padx=(0, 8))
            self.ai_buttons.append(button)
        self.feedback = tk.StringVar(value='云端 AI 会收到私信内容；本机模型无需购买 API。')
        self.label(footer, textvariable=self.feedback, muted=True, size=9, wraplength=620, justify='left').pack(anchor='w', pady=(8, 0))

    def provider_changed(self, *_):
        urls = {'ollama': 'http://127.0.0.1:11434/v1', 'lm_studio': 'http://127.0.0.1:1234/v1', 'llama_cpp': 'http://127.0.0.1:8080/v1', 'openai': 'http://127.0.0.1:8080/v1'}
        provider = self.form['AI_PROVIDER'].get()
        if provider in urls:
            self.form['AI_BASE_URL'].set(urls[provider])
        self.ai_connected = False

    def form_values(self, require_model=True):
        values = {**self.settings, **{key: field.get().strip() for key, field in self.form.items()}}
        values['SYSTEM_PROMPT'] = self.prompt_text.get('1.0', 'end-1c').strip()
        values['AI_THINKING'] = str(self.thinking.get()).lower()
        return validate_settings(values, require_model=require_model)

    def save_ai_settings(self):
        if self.running:
            self.feedback.set('请先停止监听，再保存新配置。')
            return False
        try:
            self.settings = self.form_values()
            save_settings(self.settings)
            self.preview_ai = None
            self.ai_connected = False
            self.feedback.set('配置已保存，请测试 AI 连接。')
            return True
        except (ValueError, OSError) as error:
            self.feedback.set(str(error))
            return False

    def background(self, operation, finish):
        if self.ai_busy:
            return
        self.ai_busy = True
        self.feedback.set('正在连接模型，请稍候…')
        for button in self.ai_buttons:
            button.configure(state=tk.DISABLED)
        def complete(value, error):
            self.ai_busy = False
            for button in self.ai_buttons:
                button.configure(state=tk.NORMAL)
            finish(value, error)
        def worker():
            try:
                value, error = operation(), None
            except Exception as exception:
                value, error = None, str(exception) if isinstance(exception, ValueError) else '连接失败，请检查模型服务、地址和密钥。'
            self.ui_events.put(lambda: complete(value, error))
        threading.Thread(target=worker, daemon=True).start()

    def fetch_models(self):
        try:
            values = self.form_values(require_model=False)
        except ValueError as error:
            self.feedback.set(str(error))
            return
        def finish(models, error):
            if error:
                self.feedback.set(error)
            else:
                self.model_combo.configure(values=models)
                if self.form['AI_MODEL'].get() not in models:
                    self.form['AI_MODEL'].set(models[0])
                self.feedback.set(f'读取到 {len(models)} 个模型。选择后保存配置，再测试连接。')
        self.background(lambda: read_models(values), finish)

    def test_ai(self):
        if not self.save_ai_settings():
            return
        def operation():
            system = AutoReplySystem(str(BASE_DIR / 'config_ai.env'))
            try:
                reply = system.ai_client.chat('请简短回复：你好', '__api_test__', system.system_prompt, record=False)
                if not reply:
                    raise ValueError('未收到完整回复，请检查模型名称、密钥和生成上限。')
                return reply
            finally:
                system.executor.shutdown(wait=False)
        def finish(reply, error):
            self.ai_connected = not bool(error)
            self.feedback.set(error or '连接成功，模型回复：' + reply)
        self.background(operation, finish)

    def ui_call(self, callback):
        self.ui_events.put(callback)

    def drain_events(self):
        for _ in range(100):
            try:
                self.ui_events.get_nowait()()
            except queue.Empty:
                break
        self.root.after(100, self.drain_events)

    def poll_ui(self):
        self.listen_label.configure(text='已连接' if self.ws_connected else ('连接中…' if self.running or self.starting else '未开启'), fg=C['accent' if self.ws_connected else 'muted'])
        self.model_label.configure(text='已通过测试' if self.ai_connected else '未测试', fg=C['accent' if self.ai_connected else 'muted'])
        self.start_button.configure(state=tk.DISABLED if self.running or self.starting or self.login_in_progress else tk.NORMAL)
        self.root.after(500, self.poll_ui)

    def close_app(self):
        self.stop_system()
        self.reply_executor.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()

    def log(self, message):
        def append():
            self.log_area.configure(state=tk.NORMAL)
            self.log_area.insert(tk.END, f'[{time.strftime("%H:%M:%S")}] {message}\n')
            if int(self.log_area.index('end-1c').split('.')[0]) > 2000:
                self.log_area.delete('1.0', '100.0')
            self.log_area.see(tk.END)
            self.log_area.configure(state=tk.DISABLED)
        self.ui_events.put(append)

    def clear_log(self):
        self.log_area.configure(state=tk.NORMAL)
        self.log_area.delete('1.0', tk.END)
        self.log_area.configure(state=tk.DISABLED)

    def start_system(self):
        if self.running or self.starting or self.login_in_progress:
            return
        if not read_session(BASE_DIR / '.env').has_session:
            self.log('请先扫码登录。')
            return
        try:
            validate_settings(read_settings())
        except ValueError as error:
            self.log(str(error))
            self.tabs.select(1)
            return
        self.starting = True
        super().start_system()

    def run_system(self):
        try:
            super().run_system()
        finally:
            self.starting = False
            self.ws_connected = False

    def theme_window(self, widget):
        if isinstance(widget, (tk.Frame, tk.Label, tk.Toplevel, tk.Checkbutton)):
            widget.configure(bg=C['panel'])
            if isinstance(widget, (tk.Label, tk.Checkbutton)):
                widget.configure(fg=C['text'])
        elif isinstance(widget, (tk.Text, tk.Entry, tk.Listbox)):
            widget.configure(bg=C['field'], fg=C['text'], insertbackground=C['text'], selectbackground=C['line'])
        elif isinstance(widget, tk.Button):
            widget.configure(bg=C['field'], fg=C['text'], activebackground=C['line'], activeforeground=C['text'], relief='flat', padx=12, pady=8)
        for child in widget.winfo_children():
            self.theme_window(child)
