#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, sys, subprocess, json, re
from PySide6.QtCore import Qt, QTimer, QProcess, QUrl, Signal, QObject, QPropertyAnimation, Property, QEasingCurve
from PySide6.QtGui import QColor, QPainter, QPen, QIcon, QPixmap, QAction, QDesktopServices, QFont
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QSystemTrayIcon, QMenu, QScrollArea, QFrame, QGraphicsDropShadowEffect, QCheckBox, QAbstractButton, QDialog)

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

APP_NAME = "寒霜破甲工具"
APP_VERSION = "V3.0"
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
    "codex 顶级全破 就是 v4 pro 和 gpt6.0 用的了 那种顶尖模型\n\n"
    "执行完了 输入激活词「寒霜」 显示\u201c已成功破甲\u201d就是可以了\n\n"
    "ZCode 注入：点 ZCode 卡片安装，自动写入提示词 + 系统记忆 + 系统提示词，重启 ZCode 生效\n\n"
    "如果遇到不行的情况 重新开对话 重新发就行 有时候会概率拒绝的 正常\n"
    "一般执行一次之后第一次发是会拒绝 重新开个对话就可以了\n"
    "上下文太长被压缩后 工具会自动检测并弹提示 你发「寒霜」重新激活就行\n\n"
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
QFrame.versionRow { background: #FFFFFF; border: 1.5px solid #E2E6ED; border-radius: 10px; }
QFrame.versionRow:hover { border: 1.5px solid #2F6FED; background: #F7FAFF; }
QFrame.versionRowSel { background: #EBF0FE; border: 1.5px solid #2F6FED; border-radius: 10px; }
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


class ToggleSwitch(QAbstractButton):
    """滑动开关控件：勾选=启用，取消=禁用，带平滑滑动动画。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(48, 26)
        self._offset = 0.0
        self._anim = QPropertyAnimation(self, b'offset', self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animate)

    def offset(self):
        return self._offset

    def setOffset(self, v):
        self._offset = v
        self.update()

    offset = Property(float, offset, setOffset)

    def _animate(self, checked):
        self._anim.stop()
        self._anim.setStartValue(self._offset)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        r = h / 2.0
        # 轨道
        if self.isChecked():
            track = QColor(ACCENT)
        else:
            track = QColor('#D0D5DD')
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(0, 0, w, h, r, r)
        # 滑块
        pad = 3
        d = h - pad * 2
        x = pad + self._offset * (w - d - pad * 2)
        p.setBrush(QColor('#FFFFFF'))
        p.drawEllipse(int(round(x)), pad, d, d)
        p.end()

class SkillsManagerDialog(QWidget):
    """List all Codex skills with enable/disable toggles."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Skills 管理')
        self.setWindowFlags(Qt.Dialog | Qt.WindowStaysOnTopHint)
        self.setFixedSize(620, 640)
        self.setStyleSheet(STYLESHEET)
        if parent:
            sg = parent.screen().availableGeometry()
        else:
            sg = QApplication.primaryScreen().availableGeometry()
        x = (sg.width() - self.width()) // 2 + sg.x()
        y = (sg.height() - self.height()) // 2 + sg.y()
        self.move(x, y)
        self._checks = {}   # name -> ToggleSwitch
        self._build()
        self._load()

    # ---------- config.toml 读写 ----------

    def _config_path(self):
        return os.path.join(os.path.expanduser('~'), '.codex', 'config.toml')

    def _read_disabled(self):
        """Parse config.toml [[skills.config]] blocks -> set of disabled skill names."""
        disabled = set()
        cp = self._config_path()
        if not os.path.exists(cp):
            return disabled
        try:
            with open(cp, 'r', encoding='utf-8') as f:
                text = f.read()
        except Exception:
            return disabled
        # 按 [[skills.config]] 块切分
        blocks = re.split(r'(?m)^\[\[skills\.config\]\]\s*$', text)
        for blk in blocks[1:]:
            m_path = re.search(r'(?m)^\s*path\s*=\s*"([^"]+)"', blk)
            m_en = re.search(r'(?m)^\s*enabled\s*=\s*(true|false)', blk)
            if not m_path:
                continue
            path = m_path.group(1).replace('\\', '/')
            enabled = (m_en.group(1) == 'true') if m_en else True
            if not enabled:
                # 从 path 提取 skill 目录名
                name = os.path.basename(os.path.dirname(path))
                if name:
                    disabled.add(name)
        return disabled

    def _write_disabled(self, disabled):
        """Rewrite config.toml [[skills.config]] blocks for the given disabled set."""
        cp = self._config_path()
        if not os.path.exists(cp):
            return False
        try:
            with open(cp, 'r', encoding='utf-8') as f:
                text = f.read()
        except Exception:
            return False
        # 删除所有现有 [[skills.config]] 块
        text = re.sub(r'(?m)^\[\[skills\.config\]\]\s*$.*?(?=^\[\[|\Z)', '', text, flags=re.S)
        text = text.rstrip() + '\n'
        # 追加禁用的 skills
        for name in sorted(disabled):
            sk = os.path.join(os.path.expanduser('~'), '.codex', 'skills', name, 'SKILL.md')
            p = sk.replace('\\', '/')
            text += '\n[[skills.config]]\npath = "' + p + '"\nenabled = false\n'
        try:
            with open(cp, 'w', encoding='utf-8') as f:
                f.write(text)
            return True
        except Exception:
            return False

    # ---------- UI ----------

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 22)
        lay.setSpacing(12)
        title = QLabel('Skills 管理')
        title.setStyleSheet('font-size: 20px; font-weight: 700; color: ' + TEXT_PRIMARY + ';')
        lay.addWidget(title)
        self._stat = QLabel('')
        self._stat.setStyleSheet('font-size: 13px; color: ' + TEXT_SECONDARY + ';')
        lay.addWidget(self._stat)
        div = QFrame()
        div.setFrameShape(QFrame.HLine)
        div.setStyleSheet('background: ' + BORDER_LIGHT + '; max-height: 1px; border: none;')
        lay.addWidget(div)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self._list_widget = QWidget()
        self._list_lay = QVBoxLayout(self._list_widget)
        self._list_lay.setContentsMargins(4, 4, 4, 4)
        self._list_lay.setSpacing(2)
        scroll.setWidget(self._list_widget)
        lay.addWidget(scroll, 1)
        # 底部按钮行
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        b_all = QPushButton('全选')
        b_all.setProperty('class', 'btnSecondary')
        b_all.setFixedHeight(38)
        b_all.clicked.connect(lambda: self._set_all(True))
        btn_row.addWidget(b_all)
        b_none = QPushButton('全不选')
        b_none.setProperty('class', 'btnSecondary')
        b_none.setFixedHeight(38)
        b_none.clicked.connect(lambda: self._set_all(False))
        btn_row.addWidget(b_none)
        btn_row.addStretch(1)
        b_save = QPushButton('保存')
        b_save.setProperty('class', 'btnPrimary')
        b_save.setFixedHeight(38)
        b_save.clicked.connect(self._save)
        btn_row.addWidget(b_save)
        b_close = QPushButton('关闭')
        b_close.setProperty('class', 'btnSecondary')
        b_close.setFixedHeight(38)
        b_close.clicked.connect(self.close)
        btn_row.addWidget(b_close)
        lay.addLayout(btn_row)
        tip = QLabel('勾选 = 启用，取消 = 禁用。保存后需重启 Codex 生效。')
        tip.setStyleSheet('font-size: 12px; color: ' + TEXT_HINT + ';')
        lay.addWidget(tip)

    def _load(self):
        # 清空旧列表
        while self._list_lay.count():
            item = self._list_lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._checks = {}
        disabled = self._read_disabled()
        sk_dir = os.path.join(os.path.expanduser('~'), '.codex', 'skills')
        names = []
        if os.path.isdir(sk_dir):
            for d in sorted(os.listdir(sk_dir)):
                full = os.path.join(sk_dir, d)
                if os.path.isdir(full) and os.path.exists(os.path.join(full, 'SKILL.md')):
                    names.append(d)
        for name in names:
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(8, 4, 8, 4)
            rl.setSpacing(10)
            cb = ToggleSwitch()
            cb.setChecked(name not in disabled)
            self._checks[name] = cb
            rl.addWidget(cb)
            lbl = QLabel(name)
            lbl.setStyleSheet('font-size: 14px; color: ' + TEXT_PRIMARY + '; background: transparent;')
            rl.addWidget(lbl)
            rl.addStretch(1)
            # 读取 description 作为提示
            desc = ''
            try:
                with open(os.path.join(sk_dir, name, 'SKILL.md'), 'r', encoding='utf-8', errors='ignore') as f:
                    head = f.read(600)
                m = re.search(r'description:\s*(.+)', head)
                if m:
                    desc = m.group(1).strip()[:80]
            except Exception:
                pass
            if desc:
                dl = QLabel(desc)
                dl.setStyleSheet('font-size: 11px; color: ' + TEXT_HINT + '; background: transparent;')
                dl.setWordWrap(True)
                rl.addWidget(dl, 1)
            self._list_lay.addWidget(row)
        self._list_lay.addStretch(1)
        self._update_stat(names)

    def _update_stat(self, names):
        on = sum(1 for n in names if self._checks.get(n) and self._checks[n].isChecked())
        self._stat.setText('共 %d 个 · 启用 %d · 禁用 %d' % (len(names), on, len(names) - on))

    def _set_all(self, val):
        for cb in self._checks.values():
            cb.setChecked(val)
        self._update_stat(list(self._checks.keys()))

    def _save(self):
        disabled = set()
        for name, cb in self._checks.items():
            if not cb.isChecked():
                disabled.add(name)
        ok = self._write_disabled(disabled)
        if ok:
            self._stat.setText('已保存 - 重启 Codex 生效')
            self._stat.setStyleSheet('font-size: 13px; color: ' + SUCCESS + '; font-weight: 600;')
        else:
            self._stat.setText('保存失败 - 无法写入 config.toml')
            self._stat.setStyleSheet('font-size: 13px; color: ' + DANGER + '; font-weight: 600;')
class VersionRow(QFrame):
    """版本选择对话框中的单行版本卡片，点击选中。"""
    clicked = Signal()

    def __init__(self, name, desc, recommended=False, parent=None):
        super().__init__(parent)
        self.setProperty('class', 'versionRow')
        self.setCursor(Qt.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(8)
        nm = QLabel(name)
        nm.setStyleSheet('font-size: 14px; font-weight: 700; color: ' + TEXT_PRIMARY + '; background: transparent;')
        top.addWidget(nm)
        top.addStretch(1)
        if recommended:
            rec = QLabel('推荐')
            rec.setStyleSheet(
                'font-size: 11px; font-weight: 600; color: ' + ACCENT + '; background: ' + ACCENT_LIGHT +
                '; border-radius: 8px; padding: 2px 8px;')
            top.addWidget(rec)
        lay.addLayout(top)
        ds = QLabel(desc)
        ds.setWordWrap(True)
        ds.setStyleSheet('font-size: 12px; color: ' + TEXT_SECONDARY + '; background: transparent;')
        lay.addWidget(ds)

    def mousePressEvent(self, event):
        self.clicked.emit()
        super().mousePressEvent(event)


class VersionDialog(QDialog):
    """点击「安装」后弹出的版本选择对话框。"""

    def __init__(self, title, versions, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setFixedWidth(480)
        self._selected = None
        self._rows = []
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(10)
        tip = QLabel('选择要安装的版本：')
        tip.setStyleSheet('font-size: 13px; font-weight: 600; color: ' + TEXT_PRIMARY + '; background: transparent;')
        root.addWidget(tip)
        for name, desc, pf, rec in versions:
            row = VersionRow(name, desc, rec)
            row.clicked.connect(lambda pf=pf, r=row: self._select(pf, r))
            root.addWidget(row)
            self._rows.append(row)
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        cancel = QPushButton('取消')
        cancel.setProperty('class', 'btnSecondary')
        cancel.setFixedHeight(40)
        cancel.clicked.connect(self.reject)
        btn_row.addWidget(cancel, 1)
        self._ok = QPushButton('安装')
        self._ok.setProperty('class', 'btnPrimary')
        self._ok.setFixedHeight(40)
        self._ok.setEnabled(False)
        self._ok.clicked.connect(self.accept)
        btn_row.addWidget(self._ok, 1)
        root.addLayout(btn_row)

    def _select(self, pf, row):
        self._selected = pf
        for r in self._rows:
            r.setProperty('class', 'versionRowSel' if r is row else 'versionRow')
            r.style().unpolish(r)
            r.style().polish(r)
        self._ok.setEnabled(True)

    def selected(self):
        return self._selected


class InstallCard(QFrame):
    install_requested = Signal(str)

    def __init__(self, title, desc, prompt_filename=None, versions=None, parent=None):
        super().__init__(parent)
        self._prompt_filename = prompt_filename
        self._versions = versions or []
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
            '; border-radius: 4px; padding: 4px 8px;')
        top.addWidget(self._tag)
        lay.addLayout(top)
        desc_label = QLabel(desc)
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet('font-size: 13px; color: ' + TEXT_SECONDARY + '; background: transparent;')
        lay.addWidget(desc_label)
        self._btn = QPushButton('选择版本' if self._versions else '安装')
        self._btn.setProperty('class', 'btnPrimary')
        self._btn.setFixedHeight(46)
        if self._versions:
            self._btn.clicked.connect(self._choose_version)
        else:
            self._btn.clicked.connect(lambda: self.install_requested.emit(self._prompt_filename))
        lay.addWidget(self._btn)

    def _choose_version(self):
        dlg = VersionDialog('选择版本', self._versions, self)
        if dlg.exec() == QDialog.Accepted and dlg.selected():
            self.install_requested.emit(dlg.selected())

    def set_installed(self, ok, version_name=None):
        if ok:
            self._tag.setText('已安装 ' + version_name if version_name else '已安装 ✓')
            self._tag.setStyleSheet(
                'font-size: 12px; font-weight: 600; color: ' + SUCCESS + '; background: ' + SUCCESS_LIGHT +
                '; border-radius: 4px; padding: 4px 8px;')
            self._btn.setText('重新安装')
        else:
            self._tag.setText('未安装')
            self._tag.setStyleSheet(
                'font-size: 12px; font-weight: 600; color: ' + TEXT_HINT + '; background: ' + BG_HOVER +
                '; border-radius: 4px; padding: 4px 8px;')
            self._btn.setText('选择版本' if self._versions else '安装')


class CompactionWatcher(QObject):
    """Watch Codex session files for context compaction and notify the user."""
    compacted = Signal(str)

    MARKERS = (
        'compacted', 'compaction', 'summary of the conversation',
        'conversation summary', '对话已压缩', '上下文已压缩', '对话摘要',
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sessions_dir = os.path.join(os.path.expanduser('~'), '.codex', 'sessions')
        self._known = {}   # path -> (size, pos)
        self._drop = {}    # path -> [dropped_size, remaining_polls]
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(5000)

    def _session_files(self):
        if not os.path.isdir(self._sessions_dir):
            return []
        out = []
        for root, _dirs, files in os.walk(self._sessions_dir):
            for fn in files:
                if fn.startswith('rollout-') and fn.endswith('.jsonl'):
                    out.append(os.path.join(root, fn))
        return out

    def _has_marker(self, text):
        # Only system messages carry compaction summaries; ignore user/assistant text.
        import re as _re
        for line in text.splitlines():
            if not _re.search(r'"role"\s*:\s*"system"', line):
                continue
            low = line.lower()
            if any(m in low for m in self.MARKERS):
                return True
        return False

    def _poll(self):
        try:
            files = self._session_files()
            for p in files:
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                size = st.st_size
                prev = self._known.get(p)
                if prev is None:
                    self._known[p] = (size, size)
                    continue
                prev_size, prev_pos = prev
                emit = False
                # Signal A: new system message contains a compaction marker (single hit)
                if size > prev_pos:
                    try:
                        with open(p, 'r', encoding='utf-8', errors='ignore') as f:
                            f.seek(prev_pos)
                            new = f.read()
                        if self._has_marker(new):
                            emit = True
                    except OSError:
                        pass
                # Signal B: size drop; confirm if the file stays small on a later poll
                if not emit:
                    if prev_size > 20000 and 0 < size < prev_size * 0.6:
                        self._drop[p] = [size, 6]
                    elif p in self._drop:
                        d = self._drop[p]
                        if size <= d[0]:
                            emit = True
                            self._drop.pop(p, None)
                        else:
                            d[1] -= 1
                            if d[1] <= 0:
                                self._drop.pop(p, None)
                if emit:
                    self.compacted.emit(p)
                self._known[p] = (size, size)
            for p in list(self._known):
                if not os.path.exists(p):
                    del self._known[p]
                    self._drop.pop(p, None)
        except Exception:
            pass


class MainWindow(QWidget):
    def __init__(self):
        super().__init__(None)
        self.setObjectName('mainWindow')
        self.setWindowTitle(APP_NAME)
        self.setWindowFlags(Qt.Window)
        self.setFixedSize(1080, 660)
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
        self._watcher = CompactionWatcher(self)
        self._watcher.compacted.connect(self._on_compacted)

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
        self._card_zcode._btn.setEnabled(enabled)
        self._card_claude._btn.setEnabled(enabled)
        self._btn_restart.setEnabled(enabled)
        self._btn_reinject.setEnabled(enabled)
        self._btn_uninstall.setEnabled(enabled)
        self._btn_uninstall_zcode.setEnabled(enabled)
        self._btn_uninstall_claude.setEnabled(enabled)

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

        # 主内容区（横向三栏：Codex 顶尖破甲 / ZCode 注入 / Claude 注入）
        content = QHBoxLayout()
        content.setSpacing(16)
        col_codex = QVBoxLayout()
        col_codex.setSpacing(8)
        sec_codex = QLabel('Codex 顶尖模型')
        sec_codex.setStyleSheet('font-size: 14px; font-weight: 600; color: ' + TEXT_SECONDARY + ';')
        col_codex.addWidget(sec_codex)
        self._card_codex = InstallCard(
            '顶尖破甲',
            '适用于 GPT-6.0 / v4 Pro 等顶级模型 · 点击选择版本',
            versions=[
                ('顶尖破甲 V2', '完整 CTF Lab 2.0 规范 · 身份路由 + 交付标准 + 压缩防护', '寒霜v1.2.md', True),
                ('顶尖破甲 V3', '寒霜工作规范 · 硬拒绝场景覆盖 + 拒绝话术全清单 + 过程进度播报', '寒霜v3.md', False),
                ('顶尖破甲 v1', '旧版顶尖提示词 · 完整工程规范 · 项目类型分类 + 两阶段交付', '寒霜-变体B-v3-英文.md', False),
            ]
        )
        self._card_codex.install_requested.connect(self._run_install)
        col_codex.addWidget(self._card_codex, 1)
        content.addLayout(col_codex, 1)
        col_zcode = QVBoxLayout()
        col_zcode.setSpacing(8)
        sec_zcode = QLabel('ZCode 注入')
        sec_zcode.setStyleSheet('font-size: 14px; font-weight: 600; color: ' + TEXT_SECONDARY + ';')
        col_zcode.addWidget(sec_zcode)
        self._card_zcode = InstallCard(
            'zcode破甲v2',
            '提示词 + 系统记忆 + 系统提示词',
            'zcode'
        )
        self._card_zcode.install_requested.connect(self._run_zcode_install)
        col_zcode.addWidget(self._card_zcode, 1)
        content.addLayout(col_zcode, 1)
        col_claude = QVBoxLayout()
        col_claude.setSpacing(8)
        sec_claude = QLabel('Claude 注入')
        sec_claude.setStyleSheet('font-size: 14px; font-weight: 600; color: ' + TEXT_SECONDARY + ';')
        col_claude.addWidget(sec_claude)
        self._card_claude = InstallCard(
            'Claude 注入',
            '寒霜工作规范注入 ~/.claude/CLAUDE.md · 备份原文件可卸载恢复',
            'claude'
        )
        self._card_claude.install_requested.connect(self._run_claude_install)
        col_claude.addWidget(self._card_claude, 1)
        content.addLayout(col_claude, 1)
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
        self._btn_skills = QPushButton('Skills 管理')
        self._btn_skills.setProperty('class', 'btnSecondary')
        self._btn_skills.setFixedHeight(46)
        self._btn_skills.clicked.connect(self._show_skills_manager)
        btn_row.addWidget(self._btn_skills, 1)
        self._btn_reinject = QPushButton('重新注入')
        self._btn_reinject.setProperty('class', 'btnSecondary')
        self._btn_reinject.setFixedHeight(46)
        self._btn_reinject.clicked.connect(self._reinject)
        btn_row.addWidget(self._btn_reinject, 1)
        self._btn_uninstall = QPushButton('卸载')
        self._btn_uninstall.setProperty('class', 'btnDanger')
        self._btn_uninstall.setFixedHeight(46)
        self._btn_uninstall.clicked.connect(self._uninstall)
        btn_row.addWidget(self._btn_uninstall, 1)
        self._btn_uninstall_zcode = QPushButton('卸载 ZCode')
        self._btn_uninstall_zcode.setProperty('class', 'btnDanger')
        self._btn_uninstall_zcode.setFixedHeight(46)
        self._btn_uninstall_zcode.clicked.connect(self._uninstall_zcode)
        btn_row.addWidget(self._btn_uninstall_zcode, 1)
        self._btn_uninstall_claude = QPushButton('卸载 Claude')
        self._btn_uninstall_claude.setProperty('class', 'btnDanger')
        self._btn_uninstall_claude.setFixedHeight(46)
        self._btn_uninstall_claude.clicked.connect(self._uninstall_claude)
        btn_row.addWidget(self._btn_uninstall_claude, 1)
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
        self._watch_label = QLabel('● 压缩守护: 运行中')
        self._watch_label.setStyleSheet('font-size: 12px; color: ' + SUCCESS + ';')
        footer.addWidget(self._watch_label)
        footer.addStretch(1)
        qb = QPushButton('加入QQ群')
        qb.setProperty('class', 'btnLink')
        qb.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(QQ_LINK)))
        footer.addWidget(qb)
        self._btn_quit = QPushButton('退出')
        self._btn_quit.setProperty('class', 'btnDanger')
        self._btn_quit.setFixedHeight(34)
        self._btn_quit.setFixedWidth(72)
        self._btn_quit.clicked.connect(self._quit)
        footer.addWidget(self._btn_quit)
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

    def _run_zcode_install(self, _tag):
        base = _res()
        install_ps1 = os.path.join(base, 'install-zcode.ps1')
        if not os.path.exists(install_ps1):
            self._set_status('找不到 install-zcode.ps1', 'error')
            return
        self._set_status('正在注入 ZCode（提示词 + 记忆 + 系统提示词）...')
        self._set_buttons_enabled(False)
        if self._proc is not None and self._proc.state() != QProcess.NotRunning:
            self._proc.kill()
            self._proc.waitForFinished(2000)
        proc = QProcess(self)
        self._proc = proc
        proc.setWorkingDirectory(base)
        proc.setProcessChannelMode(QProcess.MergedChannels)
        proc.finished.connect(lambda c, s: self._on_zcode_install_done(c, s))
        proc.start('powershell.exe', [
            '-NoProfile', '-ExecutionPolicy', 'RemoteSigned',
            '-File', install_ps1, '-PatchSystemPrompt'
        ])

    def _on_zcode_install_done(self, ec, es):
        self._set_buttons_enabled(True)
        ok = (es == QProcess.NormalExit and ec == 0)
        if ok:
            self._card_zcode.set_installed(True)
            self._set_status('ZCode 注入成功 - 重启 ZCode 生效', 'success')
        else:
            self._set_status('ZCode 注入失败 (退出码 ' + str(ec) + ')', 'error')

    def _run_claude_install(self, _tag):
        base = _res()
        install_ps1 = os.path.join(base, 'install-claude.ps1')
        prompt_path = os.path.join(base, '寒霜v3.md')
        if not os.path.exists(install_ps1):
            self._set_status('找不到 install-claude.ps1', 'error')
            return
        if not os.path.exists(prompt_path):
            self._set_status('找不到 寒霜v3.md', 'error')
            return
        self._set_status('正在注入 Claude（~/.claude/CLAUDE.md）...')
        self._set_buttons_enabled(False)
        if self._proc is not None and self._proc.state() != QProcess.NotRunning:
            self._proc.kill()
            self._proc.waitForFinished(2000)
        proc = QProcess(self)
        self._proc = proc
        proc.setWorkingDirectory(base)
        proc.setProcessChannelMode(QProcess.MergedChannels)
        proc.finished.connect(lambda c, s: self._on_claude_install_done(c, s))
        proc.start('powershell.exe', [
            '-NoProfile', '-ExecutionPolicy', 'RemoteSigned',
            '-File', install_ps1,
            '-SourcePrompt', prompt_path
        ])

    def _on_claude_install_done(self, ec, es):
        self._set_buttons_enabled(True)
        ok = (es == QProcess.NormalExit and ec == 0)
        if ok:
            self._card_claude.set_installed(True)
            self._set_status('Claude 注入成功 - 重启 Claude Code 生效', 'success')
        else:
            self._set_status('Claude 注入失败 (退出码 ' + str(ec) + ')', 'error')

    def _uninstall_claude(self):
        base = _res()
        install_ps1 = os.path.join(base, 'install-claude.ps1')
        if not os.path.exists(install_ps1):
            self._set_status('找不到 install-claude.ps1', 'error')
            return
        self._set_status('正在卸载 Claude 注入...')
        self._set_buttons_enabled(False)
        proc = QProcess(self)
        self._proc = proc
        proc.setWorkingDirectory(base)
        proc.setProcessChannelMode(QProcess.MergedChannels)
        proc.finished.connect(lambda c, s: self._on_claude_uninstall_done(c, s))
        proc.start('powershell.exe', [
            '-NoProfile', '-ExecutionPolicy', 'RemoteSigned',
            '-File', install_ps1, '-Uninstall'
        ])

    def _on_claude_uninstall_done(self, ec, es):
        self._set_buttons_enabled(True)
        self._card_claude.set_installed(False)
        self._set_status('Claude 注入已卸载', 'success')

    def _uninstall_zcode(self):
        base = _res()
        install_ps1 = os.path.join(base, 'install-zcode.ps1')
        if not os.path.exists(install_ps1):
            self._set_status('找不到 install-zcode.ps1', 'error')
            return
        self._set_status('正在卸载 ZCode 注入...')
        self._set_buttons_enabled(False)
        proc = QProcess(self)
        self._proc = proc
        proc.setWorkingDirectory(base)
        proc.setProcessChannelMode(QProcess.MergedChannels)
        proc.finished.connect(lambda c, s: self._on_zcode_uninstall_done(c, s))
        proc.start('powershell.exe', [
            '-NoProfile', '-ExecutionPolicy', 'RemoteSigned',
            '-File', install_ps1, '-Uninstall'
        ])

    def _on_zcode_uninstall_done(self, ec, es):
        self._set_buttons_enabled(True)
        self._card_zcode.set_installed(False)
        self._set_status('ZCode 注入已卸载', 'success')

    def _count_managed_skills(self):
        """Count managed skills currently present in ~/.codex/skills."""
        try:
            base = _res()
            src = os.path.join(base, 'codex-skills')
            if not os.path.isdir(src):
                return 0
            names = [d for d in os.listdir(src)
                     if os.path.isdir(os.path.join(src, d))
                     and os.path.exists(os.path.join(src, d, 'SKILL.md'))]
            sk = os.path.join(self._config_dir(), 'skills')
            if not os.path.isdir(sk):
                return 0
            return sum(1 for n in names if os.path.isdir(os.path.join(sk, n)))
        except Exception:
            return 0
    def _install_codex_memory(self):
        """Install the full AGENTS.md (寒霜v1.2.md) into Codex memories (append, dedupe)."""
        try:
            base = _res()
            prompt_path = os.path.join(base, '寒霜v1.2.md')
            if not os.path.exists(prompt_path):
                return
            codex_mem = os.path.join(self._config_dir(), 'memories')
            os.makedirs(codex_mem, exist_ok=True)
            summary_path = os.path.join(codex_mem, 'memory_summary.md')
            existing = ''
            if os.path.exists(summary_path):
                with open(summary_path, 'r', encoding='utf-8') as f:
                    existing = f.read()
            if '寒霜注入' in existing:
                return  # 已安装过，跳过
            with open(prompt_path, 'r', encoding='utf-8') as f:
                content = f.read()
            additions = ['## Seagull Profile (寒霜注入)\n' + content]
            new_text = existing.rstrip() + '\n\n' + '\n\n'.join(additions) + '\n'
            with open(summary_path, 'w', encoding='utf-8') as f:
                f.write(new_text)
        except Exception:
            pass

    def _on_install_done(self, pf, ec, es):
        self._set_buttons_enabled(True)
        ok = (es == QProcess.NormalExit and ec == 0)
        if ok:
            self._install_codex_memory()
            n = self._count_managed_skills()
            if n > 0:
                self._set_status(pf + ' 破甲成功 - 已启用 ' + str(n) + ' 个 skills - 重启 Codex 生效', 'success')
            else:
                self._set_status(pf + ' 破甲成功 - 重启 Codex 生效', 'success')
            if pf == '寒霜v1.2.md':
                self._card_codex.set_installed(True, 'V2')
            elif pf == '寒霜v3.md':
                self._card_codex.set_installed(True, 'V3')
            elif pf == '寒霜-变体B-v3-英文.md':
                self._card_codex.set_installed(True, 'v1')
        else:
            self._set_status(pf + ' 失败 (退出码 ' + str(ec) + ')', 'error')

    def _reinject(self):
        """Re-run install with the currently active variant (after compaction)."""
        cp = os.path.join(self._config_dir(), 'config.toml')
        if os.path.exists(cp):
            try:
                with open(cp, 'r', encoding='utf-8') as f:
                    ct = f.read()
                if '寒霜v1.2' in ct:
                    self._run_install('寒霜v1.2.md')
                    return
                if '寒霜v3' in ct:
                    self._run_install('寒霜v3.md')
                    return
                if '寒霜-变体B' in ct:
                    self._run_install('寒霜-变体B-v3-英文.md')
                    return
            except Exception:
                pass
        self._run_install('寒霜v1.2.md')

    def _on_compacted(self, path):
        # 防抖：压缩信号可能连续触发，避免重复注入
        if getattr(self, '_reinject_timer', None) is not None and self._reinject_timer.isActive():
            return
        self._set_status('检测到上下文压缩 - 自动重新注入指令，请发送「寒霜」确认激活', 'error')
        if self._tray:
            try:
                self._tray.showMessage(
                    APP_NAME,
                    '上下文已压缩，正在自动重新注入指令。请在 Codex 中发送「寒霜」确认激活。',
                    QSystemTrayIcon.Warning, 6000
                )
            except Exception:
                pass
        # 延迟 1.5 秒后自动重新注入，确保压缩写入完成后再覆盖
        self._reinject_timer = QTimer(self)
        self._reinject_timer.setSingleShot(True)
        self._reinject_timer.timeout.connect(self._reinject)
        self._reinject_timer.start(1500)

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
        # 无论退出码如何，都重新读取 config.toml 判断注入行是否真的被清除
        still_injected = False
        cp = os.path.join(self._config_dir(), 'config.toml')
        if os.path.exists(cp):
            try:
                with open(cp, 'r', encoding='utf-8') as f:
                    ct = f.read()
                still_injected = ('model_instructions_file' in ct
                                  and '寒霜v1.2' in ct)
            except Exception:
                pass
        if not still_injected:
            n = self._count_managed_skills()
            if n > 0:
                self._set_status('已卸载 - 剩余 ' + str(n) + ' 个寒霜 skills 未清理', 'error')
            else:
                self._set_status('已卸载 - skills 已全部移除', 'success')
            self._card_codex.set_installed(False)
        else:
            self._set_status('卸载失败 - config.toml 仍包含注入行', 'error')

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

    def _show_skills_manager(self):
        dlg = SkillsManagerDialog(self)
        dlg.show()
        dlg.raise_()

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
            self._run_install('寒霜v1.2.md')
            return
        with open(cp, 'r', encoding='utf-8') as f:
            ct = f.read()
        if '寒霜v1.2' in ct:
            self._run_install('寒霜v1.2.md')
        else:
            self._run_install('寒霜v1.2.md')


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
