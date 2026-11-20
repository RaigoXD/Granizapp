"""Tema visual: sobrio, alto contraste, pensado para usar con teclado y mouse en el bar."""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

LIGHT = {
    "bg": "#F4F5F8",
    "surface": "#FFFFFF",
    "surface2": "#F9FAFB",
    "border": "#E2E5EA",
    "text": "#1C1F26",
    "muted": "#6A7280",
    "primary": "#6C4CF1",
    "primary_hover": "#5B3BE2",
    "primary_soft": "#EFEBFF",
    "success": "#178A4C",
    "success_soft": "#E6F6EC",
    "danger": "#C93C3C",
    "danger_soft": "#FCECEC",
    "warning": "#B7791F",
    "warning_soft": "#FFF5E0",
    "sidebar": "#1D1A2C",
    "sidebar_text": "#D9D6E8",
    "sidebar_muted": "#8E89A8",
    "sidebar_active": "#6C4CF1",
    "selection": "#DCD3FF",
}

DARK = {
    "bg": "#131419",
    "surface": "#1C1E25",
    "surface2": "#22252D",
    "border": "#2E323C",
    "text": "#E7E9EE",
    "muted": "#9AA1AD",
    "primary": "#8C74FF",
    "primary_hover": "#9D88FF",
    "primary_soft": "#2B2550",
    "success": "#3CC57A",
    "success_soft": "#183A27",
    "danger": "#FF6B6B",
    "danger_soft": "#3D1D1F",
    "warning": "#F0B44C",
    "warning_soft": "#3B2F17",
    "sidebar": "#0E0F13",
    "sidebar_text": "#D9D6E8",
    "sidebar_muted": "#7D7896",
    "sidebar_active": "#6C4CF1",
    "selection": "#3A3266",
}

_current = dict(LIGHT)


def color(name: str) -> str:
    return _current[name]


def is_dark() -> bool:
    return _current["bg"] == DARK["bg"]


def qcolor(name: str) -> QColor:
    return QColor(_current[name])


QSS = """
* {{ font-family: "Segoe UI", "Inter", sans-serif; }}
QWidget {{ color: {text}; font-size: 10pt; }}
QMainWindow, QDialog, #Page {{ background: {bg}; }}
QToolTip {{ background: {surface}; color: {text}; border: 1px solid {border}; padding: 4px; }}

#Sidebar {{ background: {sidebar}; }}
#Sidebar QLabel#Brand {{ color: white; font-size: 14pt; font-weight: 700; padding: 14px 16px 2px 16px; }}
#Sidebar QLabel#BrandSub {{ color: {sidebar_muted}; font-size: 9pt; padding: 0 16px 10px 16px; }}
#Sidebar QLabel#NavSection {{ color: {sidebar_muted}; font-size: 8pt; font-weight: 700;
    padding: 9px 16px 3px 16px; letter-spacing: 1px; }}
#Sidebar QPushButton {{ background: transparent; color: {sidebar_text}; border: none; text-align: left;
    padding: 6px 14px; border-radius: 6px; margin: 1px 8px; font-size: 10pt; }}
#Sidebar QPushButton#Logout {{ color: {sidebar_muted}; font-size: 9pt; padding: 4px 8px; margin: 0; }}
#Sidebar QLabel#UserName {{ color: {sidebar_text}; font-weight: 600; padding-left: 16px; }}
#Sidebar QPushButton:hover {{ background: rgba(255,255,255,0.07); }}
#Sidebar QPushButton:checked {{ background: {sidebar_active}; color: white; font-weight: 600; }}

QLabel#PageTitle {{ font-size: 17pt; font-weight: 700; }}
QLabel#PageSubtitle {{ color: {muted}; }}
QLabel#Muted {{ color: {muted}; }}
QLabel#Overline {{ color: {muted}; font-size: 8pt; font-weight: 700; letter-spacing: 1px; padding-top: 4px; }}
QLabel#SectionTitle {{ font-size: 11pt; font-weight: 700; }}
QLabel#BigTotal {{ font-size: 28pt; font-weight: 800; color: {text}; }}
QLabel#Money {{ font-weight: 600; }}
QLabel#Danger {{ color: {danger}; font-weight: 600; }}
QLabel#Success {{ color: {success}; font-weight: 600; }}
QLabel#Warning {{ color: {warning}; font-weight: 600; }}
QLabel#Hint {{ color: {muted}; font-size: 9pt; }}
QLabel#Kbd {{ background: {surface2}; border: 1px solid {border}; border-radius: 4px; padding: 1px 5px;
    font-size: 8pt; color: {muted}; }}

QFrame#Card {{ background: {surface}; border: 1px solid {border}; border-radius: 10px; }}
QFrame#KpiCard {{ background: {surface}; border: 1px solid {border}; border-radius: 10px; }}
QLabel#KpiTitle {{ color: {muted}; font-size: 9pt; }}
QLabel#KpiValue {{ font-size: 17pt; font-weight: 700; }}
QLabel#KpiSub {{ color: {muted}; font-size: 8pt; }}
QFrame#HelpBanner {{ background: {primary_soft}; border: 1px solid {primary}; border-radius: 10px; }}
QFrame#HelpBanner QLabel {{ background: transparent; border: none; }}
QLabel#HelpTitle {{ color: {primary}; font-weight: 700; font-size: 10.5pt; }}
QTextBrowser#HelpBrowser {{ background: {surface}; border: 1px solid {border}; border-radius: 8px; padding: 12px; }}
#Sidebar QPushButton#HelpLink {{ color: {sidebar_text}; font-size: 9pt; padding: 4px 8px; margin: 0;
    border: 1px solid rgba(255,255,255,0.18); border-radius: 6px; }}
QFrame#Banner {{ background: {warning_soft}; border: 1px solid {warning}; border-radius: 8px; }}
QFrame#BannerDanger {{ background: {danger_soft}; border: 1px solid {danger}; border-radius: 8px; }}
QFrame#BannerOk {{ background: {success_soft}; border: 1px solid {success}; border-radius: 8px; }}

QPushButton {{ background: {surface}; border: 1px solid {border}; border-radius: 7px; padding: 6px 12px; }}
QPushButton:hover {{ border-color: {primary}; }}
QPushButton:focus {{ border: 2px solid {primary}; }}
QPushButton:disabled {{ color: {muted}; background: {surface2}; }}
QPushButton#Primary {{ background: {primary}; color: white; border: 1px solid {primary}; font-weight: 600; }}
QPushButton#Primary:hover {{ background: {primary_hover}; }}
QPushButton#Danger {{ background: {surface}; color: {danger}; border: 1px solid {danger}; }}
QPushButton#Danger:hover {{ background: {danger_soft}; }}
QPushButton#Big {{ font-size: 12pt; padding: 10px 14px; font-weight: 600; }}
QPushButton#Tile {{ text-align: left; padding: 8px 10px; border-radius: 8px; font-size: 10pt; min-height: 44px; }}
QPushButton#Chip {{ border-radius: 14px; padding: 4px 12px; }}
QPushButton#Chip:checked {{ background: {primary}; color: white; border-color: {primary}; }}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QDateTimeEdit, QTextEdit, QPlainTextEdit {{
    background: {surface}; border: 1px solid {border}; border-radius: 6px; padding: 5px 8px;
    selection-background-color: {primary}; selection-color: white; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QDateEdit:focus, QTextEdit:focus,
QPlainTextEdit:focus {{ border: 2px solid {primary}; }}
QLineEdit#Search {{ font-size: 13pt; padding: 8px 10px; }}
QLineEdit#BigInput {{ font-size: 18pt; padding: 6px 10px; font-weight: 600; }}
QComboBox QAbstractItemView {{ background: {surface}; border: 1px solid {border}; selection-background-color: {selection};
    selection-color: {text}; }}

QTableView, QTreeView, QListView, QListWidget, QTreeWidget, QTableWidget {{ background: {surface}; border: 1px solid {border};
    border-radius: 8px; gridline-color: {border}; selection-background-color: {selection}; selection-color: {text};
    alternate-background-color: {surface2}; outline: 0; }}
QTableView::item, QTreeView::item, QListView::item {{ padding: 3px 6px; }}
QTableView::item:focus {{ border: none; }}
QHeaderView::section {{ background: {surface2}; color: {muted}; border: none; border-bottom: 1px solid {border};
    padding: 6px; font-weight: 600; font-size: 9pt; }}
QTableCornerButton::section {{ background: {surface2}; border: none; }}

QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: transparent; padding: 8px 14px; border: none; border-bottom: 2px solid transparent;
    color: {muted}; font-weight: 600; }}
QTabBar::tab:selected {{ color: {primary}; border-bottom: 2px solid {primary}; }}
QTabBar::tab:hover {{ color: {text}; }}

QGroupBox {{ border: 1px solid {border}; border-radius: 8px; margin-top: 14px; padding: 10px; background: {surface}; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {muted}; font-weight: 600; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 16px; height: 16px; }}
QStatusBar {{ background: {surface}; border-top: 1px solid {border}; color: {muted}; }}
QStatusBar QLabel {{ color: {muted}; padding: 0 8px; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {border}; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; }}
QScrollBar::handle:horizontal {{ background: {border}; border-radius: 5px; min-width: 30px; }}
QMenu {{ background: {surface}; border: 1px solid {border}; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 4px; }}
QMenu::item:selected {{ background: {selection}; color: {text}; }}
QSplitter::handle {{ background: {bg}; }}
"""


def apply_theme(app: QApplication, name: str = "light") -> None:
    global _current
    _current = dict(DARK if name == "dark" else LIGHT)
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(_current["bg"]))
    pal.setColor(QPalette.WindowText, QColor(_current["text"]))
    pal.setColor(QPalette.Base, QColor(_current["surface"]))
    pal.setColor(QPalette.AlternateBase, QColor(_current["surface2"]))
    pal.setColor(QPalette.Text, QColor(_current["text"]))
    pal.setColor(QPalette.Button, QColor(_current["surface"]))
    pal.setColor(QPalette.ButtonText, QColor(_current["text"]))
    pal.setColor(QPalette.Highlight, QColor(_current["primary"]))
    pal.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
    pal.setColor(QPalette.PlaceholderText, QColor(_current["muted"]))
    pal.setColor(QPalette.ToolTipBase, QColor(_current["surface"]))
    pal.setColor(QPalette.ToolTipText, QColor(_current["text"]))
    app.setPalette(pal)
    font = QFont("Segoe UI", 10)
    app.setFont(font)
    app.setStyleSheet(QSS.format(**_current))
