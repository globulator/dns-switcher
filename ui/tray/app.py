#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DNS Switcher - Cross-platform Desktop System Tray Application.
Uses core.engine and platform network adapters with zero duplicated logic.
"""

import os
import sys
import webbrowser

# Ensure project root is in sys.path
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Qt import abstraction (supports PyQt6 and PySide6)
try:
    from PyQt6 import QtCore, QtGui, QtWidgets
    from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QPoint, QSize, QRect
    from PyQt6.QtGui import QIcon, QColor, QPainter, QBrush, QPen, QFont, QCursor, QPixmap, QGuiApplication
    from PyQt6.QtWidgets import (
        QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
        QPushButton, QLabel, QScrollArea, QFrame, QSystemTrayIcon,
        QMenu, QMessageBox, QGraphicsDropShadowEffect, QSizePolicy
    )
except ImportError:
    try:
        from PySide6 import QtCore, QtGui, QtWidgets
        from PySide6.QtCore import Qt, QThread, Signal as pyqtSignal, QTimer, QPoint, QSize, QRect
        from PySide6.QtGui import QIcon, QColor, QPainter, QBrush, QPen, QFont, QCursor, QPixmap, QGuiApplication
        from PySide6.QtWidgets import (
            QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
            QPushButton, QLabel, QScrollArea, QFrame, QSystemTrayIcon,
            QMenu, QMessageBox, QGraphicsDropShadowEffect, QSizePolicy
        )
    except ImportError:
        print("Ошибка: Для работы трей-приложения требуется PyQt6 или PySide6.")
        print("Установите: pip install PyQt6")
        sys.exit(1)

from core.storage import (
    load_presets,
    load_dns_list,
    load_targets_list,
    get_active_target,
    set_active_target,
    save_targets_list,
    normalize_host,
    load_cached_latencies,
    add_dns,
    remove_dns,
    DEFAULT_TARGETS
)
from core.engine import probe_all, probe_domain
from core.adapter import get_adapter
from ui.tray import updater

DONATE_URL = "https://boosty.to/globulator/donate"

STYLE_SHEET = """
QWidget#MainWindow {
    background-color: #242424;
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 14px;
}

QLineEdit#SearchInput {
    background-color: rgba(255, 255, 255, 0.08);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 17px;
    padding: 6px 14px;
    color: #ffffff;
    font-size: 13px;
    selection-background-color: #3584e4;
}
QLineEdit#SearchInput:focus {
    border: 1px solid rgba(53, 132, 228, 0.7);
    background-color: rgba(255, 255, 255, 0.12);
}

QPushButton.IconButton {
    background-color: rgba(255, 255, 255, 0.08);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 16px;
    color: #ffffff;
    font-size: 14px;
    font-weight: bold;
}
QPushButton.IconButton:hover {
    background-color: rgba(255, 255, 255, 0.18);
    border-color: rgba(255, 255, 255, 0.25);
}

QFrame#TabsContainer {
    background-color: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.07);
    border-radius: 12px;
}

QPushButton.TabButton {
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 9px;
    color: rgba(255, 255, 255, 0.6);
    font-size: 12px;
    font-weight: 500;
    padding: 4px 6px;
}
QPushButton.TabButton:hover {
    color: #ffffff;
    background-color: rgba(255, 255, 255, 0.1);
}
QPushButton.TabButton.ActiveTab {
    color: #ffffff;
    background-color: rgba(53, 132, 228, 0.35);
    border: 1px solid rgba(53, 132, 228, 0.75);
}

QScrollArea {
    background: transparent;
    border: none;
}
QWidget#ScrollContent {
    background: transparent;
}

QFrame.DnsRow {
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 10px;
    padding: 3px 6px;
}
QFrame.DnsRow:hover {
    background-color: rgba(255, 255, 255, 0.08);
}
QFrame.DnsRow.ActiveRow {
    background-color: rgba(255, 255, 255, 0.16);
    border: 1px solid rgba(255, 255, 255, 0.22);
}
QFrame.DnsRow.ActiveRow:hover {
    background-color: rgba(255, 255, 255, 0.20);
}

QLabel.DomainTitle {
    color: #ffffff;
    font-size: 13px;
}
QLabel.DomainTitle.ActiveTitle {
    font-weight: 600;
}

QLabel.BadgeUDP {
    font-size: 10px;
    color: rgba(255, 255, 255, 0.45);
    background-color: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 5px;
    padding: 1px 4px;
}
QLabel.BadgeDoT {
    font-size: 10px;
    font-weight: bold;
    color: #78aeed;
    background-color: rgba(53, 132, 228, 0.2);
    border: 1px solid rgba(53, 132, 228, 0.45);
    border-radius: 5px;
    padding: 1px 4px;
}
QLabel.BadgeDoH {
    font-size: 10px;
    font-weight: bold;
    color: #e5a50a;
    background-color: rgba(229, 165, 10, 0.18);
    border: 1px solid rgba(229, 165, 10, 0.45);
    border-radius: 5px;
    padding: 1px 4px;
}

QLabel.LatencyOk {
    font-size: 12px;
    font-weight: 600;
    color: #33d17a;
}
QLabel.LatencyError {
    font-size: 12px;
    color: #f66151;
}
QLabel.LatencyChecking {
    font-size: 13px;
    font-weight: bold;
    color: rgba(255, 255, 255, 0.45);
}

QPushButton.TrashButton {
    background: transparent;
    border: none;
    border-radius: 6px;
    color: rgba(255, 255, 255, 0.45);
    font-size: 12px;
}
QPushButton.TrashButton:hover {
    color: #f66151;
    background-color: rgba(255, 255, 255, 0.12);
}

QFrame#BottomBar {
    border-top: 1px solid rgba(255, 255, 255, 0.08);
    padding-top: 6px;
}

QPushButton.BottomBtn {
    background-color: rgba(255, 255, 255, 0.08);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 15px;
    color: #ffffff;
    font-size: 13px;
}
QPushButton.BottomBtn:hover {
    background-color: rgba(255, 255, 255, 0.18);
}
QPushButton#TargetBtn {
    font-size: 12px;
    color: rgba(255, 255, 255, 0.85);
    padding: 4px 10px;
}

QScrollBar:vertical {
    border: none;
    background: transparent;
    width: 6px;
    margin: 0px;
}
QScrollBar::handle:vertical {
    background: rgba(255, 255, 255, 0.2);
    min-height: 25px;
    border-radius: 3px;
}
QScrollBar::handle:vertical:hover {
    background: rgba(255, 255, 255, 0.35);
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

QFrame#UpdateBanner {
    background-color: rgba(53, 132, 228, 0.25);
    border: 1px solid rgba(53, 132, 228, 0.5);
    border-radius: 8px;
    padding: 6px;
    margin-bottom: 6px;
}
"""

def generate_app_icon():
    pix = QPixmap(64, 64)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QBrush(QColor(53, 132, 228)))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(4, 4, 56, 56)
    p.setPen(QPen(QColor(255, 255, 255), 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawEllipse(18, 18, 28, 28)
    p.drawLine(18, 32, 46, 32)
    p.drawLine(32, 18, 32, 46)
    p.end()
    return QIcon(pix)

class ProbeWorker(QThread):
    result_signal = pyqtSignal(dict)
    finished_signal = pyqtSignal()

    def __init__(self, target):
        super().__init__()
        self.target = target

    def run(self):
        probe_all(target=self.target, callback=self.result_signal.emit)
        self.finished_signal.emit()

class SingleProbeWorker(QThread):
    result_signal = pyqtSignal(dict)

    def __init__(self, domain, target):
        super().__init__()
        self.domain = domain
        self.target = target

    def run(self):
        res = probe_domain(self.domain, self.target)
        self.result_signal.emit(res)

class ApplyWorker(QThread):
    done_signal = pyqtSignal(dict)

    def __init__(self, domain):
        super().__init__()
        self.domain = domain

    def run(self):
        adapter = get_adapter()
        res = adapter.apply_dns(self.domain)
        self.done_signal.emit(res)

class UpdateCheckWorker(QThread):
    update_signal = pyqtSignal(dict)

    def run(self):
        info = updater.check_for_updates()
        if info.get("update_available"):
            self.update_signal.emit(info)

class TargetsModal(QFrame):
    target_changed = pyqtSignal(str)
    close_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("TargetsModal")
        self.setStyleSheet("""
            QFrame#TargetsModal {
                background-color: #242424;
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 14px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        hdr = QHBoxLayout()
        title = QLabel("Цели проверки задержки")
        title.setStyleSheet("font-size: 14px; font-weight: bold; color: #ffffff;")
        hdr.addWidget(title)
        hdr.addStretch()

        btn_close = QPushButton("✕")
        btn_close.setFixedSize(26, 26)
        btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_close.setStyleSheet("background: transparent; color: #888; font-size: 14px; border: none;")
        btn_close.clicked.connect(self.close_requested.emit)
        hdr.addWidget(btn_close)
        layout.addLayout(hdr)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll_content = QWidget()
        self.targets_layout = QVBoxLayout(self.scroll_content)
        self.targets_layout.setContentsMargins(0, 0, 0, 0)
        self.targets_layout.setSpacing(4)
        self.scroll.setWidget(self.scroll_content)
        layout.addWidget(self.scroll)

        add_box = QHBoxLayout()
        self.add_input = QLineEdit()
        self.add_input.setPlaceholderText("Добавить цель (напр. rutracker.org)...")
        self.add_input.setObjectName("SearchInput")
        self.add_input.returnPressed.connect(self._on_add_target)
        add_box.addWidget(self.add_input)

        btn_add = QPushButton("✔")
        btn_add.setFixedSize(32, 32)
        btn_add.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_add.setObjectName("IconButton")
        btn_add.clicked.connect(self._on_add_target)
        add_box.addWidget(btn_add)
        layout.addLayout(add_box)

        self.refresh_targets()

    def refresh_targets(self):
        while self.targets_layout.count():
            item = self.targets_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        targets = load_targets_list()
        active = get_active_target()

        for t in targets:
            row = QFrame()
            row.setObjectName("TargetRow")
            row.setStyleSheet("""
                QFrame#TargetRow {
                    background-color: rgba(255, 255, 255, 0.05);
                    border-radius: 8px;
                    padding: 4px;
                }
                QFrame#TargetRow:hover {
                    background-color: rgba(255, 255, 255, 0.1);
                }
            """)
            rl = QHBoxLayout(row)
            rl.setContentsMargins(8, 4, 8, 4)

            is_active = (t == active)
            dot = QLabel("●" if is_active else "○")
            dot.setStyleSheet("color: #3584e4; font-size: 14px;" if is_active else "color: #666; font-size: 14px;")
            rl.addWidget(dot)

            lbl = QLabel(t)
            lbl.setStyleSheet("color: #ffffff; font-size: 13px;" + ("font-weight: bold;" if is_active else ""))
            rl.addWidget(lbl)
            rl.addStretch()

            if not is_active:
                btn_sel = QPushButton("Выбрать")
                btn_sel.setStyleSheet("color: #3584e4; font-size: 11px; background: transparent; border: none;")
                btn_sel.setCursor(Qt.CursorShape.PointingHandCursor)
                btn_sel.clicked.connect(lambda _, host=t: self._select_target(host))
                rl.addWidget(btn_sel)

            if len(targets) > 1:
                btn_del = QPushButton("🗑")
                btn_del.setFixedSize(22, 22)
                btn_del.setCursor(Qt.CursorShape.PointingHandCursor)
                btn_del.setStyleSheet("background: transparent; border: none; color: #888;")
                btn_del.clicked.connect(lambda _, host=t: self._delete_target(host))
                rl.addWidget(btn_del)

            self.targets_layout.addWidget(row)
        self.targets_layout.addStretch()

    def _select_target(self, host):
        set_active_target(host)
        self.refresh_targets()
        self.target_changed.emit(host)
        self.close_requested.emit()

    def _on_add_target(self):
        text = self.add_input.text().strip()
        if text:
            try:
                norm = normalize_host(text)
            except ValueError:
                return
            targets = load_targets_list()
            if norm not in targets:
                targets.append(norm)
                save_targets_list(targets)
            set_active_target(norm)
            self.add_input.clear()
            self.refresh_targets()
            self.target_changed.emit(norm)

    def _delete_target(self, host):
        targets = load_targets_list()
        if host in targets:
            targets.remove(host)
            if not targets:
                targets = list(DEFAULT_TARGETS)
            save_targets_list(targets)
        active = get_active_target()
        if active == host:
            active = targets[0]
            set_active_target(active)
            self.target_changed.emit(active)
        self.refresh_targets()

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("MainWindow")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Popup)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(STYLE_SHEET)
        self.setFixedWidth(360)
        self.setMinimumHeight(520)
        self.setMaximumHeight(640)

        self.adapter = get_adapter()
        self.active_category = "bypass"
        self.search_query = ""
        self.sort_by_latency = False
        self.cached_latencies = load_cached_latencies()
        self.pending_domains = set()
        self.dot_frame_index = 0
        self.dot_frames = [".", "..", "..."]

        self.dot_timer = QTimer(self)
        self.dot_timer.timeout.connect(self._on_dot_frame)

        self._init_ui()
        self._refresh_rows()

        self.update_worker = UpdateCheckWorker()
        self.update_worker.update_signal.connect(self._on_update_found)
        self.update_worker.start()

    def _init_ui(self):
        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(12, 12, 12, 12)
        self.root_layout.setSpacing(8)

        self.update_banner = QFrame()
        self.update_banner.setObjectName("UpdateBanner")
        ub_layout = QHBoxLayout(self.update_banner)
        ub_layout.setContentsMargins(8, 4, 8, 4)
        self.lbl_update = QLabel("Доступно обновление!")
        self.lbl_update.setStyleSheet("color: #ffffff; font-size: 12px; font-weight: bold;")
        ub_layout.addWidget(self.lbl_update)
        ub_layout.addStretch()
        self.btn_update = QPushButton("Скачать")
        self.btn_update.setStyleSheet("background-color: #3584e4; color: #fff; border: none; border-radius: 4px; padding: 2px 8px;")
        self.btn_update.setCursor(Qt.CursorShape.PointingHandCursor)
        ub_layout.addWidget(self.btn_update)
        self.root_layout.addWidget(self.update_banner)
        self.update_banner.hide()

        search_box = QHBoxLayout()
        search_box.setSpacing(6)

        self.search_input = QLineEdit()
        self.search_input.setObjectName("SearchInput")
        self.search_input.setPlaceholderText("🔍 Поиск...")
        self.search_input.textChanged.connect(self._on_search_changed)
        search_box.addWidget(self.search_input)

        self.btn_sort = QPushButton("⇅")
        self.btn_sort.setObjectName("IconButton")
        self.btn_sort.setProperty("class", "IconButton")
        self.btn_sort.setFixedSize(34, 34)
        self.btn_sort.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_sort.setToolTip("Сортировать по задержке / по алфавиту")
        self.btn_sort.clicked.connect(self._toggle_sort)
        search_box.addWidget(self.btn_sort)

        self.root_layout.addLayout(search_box)

        self.tabs_container = QFrame()
        self.tabs_container.setObjectName("TabsContainer")
        self.tabs_layout = QHBoxLayout(self.tabs_container)
        self.tabs_layout.setContentsMargins(3, 3, 3, 3)
        self.tabs_layout.setSpacing(4)

        presets = load_presets()
        self.tab_buttons = {}
        category_labels = {
            "bypass": "🛡️ Обход",
            "security": "🔒 Защита",
            "global": "🌍 Мир",
            "national": "🏳️ Регион",
        }
        for cat in presets.get("categories", []):
            cid = cat["id"]
            lbl = category_labels.get(cid, cat.get("title", ""))
            btn = QPushButton(lbl)
            btn.setToolTip(cat.get("title", ""))
            btn.setProperty("cat_id", cid)
            btn.setProperty("class", "TabButton")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            btn.clicked.connect(lambda _, c=cid: self._switch_tab(c))
            self.tabs_layout.addWidget(btn)
            self.tab_buttons[cid] = btn

        self.root_layout.addWidget(self.tabs_container)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll_content = QWidget()
        self.scroll_content.setObjectName("ScrollContent")
        self.rows_layout = QVBoxLayout(self.scroll_content)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(3)
        self.scroll.setWidget(self.scroll_content)
        self.root_layout.addWidget(self.scroll)

        self.default_row = QFrame()
        self.default_row.setProperty("class", "DnsRow")
        self.default_row.setCursor(Qt.CursorShape.PointingHandCursor)
        self.default_row.mousePressEvent = lambda _: self._apply_dns("DEFAULT")
        def_layout = QHBoxLayout(self.default_row)
        def_layout.setContentsMargins(6, 4, 6, 4)

        self.def_radio = QLabel("○")
        self.def_radio.setStyleSheet("color: #3584e4; font-size: 14px;")
        def_layout.addWidget(self.def_radio)

        def_icon = QLabel("🖧")
        def_icon.setStyleSheet("font-size: 14px; margin-right: 4px;")
        def_layout.addWidget(def_icon)

        self.def_title = QLabel("По умолчанию (автоматически)")
        self.def_title.setProperty("class", "DomainTitle")
        def_layout.addWidget(self.def_title)
        def_layout.addStretch()

        self.def_latency = QLabel()
        def_layout.addWidget(self.def_latency)

        self.root_layout.addWidget(self.default_row)

        self.add_container = QFrame()
        self.add_container.setStyleSheet("background-color: rgba(255,255,255,0.05); border-radius: 8px; padding: 4px;")
        add_layout = QHBoxLayout(self.add_container)
        add_layout.setContentsMargins(6, 4, 6, 4)
        add_layout.setSpacing(6)

        self.new_dns_input = QLineEdit()
        self.new_dns_input.setPlaceholderText("Домен DNS (напр. dns.google)...")
        self.new_dns_input.setObjectName("SearchInput")
        self.new_dns_input.returnPressed.connect(self._save_new_dns)
        add_layout.addWidget(self.new_dns_input)

        self.btn_save_dns = QPushButton("✔")
        self.btn_save_dns.setObjectName("IconButton")
        self.btn_save_dns.setProperty("class", "IconButton")
        self.btn_save_dns.setFixedSize(30, 30)
        self.btn_save_dns.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_save_dns.clicked.connect(self._save_new_dns)
        add_layout.addWidget(self.btn_save_dns)

        self.root_layout.addWidget(self.add_container)
        self.add_container.hide()

        bottom_bar = QFrame()
        bottom_bar.setObjectName("BottomBar")
        bb_layout = QHBoxLayout(bottom_bar)
        bb_layout.setContentsMargins(0, 4, 0, 0)
        bb_layout.setSpacing(8)

        self.btn_show_add = QPushButton("+")
        self.btn_show_add.setProperty("class", "BottomBtn")
        self.btn_show_add.setFixedSize(32, 32)
        self.btn_show_add.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_show_add.setToolTip("Добавить собственный DNS-сервер")
        self.btn_show_add.clicked.connect(self._toggle_add_row)
        bb_layout.addWidget(self.btn_show_add)

        self.btn_target = QPushButton()
        self.btn_target.setObjectName("TargetBtn")
        self.btn_target.setProperty("class", "BottomBtn")
        self.btn_target.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_target.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_target.clicked.connect(self._show_targets_modal)
        self._update_target_button_label()
        bb_layout.addWidget(self.btn_target)

        self.btn_refresh = QPushButton("↻")
        self.btn_refresh.setProperty("class", "BottomBtn")
        self.btn_refresh.setFixedSize(32, 32)
        self.btn_refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_refresh.setToolTip("Обновить замеры задержки")
        self.btn_refresh.clicked.connect(self._start_probe)
        bb_layout.addWidget(self.btn_refresh)

        self.btn_donate = QPushButton("♡")
        self.btn_donate.setProperty("class", "BottomBtn")
        self.btn_donate.setFixedSize(32, 32)
        self.btn_donate.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_donate.setToolTip("Поддержать автора на Boosty")
        self.btn_donate.clicked.connect(lambda: webbrowser.open(DONATE_URL))
        bb_layout.addWidget(self.btn_donate)

        self.root_layout.addWidget(bottom_bar)

        self.targets_modal = TargetsModal(self)
        self.targets_modal.target_changed.connect(self._on_target_changed)
        self.targets_modal.close_requested.connect(self.targets_modal.hide)
        self.targets_modal.hide()

        self._update_tab_styles()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.targets_modal.setGeometry(self.rect())

    def _update_target_button_label(self):
        active = get_active_target()
        self.btn_target.setText(f"🌐 {active} ▾")

    def _show_targets_modal(self):
        self.targets_modal.refresh_targets()
        self.targets_modal.setGeometry(self.rect())
        self.targets_modal.show()
        self.targets_modal.raise_()

    def _on_target_changed(self, host):
        self._update_target_button_label()
        self._start_probe()

    def _toggle_add_row(self):
        if self.add_container.isVisible():
            self.add_container.hide()
            self.btn_show_add.setText("+")
        else:
            self.add_container.show()
            self.btn_show_add.setText("✕")
            self.new_dns_input.setFocus()

    def _save_new_dns(self):
        text = self.new_dns_input.text().strip()
        if text:
            try:
                add_dns(text, self.active_category)
            except ValueError:
                return
            self.new_dns_input.clear()
            self.add_container.hide()
            self.btn_show_add.setText("+")
            self._refresh_rows()
            self._start_probe_single(text)

    def _switch_tab(self, cat_id):
        self.active_category = cat_id
        self._update_tab_styles()
        self._refresh_rows()

    def _update_tab_styles(self):
        for cid, btn in self.tab_buttons.items():
            if cid == self.active_category:
                btn.setProperty("class", "TabButton ActiveTab")
            else:
                btn.setProperty("class", "TabButton")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _toggle_sort(self):
        self.sort_by_latency = not self.sort_by_latency
        self.btn_sort.setText("⚡" if self.sort_by_latency else "⇅")
        self._refresh_rows()

    def _on_search_changed(self, text):
        self.search_query = text.strip().lower()
        self._refresh_rows()

    def _refresh_rows(self):
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        presets = load_presets()
        active_status = self.adapter.get_current_dns()
        active_dom = active_status.get("domain", "DEFAULT")

        is_default_active = (active_dom == "DEFAULT")
        self.def_radio.setText("●" if is_default_active else "○")
        self.def_radio.setStyleSheet("color: #3584e4; font-size: 14px;" if is_default_active else "color: rgba(255,255,255,0.45); font-size: 14px;")
        if is_default_active:
            self.default_row.setProperty("class", "DnsRow ActiveRow")
            self.def_title.setProperty("class", "DomainTitle ActiveTitle")
        else:
            self.default_row.setProperty("class", "DnsRow")
            self.def_title.setProperty("class", "DomainTitle")
        self.default_row.style().unpolish(self.default_row)
        self.default_row.style().polish(self.default_row)

        def_cache = self.cached_latencies.get("DEFAULT")
        if def_cache:
            if def_cache.get("ok"):
                self.def_latency.setText(f"{def_cache.get('latency')} ms")
                self.def_latency.setProperty("class", "LatencyOk")
            else:
                self.def_latency.setText(def_cache.get("text", "не отвечает"))
                self.def_latency.setProperty("class", "LatencyError")
        else:
            self.def_latency.setText("")
        self.def_latency.style().unpolish(self.def_latency)
        self.def_latency.style().polish(self.def_latency)

        if self.search_query:
            domains = [d for d in load_dns_list() if self.search_query in d.lower()]
            self.tabs_container.hide()
        else:
            self.tabs_container.show()
            domains = []
            for cat in presets.get("categories", []):
                if cat.get("id") == self.active_category:
                    domains = list(cat.get("domains", []))
                    break

        if self.sort_by_latency:
            def sort_key(d):
                c = self.cached_latencies.get(d)
                if c and c.get("ok"):
                    return (0, c.get("latency", 9999))
                return (1, d)
            domains.sort(key=sort_key)
        else:
            domains.sort(key=lambda d: d.lower())

        self.row_widgets = {}

        for dom in domains:
            row = QFrame()
            row.setCursor(Qt.CursorShape.PointingHandCursor)
            row.mousePressEvent = lambda _, d=dom: self._apply_dns(d)

            is_active = (dom == active_dom)
            row.setProperty("class", "DnsRow ActiveRow" if is_active else "DnsRow")

            rl = QHBoxLayout(row)
            rl.setContentsMargins(6, 4, 6, 4)
            rl.setSpacing(6)

            radio = QLabel("●" if is_active else "○")
            radio.setStyleSheet("color: #3584e4; font-size: 14px;" if is_active else "color: rgba(255,255,255,0.45); font-size: 14px;")
            rl.addWidget(radio)

            title = QLabel(dom)
            title.setProperty("class", "DomainTitle ActiveTitle" if is_active else "DomainTitle")
            rl.addWidget(title)
            rl.addStretch()

            cache = self.cached_latencies.get(dom, {})
            proto = cache.get("proto", "udp").lower()
            badge = QLabel(proto.upper())
            if proto == "dot":
                badge.setProperty("class", "BadgeDoT")
            elif proto == "doh":
                badge.setProperty("class", "BadgeDoH")
            else:
                badge.setProperty("class", "BadgeUDP")
            rl.addWidget(badge)

            latency = QLabel()
            if dom in self.pending_domains:
                latency.setText(self.dot_frames[self.dot_frame_index])
                latency.setProperty("class", "LatencyChecking")
            elif cache:
                if cache.get("ok"):
                    latency.setText(f"{cache.get('latency')} ms")
                    latency.setProperty("class", "LatencyOk")
                else:
                    latency.setText(cache.get("text", "ошибка"))
                    latency.setProperty("class", "LatencyError")
            rl.addWidget(latency)

            btn_del = QPushButton("🗑")
            btn_del.setProperty("class", "TrashButton")
            btn_del.setFixedSize(24, 24)
            btn_del.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_del.clicked.connect(lambda _, d=dom: self._delete_dns(d))
            rl.addWidget(btn_del)

            self.rows_layout.addWidget(row)
            self.row_widgets[dom] = {"row": row, "latency": latency, "badge": badge}

        self.rows_layout.addStretch()

    def _delete_dns(self, domain):
        active_status = self.adapter.get_current_dns()
        if active_status.get("domain") == domain:
            self._apply_dns("DEFAULT")
        remove_dns(domain)
        self._refresh_rows()

    def _apply_dns(self, domain):
        self.apply_worker = ApplyWorker(domain)
        self.apply_worker.done_signal.connect(self._on_apply_completed)
        self.apply_worker.start()

    def _on_apply_completed(self, res):
        if res.get("success"):
            self._refresh_rows()
            dom = res.get("domain", "")
            msg = "Настройки сброшены на автоматические (DHCP)" if dom == "DEFAULT" else f"Активный DNS переключен на {dom}"
            tray_icon.showMessage("DNS Switcher", msg, QSystemTrayIcon.MessageIcon.Information, 2000)
        else:
            err = res.get("error", "Неизвестная ошибка")
            QMessageBox.warning(self, "Ошибка смены DNS", err)

    def _start_probe(self):
        target = get_active_target()
        all_doms = load_dns_list()
        self.pending_domains = set(all_doms)
        self.pending_domains.add("DEFAULT")
        self.dot_timer.start(300)
        self._refresh_rows()

        self.probe_worker = ProbeWorker(target)
        self.probe_worker.result_signal.connect(self._on_probe_result)
        self.probe_worker.finished_signal.connect(self._on_probe_finished)
        self.probe_worker.start()

    def _start_probe_single(self, domain):
        self.pending_domains.add(domain)
        self.dot_timer.start(300)
        self._refresh_rows()

        target = get_active_target()
        self.single_probe_worker = SingleProbeWorker(domain, target)
        self.single_probe_worker.result_signal.connect(self._on_probe_result)
        self.single_probe_worker.start()

    def _on_probe_result(self, res):
        dom = res.get("domain")
        if dom:
            self.cached_latencies[dom] = res
            self.pending_domains.discard(dom)
            if not self.pending_domains:
                self.dot_timer.stop()

            w = self.row_widgets.get(dom)
            if w:
                lbl = w["latency"]
                if res.get("ok"):
                    lbl.setText(f"{res.get('latency')} ms")
                    lbl.setProperty("class", "LatencyOk")
                else:
                    lbl.setText(res.get("text", "ошибка"))
                    lbl.setProperty("class", "LatencyError")
                lbl.style().unpolish(lbl)
                lbl.style().polish(lbl)

                badge = w["badge"]
                proto = res.get("proto", "udp").lower()
                badge.setText(proto.upper())
                cls_map = {"dot": "BadgeDoT", "doh": "BadgeDoH", "udp": "BadgeUDP"}
                badge.setProperty("class", cls_map.get(proto, "BadgeUDP"))
                badge.style().unpolish(badge)
                badge.style().polish(badge)

            if dom == "DEFAULT":
                if res.get("ok"):
                    self.def_latency.setText(f"{res.get('latency')} ms")
                    self.def_latency.setProperty("class", "LatencyOk")
                else:
                    self.def_latency.setText(res.get("text", "не отвечает"))
                    self.def_latency.setProperty("class", "LatencyError")
                self.def_latency.style().unpolish(self.def_latency)
                self.def_latency.style().polish(self.def_latency)

    def _on_probe_finished(self):
        self.dot_timer.stop()
        self.pending_domains.clear()
        self._refresh_rows()

    def _on_dot_frame(self):
        self.dot_frame_index = (self.dot_frame_index + 1) % len(self.dot_frames)
        frame_text = self.dot_frames[self.dot_frame_index]
        for dom in self.pending_domains:
            w = self.row_widgets.get(dom)
            if w:
                w["latency"].setText(frame_text)

    def _on_update_found(self, info):
        self.lbl_update.setText(f"Новая версия: {info.get('latest_version')}!")
        try:
            self.btn_update.clicked.disconnect()
        except Exception:
            pass
        self.btn_update.clicked.connect(lambda: webbrowser.open(info.get("download_url")))
        self.update_banner.show()

class SystemTrayApp:
    def __init__(self, app):
        self.app = app
        self.tray = QSystemTrayIcon(generate_app_icon(), app)
        self.window = MainWindow()

        menu = QMenu()
        menu.setStyleSheet("""
            QMenu {
                background-color: #242424;
                color: #ffffff;
                border: 1px solid rgba(255,255,255,0.15);
                border-radius: 6px;
                padding: 4px;
            }
            QMenu::item:selected {
                background-color: #3584e4;
                border-radius: 4px;
            }
        """)
        action_open = menu.addAction("Открыть DNS Switcher")
        action_open.triggered.connect(self.toggle_window)

        action_default = menu.addAction("Сбросить на DNS по умолчанию")
        action_default.triggered.connect(lambda: self.window._apply_dns("DEFAULT"))

        menu.addSeparator()
        action_quit = menu.addAction("Выход")
        action_quit.triggered.connect(self.app.quit)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

        global tray_icon
        tray_icon = self.tray

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.toggle_window()

    def toggle_window(self):
        if self.window.isVisible():
            self.window.hide()
        else:
            self.position_window_near_tray()
            self.window.show()
            self.window.raise_()
            self.window.activateWindow()

    def position_window_near_tray(self):
        cursor_pos = QCursor.pos()
        screen = QGuiApplication.screenAt(cursor_pos) or QApplication.primaryScreen()
        screen_geo = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)
        w = self.window.width()
        h = self.window.height()

        geo = self.tray.geometry()
        if geo.x() > 0 and geo.y() > 0:
            target_x = geo.x() + geo.width() // 2
            target_y = geo.y()
            target_h = geo.height()
        else:
            target_x = cursor_pos.x()
            target_y = cursor_pos.y()
            target_h = 24

        x = target_x - w // 2
        # If tray is in top half of screen (e.g. top taskbar/panel): place below
        if target_y < screen_geo.center().y():
            y = target_y + target_h + 10
        else:
            y = target_y - h - 10

        x = max(screen_geo.left() + 10, min(x, screen_geo.right() - w - 10))
        y = max(screen_geo.top() + 10, min(y, screen_geo.bottom() - h - 10))

        self.window.move(QPoint(x, y))

def main():
    if hasattr(QtCore.Qt.ApplicationAttribute, "AA_EnableHighDpiScaling"):
        QApplication.setAttribute(QtCore.Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    if hasattr(QtCore.Qt.ApplicationAttribute, "AA_UseHighDpiPixmaps"):
        QApplication.setAttribute(QtCore.Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    tray_app = SystemTrayApp(app)
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
