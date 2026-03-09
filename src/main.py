from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
import webbrowser
import psutil
from pathlib import Path
from typing import Dict, Optional

from PyQt6 import QtWidgets, QtCore, QtGui
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QLabel,
                             QLineEdit, QCheckBox, QPushButton, QHBoxLayout,
                             QTextEdit, QMessageBox, QSystemTrayIcon, QMenu,
                             QFormLayout)
from PyQt6.QtCore import Qt, QSize, pyqtSignal, QObject
from PyQt6.QtGui import QIcon, QAction

import proxy.tg_ws_proxy as tg_ws_proxy

APP_NAME = "tgwsproxy"
APP_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP_NAME
CONFIG_FILE = APP_DIR / "config.json"
LOG_FILE = APP_DIR / "proxy.log"
FIRST_RUN_MARKER = APP_DIR / ".wasfirstrund"

DEFAULT_CONFIG = {
    "port": 1080,
    "host": "127.0.0.1",
    "dc_ip": ["2:149.154.167.220", "4:149.154.167.220"],
    "verbose": False,
}

_proxy_thread: Optional[threading.Thread] = None
_async_stop: Optional[object] = None
_config: dict = {}
log = logging.getLogger("tg-ws-tray")

def resource_path(relative_path):
    base_path = os.path.abspath(os.path.dirname(__file__))
    return os.path.join(base_path, relative_path)

def _load_icon():
    icon_path = resource_path("resources/icon.png")

    log.info(f"Trying to load icon from: {icon_path}")

    if icon_path.exists():
        try:
            from PIL import Image
            return Image.open(str(icon_path))
        except Exception as e:
            log.error(f"Failed to load icon image: {e}")

    log.warning("Icon file not found, using generated icon")
    return _make_icon_image()

def _ensure_dirs():
    APP_DIR.mkdir(parents=True, exist_ok=True)

def _acquire_lock() -> bool:
    _ensure_dirs()
    lock_file = APP_DIR / f"{os.getpid()}.lock"
    # проверяем наличие .lock файлов
    for f in APP_DIR.glob("*.lock"):
        if f != lock_file and f.exists():
            try:
                pid = int(f.stem)
                if psutil.pid_exists(pid): return False
                f.unlink()
            except: pass
    lock_file.touch()
    return True

class SettingsWindow(QWidget):
    def __init__(self, config, callback):
        super().__init__()
        self.config = config
        self.callback = callback
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("Настройки")
        self.setFixedWidth(400)
        layout = QVBoxLayout()

        form = QFormLayout()
        self.host_input = QLineEdit(self.config.get("host", "127.0.0.1"))
        self.port_input = QLineEdit(str(self.config.get("port", 1080)))
        form.addRow("IP-адрес:", self.host_input)
        form.addRow("Порт:", self.port_input)

        layout.addLayout(form)
        layout.addWidget(QLabel("DC маппинги (DC:IP):"))
        self.dc_edit = QTextEdit("\n".join(self.config.get("dc_ip", [])))
        layout.addWidget(self.dc_edit)

        self.verbose_check = QCheckBox("Подробное логгирование")
        self.verbose_check.setChecked(self.config.get("verbose", False))
        layout.addWidget(self.verbose_check)

        btn_save = QPushButton("Сохранить и перезапустить")
        btn_save.clicked.connect(self.save)
        layout.addWidget(btn_save)

        self.setLayout(layout)

    def save(self):
        new_cfg = {
            "host": self.host_input.text(),
            "port": int(self.port_input.text()),
            "dc_ip": self.dc_edit.toPlainText().splitlines(),
            "verbose": self.verbose_check.isChecked()
        }
        with open(CONFIG_FILE, "w") as f:
            json.dump(new_cfg, f)
        self.callback()
        self.close()

def start_proxy():
    global _proxy_thread
    cfg = _config
    _proxy_thread = threading.Thread(target=lambda: tg_ws_proxy.run_proxy(
        cfg["port"], tg_ws_proxy.parse_dc_ip_list(cfg["dc_ip"]), host=cfg["host"]), daemon=True)
    _proxy_thread.start()

class TrayApp(QObject):
    def __init__(self):
        super().__init__()
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)

        icon_path = resource_path('resources/icon.png')

        self.app.setWindowIcon(QIcon(icon_path))
        self.tray = QSystemTrayIcon(QIcon(icon_path))
        self.tray.setToolTip("tgwsproxy")
        menu = QMenu()

        open_action = QAction("Добавить прокси в Telegram", self.app)
        open_action.triggered.connect(self.open_tg)
        menu.addAction(open_action)

        settings_action = QAction("Настройки", self.app)
        settings_action.triggered.connect(self.show_settings)
        menu.addAction(settings_action)

        exit_action = QAction("Выход", self.app)
        exit_action.triggered.connect(self.app.quit)
        menu.addAction(exit_action)

        self.tray.setContextMenu(menu)
        self.tray.show()

    def open_tg(self):
        webbrowser.open(f"tg://socks?server={_config['host']}&port={_config['port']}")

    def show_settings(self):
        self.win = SettingsWindow(_config, lambda: os.execv(sys.executable, ['python'] + sys.argv))
        self.win.show()

    def run(self):
        start_proxy()
        sys.exit(self.app.exec())

if __name__ == "__main__":
    if not _acquire_lock(): sys.exit(0)
    _ensure_dirs()
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r") as f: _config = json.load(f)
    else: _config = DEFAULT_CONFIG

    TrayApp().run()
