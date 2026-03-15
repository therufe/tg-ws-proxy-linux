from __future__ import annotations

import json
import logging
import os
import sys
import threading
import webbrowser
import psutil
import atexit
import subprocess
from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QLabel,
                             QLineEdit, QCheckBox, QPushButton,
                             QTextEdit, QMessageBox, QSystemTrayIcon, QMenu,
                             QFormLayout)
from PyQt6.QtCore import Qt, pyqtSignal, QObject
from PyQt6.QtGui import QIcon

import proxy.tg_ws_proxy as tg_ws_proxy

APP_NAME = "tgwsproxy"
APP_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP_NAME
CONFIG_FILE = APP_DIR / "config.json"
LOG_FILE = APP_DIR / "proxy.log"

DEFAULT_CONFIG = {
    "port": 1080,
    "host": "127.0.0.1",
    "dc_ip": ["2:149.154.167.220", "4:149.154.167.220"],
    "verbose": False,
}

_config: dict = {}
proxy_error_signal = None
log = logging.getLogger("tgws-tray")

def _setup_logging(verbose: bool):
    _ensure_dirs()
    level = logging.DEBUG if verbose else logging.WARNING
    fh = logging.FileHandler(LOG_FILE, encoding='utf-8', mode='w')
    fmt = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')
    fh.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(fh)

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    root.addHandler(sh)

def resource_path(relative_path):
    base_path = os.path.abspath(os.path.dirname(__file__))
    return os.path.join(base_path, relative_path)

def _ensure_dirs():
    APP_DIR.mkdir(parents=True, exist_ok=True)

def _acquire_lock() -> bool:
    _ensure_dirs()
    lock_file = APP_DIR / f"{os.getpid()}.lock"
    for f in APP_DIR.glob("*.lock"):
        try:
            pid = int(f.stem)
            if psutil.pid_exists(pid):
                return False
            f.unlink()
        except (ValueError, OSError):
            pass
    lock_file.touch()
    atexit.register(lambda: lock_file.unlink(missing_ok=True))
    return True

class SettingsWindow(QWidget):
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("Настройки")
        self.setFixedWidth(400)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowMaximizeButtonHint)

        layout = QVBoxLayout()
        form = QFormLayout()

        self.host_input = QLineEdit(self.config.get("host", "127.0.0.1"))
        self.port_input = QLineEdit(str(self.config.get("port", 1080)))
        form.addRow("IP-адрес:", self.host_input)
        form.addRow("Порт:", self.port_input)

        layout.addLayout(form)
        layout.addWidget(QLabel("DC маппинги (формат DC:IP):"))
        self.dc_edit = QTextEdit("\n".join(self.config.get("dc_ip", [])))
        layout.addWidget(self.dc_edit)

        self.verbose_check = QCheckBox("Подробное логгирование")
        self.verbose_check.setChecked(self.config.get("verbose", False))
        layout.addWidget(self.verbose_check)

        btn_save = QPushButton("Сохранить настройки")
        btn_save.setFixedHeight(40)
        btn_save.clicked.connect(self.save)
        layout.addWidget(btn_save)

        self.setLayout(layout)

    def save(self):
        try:
            port = int(self.port_input.text().strip())

            raw_text = self.dc_edit.toPlainText()
            for char in [',', ';', '\n']:
                raw_text = raw_text.replace(char, ' ')

            lines = [l.strip() for l in raw_text.split() if l.strip()]

            tg_ws_proxy.parse_dc_ip_list(lines)

            new_cfg = {
                "host": self.host_input.text().strip() or "127.0.0.1",
                "port": port,
                "dc_ip": lines,
                "verbose": self.verbose_check.isChecked()
            }
            with open(CONFIG_FILE, "w") as f:
                json.dump(new_cfg, f, indent=2)

            QMessageBox.information(
                self,
                "Настройки сохранены",
                "Изменения успешно записаны.\n\nДля их применения требуется перезапуск."
            )
            self.close()
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Некорректные данные в списке DC:IP - \n{e}")

def start_proxy():
    def target():
        h, p = _config.get("host", "127.0.0.1"), _config.get("port", 1080)
        try:
            raw_ips = _config.get("dc_ip", [])
            flat_ips =[]
            for item in raw_ips:
                flat_ips.extend(item.split())

            dc_opt = tg_ws_proxy.parse_dc_ip_list(flat_ips)
            tg_ws_proxy.run_proxy(p, dc_opt, host=h)
        except Exception as e:
            msg = str(e)
            if "already in use" in msg.lower() or (isinstance(e, OSError) and e.errno == 98):
                msg = f"Порт {p} занят другим приложением"
            log.error(msg)
            if proxy_error_signal: proxy_error_signal.emit(msg)

    threading.Thread(target=target, daemon=True).start()

class TrayApp(QObject):
    error_signal = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)

        global proxy_error_signal
        proxy_error_signal = self.error_signal
        self.error_signal.connect(self.show_error)

        icon_path = resource_path('resources/icon.png')
        tray_path = resource_path('resources/tray.png')
        icon = QIcon(icon_path)
        trayicon = QIcon(tray_path)
        self.app.setWindowIcon(icon)

        self.tray = QSystemTrayIcon(trayicon)
        self.tray.setToolTip("tgwsproxy - работает")

        menu = QMenu()
        a_tg = menu.addAction("Добавить прокси в Telegram")
        a_tg.triggered.connect(self.open_tg)

        a_set = menu.addAction("Настройки прокси")
        a_set.triggered.connect(self.show_settings)

        act_log = menu.addAction("Открыть логи")
        act_log.triggered.connect(self.open_log)

        menu.addSeparator()
        a_exit = menu.addAction("Выход")
        a_exit.triggered.connect(self.app.quit)

        self.tray.setContextMenu(menu)
        self.tray.show()

    def show_error(self, msg):
        QMessageBox.critical(None, "Ошибка прокси", msg)

    def open_tg(self):
        # h = _config.get('host', '127.0.0.1')
        p = _config.get('port', 1080)
        url = f"tg://socks?server=127.0.0.1&port={p}"

        QApplication.clipboard().setText(url)

        try:
            res = subprocess.call(['xdg-open', url], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
            if res != 0:
                raise RuntimeError("xdg-open не смог найти обработчик для ссылки")
        except Exception as e:
            log.warning(f"Не удалось открыть Telegram автоматически: {e}")
            self.tray.showMessage(
                "tgwsproxy",
                f"Не удалось открыть Telegram (вероятно используется Flatpak или Snap версия). Ссылка скопирована в буфер обмена, отправьте её в любой чат Telegram (например, в «Избранное») и нажмите по ней для подключения.",
                QSystemTrayIcon.MessageIcon.Information,
                10000
            )

    def open_log(self):
        if LOG_FILE.exists():
            subprocess.Popen(['xdg-open', str(LOG_FILE)])
        else:
            QMessageBox.information(None, "Ошибка", f"Файл логов отсутствует:\n{LOG_FILE}")

    def show_settings(self):
        self.win = SettingsWindow(_config)
        self.win.show()

    def run(self):
        start_proxy()
        self.tray.showMessage(
            "tgwsproxy",
            f"Прокси запущено. Клик правой кнопкой по иконке, если требуется настройка",
            QSystemTrayIcon.MessageIcon.Information,
            3000
        )
        return self.app.exec()

if __name__ == "__main__":
    if not _acquire_lock():
        app_err = QApplication(sys.argv)
        QMessageBox.critical(None, "Ошибка", "Приложение уже запущено!")
        sys.exit(0)

    try:
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, "r") as f: _config = json.load(f)
        else: _config = DEFAULT_CONFIG
    except: _config = DEFAULT_CONFIG

    _setup_logging(_config.get("verbose", False))

    tray_app = TrayApp()
    sys.exit(tray_app.run())
