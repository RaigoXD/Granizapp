"""Gráficos livianos dibujados con QPainter (sin dependencias extra)."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from granizapp.core.utils import fmt_money, fmt_number
from granizapp.ui import theme


def _short_money(v: float) -> str:
    v = float(v)
    if abs(v) >= 1_000_000:
        return f"{v / 1_000_000:.1f} M".replace(".", ",")
    if abs(v) >= 1000:
        return f"{v / 1000:.0f} k"
    return f"{v:.0f}"


class BarChart(QWidget):
    """Barras verticales (ventas por día, por hora, por mes)."""

    def __init__(self, parent=None, money: bool = True, height: int = 220):
        super().__init__(parent)
        self.items: list[tuple[str, float]] = []
        self.money = money
        self.highlight: int | None = None
        self.setMinimumHeight(height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)
        self._bars: list[QRectF] = []

    def set_data(self, items: list[tuple[str, float]], highlight: int | None = None):
        self.items = items
        self.highlight = highlight
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        left, right, top, bottom = 46, 8, 14, 26
        plot_w, plot_h = max(1, w - left - right), max(1, h - top - bottom)
        muted = theme.qcolor("muted")
        grid = theme.qcolor("border")
        p.setFont(QFont("Segoe UI", 8))
        if not self.items:
            p.setPen(muted)
            p.drawText(self.rect(), Qt.AlignCenter, "Sin datos en el periodo")
            return
        max_v = max(max(v for _, v in self.items), 1)
        # líneas guía
        for i in range(5):
            y = top + plot_h * i / 4
            p.setPen(QPen(grid, 1))
            p.drawLine(QPointF(left, y), QPointF(w - right, y))
            val = max_v * (1 - i / 4)
            p.setPen(muted)
            p.drawText(QRectF(0, y - 8, left - 6, 16), Qt.AlignRight | Qt.AlignVCenter,
                       _short_money(val) if self.money else fmt_number(val))
        n = len(self.items)
        slot = plot_w / n
        bar_w = max(2.0, min(42.0, slot * 0.7))
        self._bars = []
        step = max(1, int(n / max(1, plot_w / 46)))
        primary = theme.qcolor("primary")
        soft = QColor(primary)
        soft.setAlpha(150)
        for i, (lab, v) in enumerate(self.items):
            x = left + slot * i + (slot - bar_w) / 2
            bh = plot_h * (max(v, 0) / max_v)
            rect = QRectF(x, top + plot_h - bh, bar_w, bh)
            self._bars.append(QRectF(left + slot * i, top, slot, plot_h))
            p.setPen(Qt.NoPen)
            p.setBrush(primary if self.highlight is None or self.highlight == i else soft)
            p.drawRoundedRect(rect, 3, 3)
            if i % step == 0:
                p.setPen(muted)
                p.drawText(QRectF(left + slot * i - 20, h - bottom + 4, slot + 40, 16), Qt.AlignHCenter, lab)

    def mouseMoveEvent(self, e):
        for i, r in enumerate(self._bars):
            if r.contains(e.position()):
                lab, v = self.items[i]
                QToolTip.showText(e.globalPosition().toPoint(), f"{lab}: {fmt_money(v) if self.money else fmt_number(v, 2)}", self)
                return
        QToolTip.hideText()


class HBars(QWidget):
    """Lista de barras horizontales (ranking de productos, gastos por categoría)."""

    def __init__(self, parent=None, money: bool = True, row_h: int = 26, max_rows: int = 10):
        super().__init__(parent)
        self.items: list[tuple[str, float, str]] = []
        self.money = money
        self.row_h = row_h
        self.max_rows = max_rows
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    def set_data(self, items: list[tuple[str, float]] | list[tuple[str, float, str]]):
        norm = []
        for it in items[: self.max_rows]:
            if len(it) == 2:
                norm.append((it[0], it[1], ""))
            else:
                norm.append(it)
        self.items = norm
        self.setMinimumHeight(max(40, len(self.items) * self.row_h + 8))
        self.updateGeometry()
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        muted, text = theme.qcolor("muted"), theme.qcolor("text")
        p.setFont(QFont("Segoe UI", 9))
        if not self.items:
            p.setPen(muted)
            p.drawText(self.rect(), Qt.AlignCenter, "Sin datos")
            return
        w = self.width()
        label_w = min(220, int(w * 0.38))
        value_w = 110
        bar_area = max(10, w - label_w - value_w - 16)
        max_v = max((v for _, v, _ in self.items), default=1) or 1
        primary = theme.qcolor("primary")
        track = theme.qcolor("primary_soft")
        for i, (lab, v, extra) in enumerate(self.items):
            y = 4 + i * self.row_h
            p.setPen(text)
            p.drawText(QRectF(0, y, label_w - 8, self.row_h - 4), Qt.AlignVCenter | Qt.AlignLeft,
                       p.fontMetrics().elidedText(lab, Qt.ElideRight, label_w - 8))
            p.setPen(Qt.NoPen)
            p.setBrush(track)
            p.drawRoundedRect(QRectF(label_w, y + 6, bar_area, self.row_h - 14), 4, 4)
            p.setBrush(primary)
            p.drawRoundedRect(QRectF(label_w, y + 6, bar_area * max(v, 0) / max_v, self.row_h - 14), 4, 4)
            p.setPen(text)
            val = fmt_money(v) if self.money else fmt_number(v, 2)
            p.drawText(QRectF(label_w + bar_area + 6, y, value_w + 8, self.row_h - 4), Qt.AlignVCenter | Qt.AlignRight,
                       val + (f"  {extra}" if extra else ""))
