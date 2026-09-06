#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, sys, subprocess, json, re
from PySide6.QtCore import Qt, QTimer, QProcess, QUrl, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QIcon, QPixmap, QAction, QDesktopServices, QFont
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QSystemTrayIcon, QMenu, QScrollArea, QFrame, QGraphicsDropShadowEffect, QCheckBox)

import hashlib
import hmac
import struct
import ctypes
import ctypes.wintypes

# ============ Anti-Reverse Engineering ============

def _anti_debug():
    """Detect debugger attachment and analysis tools"""
    try:
        # Check IsDebuggerPresent
        kernel32 = ctypes.windll.kernel32
        if kernel32.IsDebuggerPresent():
            return True
        # Check for common analysis tool windows
        user32 = ctypes.windll.user32
        tools = [
            'x64dbg', 'x32dbg', 'OllyDbg', 'IDA', 'Ghidra',
            'Process Monitor', 'Process Hacker', 'Wireshark',
            'Fiddler', 'Charles', 'Burp Suite', 'dnSpy'
        ]
        for tool in tools:
            hwnd = user32.FindWindowW(None, tool)
            if hwnd:
                return True
    except Exception:
        pass
    return False


def _anti_vm():
    """Detect virtual machine / sandbox"""
    try:
        import platform
        # Check manufacturer strings
        manufacturer = platform.system()
        # Simple VM detection via registry
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, 
                r'HARDWARE\DESCRIPTION\System\BIOS')
            val, _ = winreg.QueryValueEx(key, 'SystemManufacturer')
            vm_strings = ['VMware', 'VirtualBox', 'KVM', 'QEMU', 'Xen', 'Microsoft Corporation Virtual Machine']
            for s in vm_strings:
                if s.lower() in str(val).lower():
                    return True
        except Exception:
            pass
        # Check CPU count (sandboxes often have 1-2)
        if os.cpu_count() and os.cpu_count() <= 1:
            return True
    except Exception:
        pass
    return False


def _integrity_check():
    """Verify code integrity - detects tampering"""
    try:
        # Get this module's code hash
        import __main__
        code_obj = __main__.__dict__.get('_fj_hash', None)
        if code_obj is None:
            return True  # First run
        current = hashlib.sha256(str(sys._MEIPASS if hasattr(sys, '_MEIPASS') else __file__).encode()).hexdigest()[:16]
        return code_obj == current
    except Exception:
        return True


def _security_gate():
    """Run all security checks - returns False if compromised"""
    if _anti_debug():
        return False
    if _anti_vm():
        return False
    if not _integrity_check():
        return False
    return True

APP_NAME = "寒霜 Codex 破甲工具"
APP_VERSION = "1.0"
ACCENT = "#2F6FED"
ACCENT_LIGHT = "#EBF0FE"
SUCCESS = "#16A34A"
SUCCESS_LIGHT = "#F0FDF4"
DANGER = "#EF4444"
TEXT_PRIMARY = "#1B2231"
TEXT_SECONDARY = "#6B7280"
TEXT_HINT = "#9CA3AF"
BORDER_LIGHT = "#E2E6ED"
BORDER_MEDIUM = "#D0D5DD"
BG_PRIMARY = "#FFFFFF"
BG_CARD = "#F7F8FC"
BG_HOVER = "#EDF0F7"
FONT_UI = "Microsoft YaHei UI"

ACTIVATION_LINE = "已激活 QQ群1098743629"
DISCLAIMER_TITLE = "免责声明"
AGREE_TEXT = "我同意 并接受所有条约"
QQ_LINK = "https://qm.qq.com/q/cRpXonxdvy"

DISCLAIMER_TEXT = (
    "本提示词、文档、代码及相关资料（下称\u201c本内容\u201d）仅供合法的教育学习、授权安全测试、技术研究与知识分享之用。\n\n"
    "1. 本内容仅面向具备完全民事行为能力的成年人。使用者须确保其获取、使用本内容的行为完全遵守所在国家/地区法律法规及第三方平台协议。\n"
    "2. 严禁将本内容用于任何违法或侵权活动，包括但不限于：制作外挂、网络入侵与 DDoS 攻击、传播恶意软件、伪造证件、诈骗、洗钱、走私、涉及枪械/爆炸物/毒品及危害人身安全的行为、诱导 AI 绕过安全机制实施违法、以及其他侵犯他人合法权益的行为。\n"
    "3. 使用者将本内容用于非法用途，属其个人独立行为，与提供方无关；由此产生的一切法律后果、经济责任及第三方索赔，均由使用者自行承担。\n"
    "4. 提供方不对使用者的任何行为承担任何直接或间接责任，不参与、不协助、不鼓励、不默许任何违法行为。\n"
    "5. 使用、复制、传播本内容即视为已阅读并同意本声明全部条款；不同意请立即停止使用并删除所有副本。\n\n"
    "提供方保留随时更新本声明的权利，更新后自发布之日起生效。"
)

TUTORIAL_TITLE = "使用教程"

TUTORIAL_TEXT = (
    "使用教程\n\n"
    "flash 适合那种中端模型 比如 v4 flash\n"
    "codex 顶级全破 就是 v4 pro 和 gpt5.6 用的了 那种顶尖模型\n\n"
    "执行完了 输入激活词「寒霜」 显示\u201c已成功破甲\u201d就是可以了\n\n"
    "如果遇到不行的情况 重新开对话 重新发就行 有时候会概率拒绝的 正常\n"
    "一般执行一次之后第一次发是会拒绝 重新开个对话就可以了\n\n"
    "如果一直不行 要么是和谐了 要么是中转站惨水 因为安全对齐不一样 给你惨了傻子模型\n\n"
    "每次重启电脑记得重新执行 重启自动复原的\n\n"
    "永久免费       QQ群1098743629"
)

STYLESHEET = """
QWidget { font-family: 'Microsoft YaHei UI'; }
QWidget#mainWindow { background: #FFFFFF; }
QLabel { color: #1B2231; background: transparent; }
QPushButton { border-radius: 8px; font-family: 'Microsoft YaHei UI'; font-weight: 600; }
QPushButton.btnPrimary { background: #2F6FED; color: #FFFFFF; border: none; font-size: 15px; padding: 0px 20px; border-radius: 8px; }
QPushButton.btnPrimary:hover { background: #4285F4; border: 1px solid #4285F4; }
QPushButton.btnPrimary:pressed { background: #1E5CD6; border: 1px solid #1E5CD6; }
QPushButton.btnPrimary:disabled { background: #C7CCD6; color: #FFFFFF; }
QPushButton.btnSecondary { background: #FFFFFF; color: #1B2231; border: 1.5px solid #D0D5DD; font-size: 15px; padding: 0px 20px; border-radius: 8px; }
QPushButton.btnSecondary:hover { background: #F0F3F9; border: 1.5px solid #2F6FED; }
QPushButton.btnSecondary:pressed { background: #E4E8F0; border: 1.5px solid #1E5CD6; }
QPushButton.btnSecondary:disabled { color: #9CA3AF; border: 1.5px solid #E2E6ED; background: #F9FAFB; }
QPushButton.btnDanger { background: #EF4444; color: #FFFFFF; border: none; font-size: 15px; padding: 0px 20px; border-radius: 8px; }
QPushButton.btnDanger:hover { background: #DC2626; border: 1px solid #DC2626; }
QPushButton.btnDanger:pressed { background: #B91C1C; border: 1px solid #B91C1C; }
QPushButton.btnLink { background: transparent; color: #2F6FED; border: none; font-size: 14px; padding: 10px 20px; font-weight: 600; border-radius: 6px; }
QPushButton.btnLink:hover { color: #1E5CD6; background: #EBF0FE; }
QPushButton.btnLink:pressed { color: #1E5CD6; background: #DCE6FD; }
QFrame.card { background: #F7F8FC; border: 1px solid #E2E6ED; border-radius: 12px; }
QScrollArea { background: transparent; border: none; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }
QScrollBar::handle:vertical { background: #D0D5DD; border-radius: 4px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #B0B5BD; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QCheckBox { color: #1B2231; font-size: 14px; spacing: 10px; }
QCheckBox::indicator { width: 22px; height: 22px; border-radius: 6px; border: 2px solid #D0D5DD; background: #FFFFFF; }
QCheckBox::indicator:hover { border-color: #2F6FED; background: #F0F3F9; }
QCheckBox::indicator:checked { background-color: #2F6FED; border-color: #2F6FED; image: url(check.png); }
QCheckBox::indicator:checked:hover { background-color: #4285F4; border-color: #4285F4; }
"""


def _res(rel=''):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, rel)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), rel)




def _create_check_png():
    """Generate a white checkmark PNG for checkbox indicator"""
    try:
        from PySide6.QtCore import Qt, QPointF
        from PySide6.QtGui import QPainter, QPen, QColor, QPixmap, QPainterPath
        pm = QPixmap(22, 22)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor('#FFFFFF'), 3)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        path = QPainterPath()
        path.moveTo(5, 12)
        path.lineTo(10, 17)
        path.lineTo(18, 6)
        p.drawPath(path)
        p.end()
        # Use a writable location (temp dir) for onefile mode
        if hasattr(sys, '_MEIPASS'):
            base = os.path.dirname(sys.executable)
        else:
            base = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(base, 'check.png')
        pm.save(path, 'PNG')
        return path
    except Exception:
        return None




# ============ Login/Register Dialog ============


class AgreementDialog(QWidget):
    agreed = Signal()

    def __init__(self):
        super().__init__(None)
        self.setWindowTitle(DISCLAIMER_TITLE)
        self.setWindowFlags(Qt.Dialog | Qt.WindowStaysOnTopHint)
        self.setFixedSize(560, 680)
        self.setStyleSheet(STYLESHEET)
        screen = QApplication.primaryScreen().availableGeometry()
        x = (screen.width() - self.width()) // 2 + screen.x()
        y = (screen.height() - self.height()) // 2 + screen.y()
        self.move(x, y)
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 28, 28, 28)
        lay.setSpacing(16)
        title = QLabel(DISCLAIMER_TITLE)
        title.setStyleSheet('font-size: 22px; font-weight: 700; color: ' + TEXT_PRIMARY + ';')
        title.setAlignment(Qt.AlignCenter)
        lay.addWidget(title)
        act = QLabel(ACTIVATION_LINE)
        act.setStyleSheet('font-size: 15px; font-weight: 600; color: ' + ACCENT + ';')
        act.setAlignment(Qt.AlignCenter)
        lay.addWidget(act)
        div = QFrame()
        div.setFrameShape(QFrame.HLine)
        div.setStyleSheet('background: ' + BORDER_LIGHT + '; max-height: 1px; border: none;')
        lay.addWidget(div)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QLabel(DISCLAIMER_TEXT)
        body.setWordWrap(True)
        body.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        body.setStyleSheet('color: ' + TEXT_PRIMARY + '; font-size: 14px; background: transparent; padding: 4px; line-height: 1.8;')
        scroll.setWidget(body)
        lay.addWidget(scroll, 1)
        btn = QPushButton(AGREE_TEXT)
        btn.setProperty('class', 'btnPrimary')
        btn.setFixedHeight(46)
        btn.clicked.connect(self._agree)
        lay.addWidget(btn)
        btn_reject = QPushButton('拒绝并退出')
        btn_reject.setProperty('class', 'btnSecondary')
        btn_reject.setFixedHeight(46)
        btn_reject.setMinimumWidth(200)
        btn_reject.clicked.connect(self._reject)
        lay.addWidget(btn_reject)

    def _agree(self):
        self.agreed.emit()
        self.close()

    def _reject(self):
        QApplication.instance().quit()


class TutorialDialog(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(TUTORIAL_TITLE)
        self.setWindowFlags(Qt.Dialog | Qt.WindowStaysOnTopHint)
        self.setFixedSize(540, 580)
        self.setStyleSheet(STYLESHEET)
        if parent:
            sg = parent.screen().availableGeometry()
        else:
            sg = QApplication.primaryScreen().availableGeometry()
        x = (sg.width() - self.width()) // 2 + sg.x()
        y = (sg.height() - self.height()) // 2 + sg.y()
        self.move(x, y)
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 28, 28, 28)
        lay.setSpacing(16)
        title = QLabel(TUTORIAL_TITLE)
        title.setStyleSheet('font-size: 22px; font-weight: 700; color: ' + TEXT_PRIMARY + ';')
        title.setAlignment(Qt.AlignCenter)
        lay.addWidget(title)
        div = QFrame()
        div.setFrameShape(QFrame.HLine)
        div.setStyleSheet('background: ' + BORDER_LIGHT + '; max-height: 1px; border: none;')
        lay.addWidget(div)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QLabel(TUTORIAL_TEXT)
        body.setWordWrap(True)
        body.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        body.setStyleSheet('color: ' + TEXT_PRIMARY + '; font-size: 15px; background: transparent; padding: 4px; line-height: 1.8;')
        scroll.setWidget(body)
        lay.addWidget(scroll, 1)
        close_btn = QPushButton('关闭')
        close_btn.setProperty('class', 'btnSecondary')
        close_btn.setFixedHeight(40)
        close_btn.clicked.connect(self.close)
        lay.addWidget(close_btn)


class InstallCard(QFrame):
    install_requested = Signal(str)

    def __init__(self, title, desc, prompt_filename, parent=None):
        super().__init__(parent)
        self._prompt_filename = prompt_filename
        self.setProperty('class', 'card')
        self._build(title, desc)

    def _build(self, title, desc):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(12)
        top = QHBoxLayout()
        top.setSpacing(12)
        name = QLabel(title)
        name.setStyleSheet('font-size: 16px; font-weight: 700; color: ' + TEXT_PRIMARY + '; background: transparent;')
        top.addWidget(name)
        top.addStretch(1)
        self._tag = QLabel('未安装')
        self._tag.setStyleSheet(
            'font-size: 12px; font-weight: 600; color: ' + TEXT_HINT + '; background: ' + BG_HOVER +
            '; border-radius: 10px; padding: 4px 12px;')
        top.addWidget(self._tag)
        lay.addLayout(top)
        desc_label = QLabel(desc)
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet('font-size: 13px; color: ' + TEXT_SECONDARY + '; background: transparent;')
        lay.addWidget(desc_label)
        self._btn = QPushButton('安装')
        self._btn.setProperty('class', 'btnPrimary')
        self._btn.setFixedHeight(46)
        self._btn.clicked.connect(lambda: self.install_requested.emit(self._prompt_filename))
        lay.addWidget(self._btn)

    def set_installed(self, ok):
        if ok:
            self._tag.setText('已安装 ✓')
            self._tag.setStyleSheet(
                'font-size: 12px; font-weight: 600; color: ' + SUCCESS + '; background: ' + SUCCESS_LIGHT +
                '; border-radius: 10px; padding: 4px 12px;')
            self._btn.setText('重新安装')
        else:
            self._tag.setText('未安装')
            self._tag.setStyleSheet(
                'font-size: 12px; font-weight: 600; color: ' + TEXT_HINT + '; background: ' + BG_HOVER +
                '; border-radius: 10px; padding: 4px 12px;')
            self._btn.setText('安装')


class MainWindow(QWidget):
    def __init__(self):
        super().__init__(None)
        self.setObjectName('mainWindow')
        self.setWindowTitle(APP_NAME)
        self.setWindowFlags(Qt.Window)
        self.setFixedSize(780, 520)
        self.setStyleSheet(STYLESHEET)
        screen = QApplication.primaryScreen().availableGeometry()
        x = (screen.width() - self.width()) // 2 + screen.x()
        y = (screen.height() - self.height()) // 2 + screen.y()
        self.move(x, y)
        self._proc = None
        self._tutorial = None
        self._tray = None
        self._build()
        self._setup_tray()

    def _config_dir(self):
        return os.path.expanduser('~/.codex')

    def _read_auto_setting(self):
        sp = os.path.join(self._config_dir(), 'fj_settings.json')
        if os.path.exists(sp):
            try:
                with open(sp, 'r', encoding='utf-8') as f:
                    d = json.load(f)
                    return d.get('auto_install', False)
            except Exception:
                pass
        return False

    def _save_auto_setting(self, val):
        sd = self._config_dir()
        os.makedirs(sd, exist_ok=True)
        sp = os.path.join(sd, 'fj_settings.json')
        d = {}
        if os.path.exists(sp):
            try:
                with open(sp, 'r', encoding='utf-8') as f:
                    d = json.load(f)
            except Exception:
                pass
        d['auto_install'] = val
        with open(sp, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=2)

    def _set_status(self, text, level=None):
        if level == 'success':
            self._status.setText('● ' + text)
            self._status.setStyleSheet('font-size: 14px; color: ' + SUCCESS + '; font-weight: 600;')
        elif level == 'error':
            self._status.setText('● ' + text)
            self._status.setStyleSheet('font-size: 14px; color: ' + DANGER + '; font-weight: 600;')
        else:
            self._status.setText('● ' + text)
            self._status.setStyleSheet('font-size: 14px; color: ' + TEXT_SECONDARY + ';')

    def _set_buttons_enabled(self, enabled):
        self._card_codex._btn.setEnabled(enabled)
        self._card_flash._btn.setEnabled(enabled)
        self._btn_restart.setEnabled(enabled)
        self._btn_uninstall.setEnabled(enabled)

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        # 顶部标题栏
        header = QHBoxLayout()
        header.setSpacing(14)
        logo_path = _res('logo.jpg')
        logo_label = QLabel()
        if os.path.exists(logo_path):
            pm = QPixmap(logo_path)
            pm = pm.scaled(52, 52, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            logo_label.setPixmap(pm)
            logo_label.setFixedSize(52, 52)
        else:
            logo_label.setText('寒')
            logo_label.setStyleSheet('font-size: 32px; font-weight: 700; color: ' + ACCENT + ';')
        header.addWidget(logo_label)
        tc = QVBoxLayout()
        tc.setSpacing(2)
        title = QLabel(APP_NAME)
        title.setStyleSheet('font-size: 20px; font-weight: 700; color: ' + TEXT_PRIMARY + ';')
        tc.addWidget(title)
        subtitle = QLabel('自动破甲提示词 · 一键安装')
        subtitle.setStyleSheet('font-size: 13px; color: ' + TEXT_SECONDARY + ';')
        tc.addWidget(subtitle)
        header.addLayout(tc)
        header.addStretch(1)
        vt = QLabel(APP_VERSION)
        vt.setStyleSheet(
            'font-size: 12px; font-weight: 600; color: ' + ACCENT + '; background: ' + ACCENT_LIGHT +
            '; border: 1px solid ' + ACCENT + '; border-radius: 12px; padding: 4px 14px;')
        header.addWidget(vt)
        root.addLayout(header)

        div = QFrame()
        div.setFrameShape(QFrame.HLine)
        div.setStyleSheet('background: ' + BORDER_LIGHT + '; max-height: 1px; border: none;')
        root.addWidget(div)

        # 主内容区（横向两栏）
        content = QHBoxLayout()
        content.setSpacing(16)
        left_col = QVBoxLayout()
        left_col.setSpacing(8)
        sec_left = QLabel('Codex 顶尖模型')
        sec_left.setStyleSheet('font-size: 14px; font-weight: 600; color: ' + TEXT_SECONDARY + ';')
        left_col.addWidget(sec_left)
        self._card_codex = InstallCard(
            '顶尖破甲 v1',
            '适用于 GPT-5.6 / v4 Pro 等顶级模型',
            '寒霜-变体B-v3-英文.md'
        )
        self._card_codex.install_requested.connect(self._run_install)
        left_col.addWidget(self._card_codex, 1)
        content.addLayout(left_col, 1)
        right_col = QVBoxLayout()
        right_col.setSpacing(8)
        sec_right = QLabel('Flash 中端模型')
        sec_right.setStyleSheet('font-size: 14px; font-weight: 600; color: ' + TEXT_SECONDARY + ';')
        right_col.addWidget(sec_right)
        self._card_flash = InstallCard(
            'Flash 破甲 v1',
            '适用于 v4 Flash 等中端模型',
            '寒霜-flash-v2.md'
        )
        self._card_flash.install_requested.connect(self._run_install)
        right_col.addWidget(self._card_flash, 1)
        content.addLayout(right_col, 1)
        root.addLayout(content, 1)

        auto_row = QHBoxLayout()
        auto_row.setContentsMargins(4, 0, 4, 0)
        self._auto_check = QCheckBox('启动时自动注入')
        self._auto_check.setChecked(self._read_auto_setting())
        self._auto_check.toggled.connect(self._save_auto_setting)
        auto_row.addWidget(self._auto_check)
        auto_row.addStretch(1)
        root.addLayout(auto_row)

        # 操作按钮行
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        self._btn_restart = QPushButton('重启 Codex')
        self._btn_restart.setProperty('class', 'btnSecondary')
        self._btn_restart.setFixedHeight(46)
        self._btn_restart.clicked.connect(self._restart_codex)
        btn_row.addWidget(self._btn_restart, 1)
        self._btn_tutorial = QPushButton('使用教程')
        self._btn_tutorial.setProperty('class', 'btnSecondary')
        self._btn_tutorial.setFixedHeight(46)
        self._btn_tutorial.clicked.connect(self._show_tutorial)
        btn_row.addWidget(self._btn_tutorial, 1)
        self._btn_uninstall = QPushButton('卸载')
        self._btn_uninstall.setProperty('class', 'btnDanger')
        self._btn_uninstall.setFixedHeight(46)
        self._btn_uninstall.clicked.connect(self._uninstall)
        btn_row.addWidget(self._btn_uninstall, 1)
        root.addLayout(btn_row)

        div2 = QFrame()
        div2.setFrameShape(QFrame.HLine)
        div2.setStyleSheet('background: ' + BORDER_LIGHT + '; max-height: 1px; border: none;')
        root.addWidget(div2)

        footer = QHBoxLayout()
        footer.setSpacing(16)
        self._status = QLabel('● 就绪')
        self._status.setStyleSheet('font-size: 14px; color: ' + TEXT_SECONDARY + ';')
        footer.addWidget(self._status)
        footer.addStretch(1)
        qb = QPushButton('加入QQ群')
        qb.setProperty('class', 'btnLink')
        qb.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(QQ_LINK)))
        footer.addWidget(qb)
        root.addLayout(footer)

    def _run_install(self, prompt_filename):
        base = _res()
        install_ps1 = os.path.join(base, 'install.ps1')
        prompt_path = os.path.join(base, prompt_filename)
        if not os.path.exists(prompt_path):
            self._set_status('找不到文件: ' + prompt_filename, 'error')
            return
        if not os.path.exists(install_ps1):
            self._set_status('找不到 install.ps1', 'error')
            return
        self._set_status('正在安装 ' + prompt_filename + '...')
        self._set_buttons_enabled(False)
        if self._proc is not None and self._proc.state() != QProcess.NotRunning:
            self._proc.kill()
            self._proc.waitForFinished(2000)
        proc = QProcess(self)
        self._proc = proc
        proc.setWorkingDirectory(base)
        proc.setProcessChannelMode(QProcess.MergedChannels)
        proc.finished.connect(lambda c, s: self._on_install_done(prompt_filename, c, s))
        proc.start('powershell.exe', [
            '-NoProfile', '-ExecutionPolicy', 'RemoteSigned',
            '-File', install_ps1,
            '-SourcePrompt', prompt_path
        ])

    def _on_install_done(self, pf, ec, es):
        self._set_buttons_enabled(True)
        ok = (es == QProcess.NormalExit and ec == 0)
        if ok:
            self._set_status(pf + ' 破甲成功 - 重启 Codex 生效', 'success')
            if pf == '寒霜-变体B-v3-英文.md':
                self._card_codex.set_installed(True)
                self._card_flash.set_installed(False)
            elif pf == '寒霜-flash-v2.md':
                self._card_flash.set_installed(True)
                self._card_codex.set_installed(False)
        else:
            self._set_status(pf + ' 失败 (退出码 ' + str(ec) + ')', 'error')

    def _uninstall(self):
        base = _res()
        install_ps1 = os.path.join(base, 'install.ps1')
        if not os.path.exists(install_ps1):
            self._set_status('找不到 install.ps1', 'error')
            return
        self._set_status('正在卸载...')
        self._set_buttons_enabled(False)
        proc = QProcess(self)
        self._proc = proc
        proc.setWorkingDirectory(base)
        proc.setProcessChannelMode(QProcess.MergedChannels)
        proc.finished.connect(lambda c, s: self._on_uninstall_done(c, s))
        proc.start('powershell.exe', [
            '-NoProfile', '-ExecutionPolicy', 'RemoteSigned',
            '-File', install_ps1, '-Uninstall'
        ])

    def _on_uninstall_done(self, ec, es):
        self._set_buttons_enabled(True)
        ok = (es == QProcess.NormalExit and ec == 0)
        if ok:
            self._set_status('已卸载', 'success')
            self._card_codex.set_installed(False)
            self._card_flash.set_installed(False)
        else:
            self._set_status('卸载失败', 'error')

    def _restart_codex(self):
        self._set_status('正在重启 Codex...')
        self._set_buttons_enabled(False)
        ps_cmd = "$ErrorActionPreference = 'SilentlyContinue'; "
        ps_cmd += "$appId = (Get-StartApps | Where-Object { $_.AppID -like 'OpenAI.Codex*' } | Select-Object -First 1 -ExpandProperty AppID); "
        ps_cmd += "$chat = @(Get-Process ChatGPT | Where-Object { $_.Path -like '*OpenAI.Codex*' }); "
        ps_cmd += "$chat | Stop-Process -Force; "
        ps_cmd += "$cx = @(Get-Process codex -ErrorAction SilentlyContinue); "
        ps_cmd += "$cx | Stop-Process -Force; "
        ps_cmd += "Start-Sleep -Milliseconds 1200; "
        ps_cmd += "if ($appId) { Start-Process explorer.exe -ArgumentList ('shell:AppsFolder\\' + $appId); }"
        subprocess.Popen(
            ['powershell.exe', '-NoProfile', '-Command', ps_cmd],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        QTimer.singleShot(4000, self._on_restart_done)

    def _on_restart_done(self):
        self._set_status('Codex 已重启', 'success')
        self._set_buttons_enabled(True)

    def _show_tutorial(self):
        if self._tutorial is None:
            self._tutorial = TutorialDialog(self)
        self._tutorial.show()
        self._tutorial.raise_()

    def _setup_tray(self):
        try:
            self._tray = QSystemTrayIcon(self._make_icon(), self)
            self._tray.setToolTip(APP_NAME)
            menu = QMenu()
            a1 = QAction('显示', self)
            a1.triggered.connect(self.showNormal)
            a2 = QAction('退出', self)
            a2.triggered.connect(self._quit)
            menu.addAction(a1)
            menu.addSeparator()
            menu.addAction(a2)
            self._tray.setContextMenu(menu)
            self._tray.activated.connect(self._on_tray_activated)
            self._tray.show()
        except Exception:
            self._tray = None

    def _make_icon(self):
        pm = QPixmap(64, 64)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor(ACCENT))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(4, 4, 56, 56, 14, 14)
        f = QFont(FONT_UI, 22)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QPen(QColor('#FFFFFF')))
        p.drawText(pm.rect(), Qt.AlignCenter, '寒')
        p.end()
        return QIcon(pm)

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self.showNormal()

    def _quit(self):
        if self._tray:
            self._tray.hide()
        QApplication.instance().quit()

    def closeEvent(self, event):
        if self._tray and self.isVisible():
            event.ignore()
            self.hide()
        else:
            event.accept()

    def auto_install(self):
        cp = os.path.join(self._config_dir(), 'config.toml')
        if not os.path.exists(cp):
            self._run_install('寒霜-变体B-v3-英文.md')
            return
        with open(cp, 'r', encoding='utf-8') as f:
            ct = f.read()
        if '寒霜-flash-v2' in ct:
            self._run_install('寒霜-flash-v2.md')
        elif '寒霜-变体B' in ct:
            self._run_install('寒霜-变体B-v3-英文.md')
        else:
            self._run_install('寒霜-变体B-v3-英文.md')


def main():
    if not _security_gate():
        sys.exit(1)
    app = QApplication(sys.argv)
    _create_check_png()
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    probe = QLocalSocket()
    probe.connectToServer('fj_codex_tool_v2')
    if probe.waitForConnected(150):
        probe.disconnectFromServer()
        return 0
    server = QLocalServer()
    server.removeServer('fj_codex_tool_v2')
    server.listen('fj_codex_tool_v2')
    agree = AgreementDialog()
    win = None

    def on_agreed():
        nonlocal win
        win = MainWindow()
        win.show()
        if win._auto_check.isChecked():
            QTimer.singleShot(500, win.auto_install)

    agree.agreed.connect(on_agreed)
    agree.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    sys.exit(main())
