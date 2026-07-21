"""Switchable palettes (dark / light) and stylesheet builder.

Deliberately restrained: neutral surfaces, one red accent used only for
state (active nav item, toggle-on, primary action). No gradients.

Custom-painted widgets read the module-level color names at paint time,
so set_theme() + app.setStyleSheet(build_qss()) + a global update()
switches everything live.
"""

from __future__ import annotations

import json
from pathlib import Path

SETTINGS_FILE = Path.home() / ".config" / "nitrotool" / "settings.json"

PALETTES = {
    "dark": dict(
        BG="#0e1013",
        PANEL="#15181d",
        PANEL_HI="#1b1f26",
        BORDER="#262b33",
        TEXT="#e8eaed",
        MUTED="#8b93a1",
        ACCENT="#e2382c",
        ACCENT_DIM="#7a2620",
        OK="#3ecf6f",
        KNOB="#ffffff",
        BLUE="#4da3ff",
        YELLOW="#f0b429",
    ),
    "light": dict(
        BG="#f2f3f5",
        PANEL="#ffffff",
        PANEL_HI="#e9ebee",
        BORDER="#d7dbe0",
        TEXT="#1b1e22",
        MUTED="#68717d",
        ACCENT="#d32f24",
        ACCENT_DIM="#f0b9b5",
        OK="#1f9d4d",
        KNOB="#ffffff",
        BLUE="#1f6fce",
        YELLOW="#b47d00",
    ),
}

current = "dark"

# Module-level color names, refreshed by set_theme()
BG = PANEL = PANEL_HI = BORDER = TEXT = MUTED = ""
ACCENT = ACCENT_DIM = OK = KNOB = BLUE = YELLOW = ""


def set_theme(name: str) -> None:
    global current
    if name not in PALETTES:
        name = "dark"
    current = name
    globals().update(PALETTES[name])


def load_saved_theme() -> str:
    try:
        return json.loads(SETTINGS_FILE.read_text()).get("theme", "dark")
    except (OSError, ValueError):
        return "dark"


def save_theme(name: str) -> None:
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(SETTINGS_FILE.read_text())
    except (OSError, ValueError):
        data = {}
    data["theme"] = name
    SETTINGS_FILE.write_text(json.dumps(data, indent=2))


set_theme(load_saved_theme())


def build_qss() -> str:
    return f"""
* {{
    font-family: "Ubuntu", "Inter", "Segoe UI", sans-serif;
    outline: none;
}}
QMainWindow, QWidget#root, QDialog, QMessageBox {{
    background: {BG};
}}
QStackedWidget, QScrollArea {{
    background: {BG};
    border: none;
}}
QWidget#page {{
    background: {BG};
}}
QLabel {{
    color: {TEXT};
    background: transparent;
}}
QLabel[class="muted"] {{
    color: {MUTED};
}}
QLabel[class="pagetitle"] {{
    font-size: 20px;
    font-weight: 600;
}}

/* ---- banner ---- */
QFrame#banner {{
    background: {PANEL_HI};
    border: 1px solid {BORDER};
    border-radius: 0;
    border-left: 3px solid {ACCENT};
}}

/* ---- sidebar ---- */
QWidget#sidebar {{
    background: {PANEL};
    border-right: 1px solid {BORDER};
}}
QPushButton[class="nav"] {{
    color: {MUTED};
    background: transparent;
    border: none;
    border-radius: 8px;
    padding: 10px 14px;
    text-align: left;
    font-size: 14px;
}}
QPushButton[class="nav"]:hover {{
    background: {PANEL_HI};
    color: {TEXT};
}}
QPushButton[class="nav"]:checked {{
    background: {PANEL_HI};
    color: {TEXT};
    border-left: 3px solid {ACCENT};
    padding-left: 11px;
}}
QLabel#brand {{
    font-size: 15px;
    font-weight: 700;
    color: {TEXT};
    letter-spacing: 0.5px;
}}
QLabel#brandsub {{
    font-size: 11px;
    color: {MUTED};
}}

/* ---- cards ---- */
QFrame[class="card"] {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
QLabel[class="cardtitle"] {{
    font-size: 13px;
    font-weight: 600;
    color: {MUTED};
    letter-spacing: 0.8px;
}}

/* ---- status chips ---- */
QLabel[class="chip"] {{
    border-radius: 9px;
    padding: 2px 10px;
    font-size: 11px;
    font-weight: 600;
}}
QLabel[chip="ok"] {{
    background: {OK};
    color: {PANEL};
}}
QLabel[chip="temp"] {{
    background: {ACCENT_DIM};
    color: {TEXT};
}}
QLabel[chip="off"] {{
    background: {BORDER};
    color: {MUTED};
}}

/* ---- controls ---- */
QSlider {{
    min-height: 24px;   /* room for the 16px handle — prevents clipping */
}}
QSlider::groove:horizontal {{
    height: 4px;
    background: {BORDER};
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: {ACCENT};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    width: 16px;
    height: 16px;
    margin: -6px 0;
    border-radius: 8px;
    background: {TEXT};
}}
QSlider::sub-page:horizontal:disabled {{
    background: {BORDER};
}}
QSlider::handle:horizontal:disabled {{
    background: {MUTED};
}}

QPushButton[class="mode"] {{
    color: {MUTED};
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 13px;
}}
QPushButton[class="mode"]:hover {{
    color: {TEXT};
    background: {PANEL_HI};
}}
QPushButton[class="mode"]:checked {{
    color: {TEXT};
    border: 1px solid {ACCENT};
    background: {PANEL_HI};
}}
QPushButton[class="mode"]:disabled {{
    color: {BORDER};
    border: 1px solid {BORDER};
    background: {PANEL};
}}
QLabel:disabled {{
    color: {BORDER};
}}

QPushButton[class="action"] {{
    color: {TEXT};
    background: {PANEL_HI};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 7px 16px;
    font-size: 13px;
}}
QPushButton[class="action"]:hover {{
    border-color: {MUTED};
}}
QPushButton[class="action"]:disabled {{
    color: {MUTED};
    background: {PANEL};
}}
QPushButton[class="primary"] {{
    color: #ffffff;
    background: {ACCENT};
    border: none;
    border-radius: 8px;
    padding: 8px 18px;
    font-size: 13px;
    font-weight: 600;
}}
QPushButton[class="primary"]:hover {{
    background: {"#c9271c" if current == "light" else "#ef4437"};
}}
QPushButton[class="primary"]:disabled {{
    background: {BORDER};
    color: {MUTED};
}}

QCheckBox {{
    color: {TEXT};
    font-size: 13px;
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 5px;
    border: 1px solid {BORDER};
    background: {PANEL_HI};
}}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
}}

QComboBox {{
    color: {TEXT};
    background: {PANEL_HI};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 6px 12px;
    font-size: 13px;
}}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {PANEL_HI};
    color: {TEXT};
    border: 1px solid {BORDER};
    selection-background-color: {ACCENT_DIM};
}}

QLineEdit {{
    color: {TEXT};
    background: {PANEL_HI};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 6px 10px;
    font-size: 13px;
}}
QLineEdit:focus {{ border-color: {MUTED}; }}

QPlainTextEdit {{
    color: {MUTED};
    background: {BG};
    border: 1px solid {BORDER};
    border-radius: 8px;
    font-family: "Ubuntu Mono", monospace;
    font-size: 12px;
}}

QScrollBar:vertical {{
    background: transparent; width: 8px; margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {BORDER}; border-radius: 4px; min-height: 30px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}

QToolTip {{
    color: {TEXT};
    background: {PANEL_HI};
    border: 1px solid {BORDER};
    padding: 4px 8px;
}}

QMenu {{
    background: {PANEL_HI};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 18px;
    border-radius: 6px;
}}
QMenu::item:selected {{
    background: {ACCENT_DIM};
}}
QMenu::separator {{
    height: 1px;
    background: {BORDER};
    margin: 4px 8px;
}}
"""
