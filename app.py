"""Portable entry point with a process lock to prevent duplicate replies."""
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


class InstanceLock:
    def __init__(self, path):
        self.path = Path(path)
        self.file = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open('a+b')
        if self.path.stat().st_size == 0:
            self.file.write(b'0')
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            self.file.close()
            self.file = None
            return False

    def release(self):
        if self.file:
            self.file.close()
            self.file = None


def main():
    os.chdir(BASE_DIR)
    lock = InstanceLock(BASE_DIR / 'datas' / 'app.lock')
    if not lock.acquire():
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo('助手已打开', '这个安装目录的助手已经运行，请切换到已打开的窗口。')
        root.destroy()
        return
    try:
        from trial_launcher import TrialGUI
        app = TrialGUI()
        app.root.mainloop()
    finally:
        lock.release()


if __name__ == '__main__':
    main()
