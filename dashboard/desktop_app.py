"""Native, in-place updating desktop dashboard for FocusOS."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from PySide6.QtCore import (
    QEasingCurve,
    QObject,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QSettings,
    QThread,
    Qt,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.focus_runtime import FocusRuntime


HISTORY_LIMIT = 120

# Themes ----------------------------------------------------------------------
DARK: Dict[str, str] = {
    "bg": "#0d1117",
    "surface": "#161b22",
    "surface_alt": "#12171e",
    "border": "#262d38",
    "border_strong": "#30394a",
    "text": "#e6edf3",
    "muted": "#8b97a8",
    "accent": "#2f81f7",
    "accent_hover": "#4893ff",
    "accent_text": "#ffffff",
    "button": "#1c232d",
    "button_hover": "#252e3b",
    "button_off_text": "#4d5766",
    "button_off_bg": "#12171e",
    "green": "#3fb950",
    "amber": "#d29922",
    "red": "#f85149",
    "green_bg": "#12261a",
    "green_border": "#1f4a2b",
    "amber_bg": "#2a2111",
    "amber_border": "#4d3b14",
    "red_bg": "#2d1618",
    "red_border": "#5c2a2e",
    "grid": "#232a35",
    "select": "#1f3a5f",
    "scroll": "#30394a",
    "cpu": "#58a6ff",
    "ram": "#bc8cff",
    "disk": "#e3b341",
    "gpu": "#39c5bb",
}
LIGHT: Dict[str, str] = {
    "bg": "#f4f6f9",
    "surface": "#ffffff",
    "surface_alt": "#f7f9fb",
    "border": "#dde2ea",
    "border_strong": "#c9d1dc",
    "text": "#1f2937",
    "muted": "#667085",
    "accent": "#2563eb",
    "accent_hover": "#1d4fd8",
    "accent_text": "#ffffff",
    "button": "#ffffff",
    "button_hover": "#eef2f7",
    "button_off_text": "#a5aebb",
    "button_off_bg": "#f1f3f6",
    "green": "#16803c",
    "amber": "#b7791f",
    "red": "#d92d20",
    "green_bg": "#e7f6ec",
    "green_border": "#b7e1c3",
    "amber_bg": "#fdf3dc",
    "amber_border": "#f0d89a",
    "red_bg": "#fdecea",
    "red_border": "#f4c2bd",
    "grid": "#e8ecf2",
    "select": "#dbe7fb",
    "scroll": "#c3ccd8",
    "cpu": "#2563eb",
    "ram": "#7c3aed",
    "disk": "#d97706",
    "gpu": "#0d9488",
}
THEMES = {"dark": DARK, "light": LIGHT}

# (series name in history, palette key)
RESOURCE_SERIES = [
    ("CPU %", "cpu"),
    ("RAM %", "ram"),
    ("Disk %", "disk"),
    ("GPU %", "gpu"),
]
PROCESS_SERIES = [
    ("Active", "green"),
    ("Background", "amber"),
    ("Suspended", "red"),
]
CLASS_COLOR_KEYS = {
    "active": "green",
    "foreground": "green",
    "background": "amber",
    "suspended": "red",
}


def build_stylesheet(p: Dict[str, str]) -> str:
    return f"""
QMainWindow, QWidget#dashboardRoot {{
    background: {p['bg']}; color: {p['text']};
    font-family: "Segoe UI", "Inter", "SF Pro Text", "Helvetica Neue", sans-serif;
    font-size: 13px;
}}
QScrollArea {{ border: 0; background: {p['bg']}; }}
QScrollBar:vertical {{ background: transparent; width: 12px; margin: 2px; }}
QScrollBar::handle:vertical {{
    background: {p['scroll']}; border-radius: 4px; min-height: 36px; margin: 0 2px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QLabel {{ color: {p['text']}; background: transparent; }}

QLabel#pageTitle {{ font-size: 22px; font-weight: 700; }}
QLabel#pageSubtitle, QLabel#mutedText {{ color: {p['muted']}; }}
QLabel#clockLabel {{ color: {p['muted']}; font-size: 12px; }}

QLabel#statusBadge {{
    border-radius: 12px; padding: 4px 14px; font-weight: 700; font-size: 12px;
    color: {p['muted']}; background: {p['button']}; border: 1px solid {p['border_strong']};
}}
QLabel#statusBadge[state="running"] {{
    color: {p['green']}; background: {p['green_bg']}; border: 1px solid {p['green_border']};
}}
QLabel#statusBadge[state="paused"] {{
    color: {p['amber']}; background: {p['amber_bg']}; border: 1px solid {p['amber_border']};
}}

QWidget#metricCard, QWidget#surfaceCard, QWidget#tableCard {{
    background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 10px;
}}
QLabel#metricName {{ color: {p['muted']}; font-size: 11px; font-weight: 700; }}
QLabel#metricValue {{ font-size: 28px; font-weight: 600; }}
QLabel#sectionTitle {{ font-size: 14px; font-weight: 700; }}
QLabel#focusApp {{ font-size: 18px; font-weight: 700; }}
QLabel#chip {{
    background: {p['button']}; border: 1px solid {p['border_strong']};
    border-radius: 9px; padding: 2px 10px; color: {p['muted']}; font-size: 12px; font-weight: 600;
}}

QPushButton {{
    background: {p['button']}; border: 1px solid {p['border_strong']}; border-radius: 7px;
    padding: 7px 18px; color: {p['text']}; font-weight: 600; min-height: 18px;
}}
QPushButton:hover {{ background: {p['button_hover']}; }}
QPushButton:disabled {{
    color: {p['button_off_text']}; background: {p['button_off_bg']}; border-color: {p['border']};
}}
QPushButton#primaryButton {{
    background: {p['accent']}; border-color: {p['accent']}; color: {p['accent_text']};
}}
QPushButton#primaryButton:hover {{ background: {p['accent_hover']}; }}
QPushButton#primaryButton:disabled {{
    background: {p['button_off_bg']}; border-color: {p['border']}; color: {p['button_off_text']};
}}
QPushButton#dangerButton {{ color: {p['red']}; border-color: {p['red_border']}; }}
QPushButton#dangerButton:hover {{ background: {p['red_bg']}; }}
QPushButton#dangerButton:disabled {{
    color: {p['button_off_text']}; background: {p['button_off_bg']}; border-color: {p['border']};
}}

QTableWidget {{
    background: transparent; alternate-background-color: {p['surface_alt']};
    border: 0; outline: 0; color: {p['text']};
    selection-background-color: {p['select']}; selection-color: {p['text']};
}}
QTableWidget::item {{ padding: 4px 8px; border: 0; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{
    background: transparent; color: {p['muted']}; padding: 8px;
    border: 0; border-bottom: 1px solid {p['border']}; font-weight: 700; font-size: 12px;
}}
QMessageBox {{ background: {p['surface']}; }}
"""


# Widgets ---------------------------------------------------------------------
class SmoothWheel:
    """Animated wheel scrolling for any scroll bar, with trackpad support.

    handle() returns False when the wheel event should bubble up to the parent
    (the bar cannot move any further in that direction).
    """

    def __init__(self, owner: QObject, bar: Any, duration: int = 220, step: float = 0.9):
        self.bar = bar
        self.step = step
        self._target = 0
        self._anim = QPropertyAnimation(bar, b"value", owner)
        self._anim.setDuration(duration)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def handle(self, event: Any) -> bool:
        bar = self.bar
        if bar.maximum() <= bar.minimum():
            return False

        running = self._anim.state() == QPropertyAnimation.State.Running
        pixel = event.pixelDelta().y()
        if pixel:  # trackpads already deliver smooth per-pixel deltas
            if not running and (
                (pixel > 0 and bar.value() <= bar.minimum())
                or (pixel < 0 and bar.value() >= bar.maximum())
            ):
                return False
            self._anim.stop()
            bar.setValue(bar.value() - pixel)
            return True

        delta = event.angleDelta().y()
        if delta == 0:
            return False

        base = self._target if running else bar.value()
        at_edge = (delta > 0 and base <= bar.minimum()) or (
            delta < 0 and base >= bar.maximum()
        )
        if at_edge:
            return running  # swallow while still animating, otherwise pass to parent

        target = max(bar.minimum(), min(bar.maximum(), int(base - delta * self.step)))
        self._target = target
        self._anim.stop()
        self._anim.setStartValue(bar.value())
        self._anim.setEndValue(target)
        self._anim.start()
        return True


class SmoothScrollArea(QScrollArea):
    """Page scroll area with smooth wheel scrolling."""

    def __init__(self) -> None:
        super().__init__()
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._smooth = SmoothWheel(self, self.verticalScrollBar(), duration=240, step=1.0)

    def wheelEvent(self, event: Any) -> None:
        if self._smooth.handle(event):
            event.accept()
        else:
            event.ignore()


class FlatTable(QTableWidget):
    """Table with its own scroll bar and smooth wheel scrolling.

    When the table is already at its top or bottom, the wheel passes through
    to the page so the whole dashboard keeps scrolling without getting stuck.
    """

    ROW_HEIGHT = 34
    VIEW_HEIGHT = 420

    def __init__(self, rows: int, columns: int) -> None:
        super().__init__(rows, columns)
        self.setVerticalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        self._smooth = SmoothWheel(self, self.verticalScrollBar(), duration=200, step=0.8)

    def wheelEvent(self, event: Any) -> None:
        if self._smooth.handle(event):
            event.accept()
        else:
            event.ignore()


class MetricHistory:
    """Keep a bounded series of system samples for live charts."""

    def __init__(self, limit: int = HISTORY_LIMIT):
        self.limit = limit
        self.samples: List[Dict[str, Any]] = []

    def record(self, state: Dict[str, Any], timestamp: Optional[datetime] = None) -> None:
        self.samples.append(
            {
                "Time": timestamp or datetime.now(),
                "CPU %": float(state.get("cpu_usage", 0.0)),
                "RAM %": float(state.get("ram_usage", 0.0)),
                "Disk %": float(state.get("disk_usage", 0.0)),
                "GPU %": (
                    float(state["gpu_usage"])
                    if state.get("gpu_usage") is not None
                    else None
                ),
                "Active": int(state.get("active_processes", 0)),
                "Background": int(state.get("background_processes", 0)),
                "Suspended": int(state.get("suspended_processes", 0)),
            }
        )
        if len(self.samples) > self.limit:
            del self.samples[:-self.limit]


class MetricChart(QWidget):
    """Plain QPainter line chart: crisp lines, grid, time axis, no fills."""

    def __init__(self, title: str, series: List[tuple[str, str]], fixed_scale: bool):
        super().__init__()
        self.title = title
        self.series = series
        self.fixed_scale = fixed_scale
        self.samples: List[Dict[str, Any]] = []
        self.palette_map: Dict[str, str] = DARK
        self.setMinimumHeight(280)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_theme(self, palette: Dict[str, str]) -> None:
        self.palette_map = palette
        self.update()

    def set_samples(self, samples: List[Dict[str, Any]]) -> None:
        self.samples = samples
        self.update()

    def paintEvent(self, event: Any) -> None:
        del event
        p = self.palette_map
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        card = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(QColor(p["border"]), 1))
        painter.setBrush(QColor(p["surface"]))
        painter.drawRoundedRect(card, 10, 10)

        title_font = QFont(self.font())
        title_font.setPointSize(10)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(QColor(p["text"]))
        painter.drawText(18, 28, self.title)

        small = QFont(self.font())
        small.setPointSize(9)
        painter.setFont(small)
        metrics = painter.fontMetrics()

        left, top, right, bottom = 46, 46, 20, 62
        plot = self.rect().adjusted(left, top, -right, -bottom)

        if not self.samples:
            painter.setPen(QColor(p["muted"]))
            painter.drawText(plot, Qt.AlignmentFlag.AlignCenter, "Waiting for samples...")
            return

        max_value = 100.0
        if not self.fixed_scale:
            observed = [
                float(sample[name])
                for sample in self.samples
                for name, _ in self.series
                if sample.get(name) is not None
            ]
            max_value = float(max(5, int(max(observed, default=0.0) * 1.2) + 1))

        # Horizontal grid and y labels
        for step in range(5):
            y = plot.bottom() - plot.height() * step / 4
            painter.setPen(QPen(QColor(p["grid"]), 1))
            painter.drawLine(plot.left(), round(y), plot.right(), round(y))
            painter.setPen(QColor(p["muted"]))
            painter.drawText(
                QRectF(4, y - 8, left - 10, 16),
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                f"{max_value * step / 4:.0f}",
            )

        # Vertical grid and time labels
        count = len(self.samples)
        ticks = 5
        for tick in range(ticks):
            x = plot.left() + plot.width() * tick / (ticks - 1)
            painter.setPen(QPen(QColor(p["grid"]), 1))
            painter.drawLine(round(x), plot.top(), round(x), plot.bottom())
            index = round((count - 1) * tick / (ticks - 1))
            stamp = self.samples[index].get("Time")
            if isinstance(stamp, datetime):
                text = stamp.strftime("%H:%M:%S")
                width = metrics.horizontalAdvance(text)
                label_x = min(max(x - width / 2, plot.left() - 10), self.width() - right - width + 10)
                painter.setPen(QColor(p["muted"]))
                painter.drawText(QPointF(label_x, plot.bottom() + 18), text)

        # Plot frame
        painter.setPen(QPen(QColor(p["border_strong"]), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(plot)

        # Lines (clipped to the plot area)
        painter.save()
        painter.setClipRect(plot.adjusted(-1, -2, 2, 2))
        latest: Dict[str, Optional[float]] = {}
        for series_name, color_key in self.series:
            color = QColor(p[color_key])
            path = QPainterPath()
            started = False
            last_value: Optional[float] = None
            for index, sample in enumerate(self.samples):
                value = sample.get(series_name)
                if value is None:
                    continue
                x = plot.left() + (
                    plot.width() if count == 1 else plot.width() * index / (count - 1)
                )
                y = plot.bottom() - min(float(value), max_value) / max_value * plot.height()
                if not started:
                    path.moveTo(x, y)
                    started = True
                else:
                    path.lineTo(x, y)
                last_value = float(value)
            latest[series_name] = last_value
            if not started:
                continue
            pen = QPen(color, 1.8)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawPath(path)
        painter.restore()

        # Legend with current values
        legend_x = float(left)
        legend_y = self.height() - 16
        for name, color_key in self.series:
            value = latest.get(name)
            if value is None:
                continue
            color = QColor(p[color_key])
            painter.setPen(QPen(color, 2.5))
            painter.drawLine(QPointF(legend_x, legend_y - 4), QPointF(legend_x + 14, legend_y - 4))
            label = f"{name}  {value:.0f}"
            painter.setPen(QColor(p["text"]))
            painter.drawText(QPointF(legend_x + 20, legend_y), label)
            legend_x += 20 + metrics.horizontalAdvance(label) + 24


class MetricCard(QWidget):
    """KPI card: caption, value and a thin usage bar."""

    def __init__(self, name: str, color_key: str):
        super().__init__()
        self.color_key = color_key
        self.setObjectName("metricCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 16)
        layout.setSpacing(6)

        self.name_label = QLabel(name.upper())
        self.name_label.setObjectName("metricName")
        self.value_label = QLabel("--")
        self.value_label.setObjectName("metricValue")

        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(5)

        layout.addWidget(self.name_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.bar)

    def apply_theme(self, p: Dict[str, str]) -> None:
        self.bar.setStyleSheet(
            f"QProgressBar {{ background: {p['grid']}; border: 0; border-radius: 2px; }}"
            f"QProgressBar::chunk {{ background: {p[self.color_key]}; border-radius: 2px; }}"
        )

    def set_value(self, percent: Optional[float]) -> None:
        if percent is None:
            self.value_label.setText("N/A")
            self.bar.setValue(0)
            return
        self.value_label.setText(f"{percent:.1f}%")
        self.bar.setValue(int(max(0.0, min(percent, 100.0)) * 10))


class DashboardWorker(QObject):
    """Run monitoring and runtime controls away from the UI event loop."""

    operation_completed = Signal(str, object, str)

    def __init__(self, runtime: FocusRuntime):
        super().__init__()
        self.runtime = runtime

    @Slot()
    def refresh(self) -> None:
        try:
            state = (
                self.runtime.refresh()
                if self.runtime.state.status in {"RUNNING", "PAUSED"}
                else self.runtime.snapshot()
            )
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            self.operation_completed.emit("refresh", None, str(error))
            return
        self.operation_completed.emit("refresh", state, "")

    @Slot(str)
    def run_control(self, action: str) -> None:
        actions = {
            "start": self.runtime.start,
            "pause": self.runtime.pause,
            "resume": self.runtime.resume,
            "stop": self.runtime.stop,
            "emergency_disable": self.runtime.emergency_disable,
        }
        try:
            state = actions[action]()
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            self.operation_completed.emit(action, None, str(error))
            return
        self.operation_completed.emit(action, state, "")


class DashboardWindow(QMainWindow):
    """FocusOS desktop control center using stable Qt widgets."""

    request_refresh = Signal()
    request_control = Signal(str)

    def __init__(self, runtime: Optional[FocusRuntime] = None):
        super().__init__()
        self.runtime = runtime or FocusRuntime()
        self.history = MetricHistory()
        self._status = "STOPPED"
        self._refresh_pending = False
        self._control_pending = False
        self._closing = False
        self._shutdown_complete = False
        self._warning_active = False
        self._message_kind = ""
        self._plan: List[Dict[str, Any]] = []
        self._top_memory: List[Dict[str, Any]] = []

        self.settings = QSettings("FocusOS", "Monitor")
        saved = str(self.settings.value("theme", "dark"))
        self.theme_name = saved if saved in THEMES else "dark"

        self.setWindowTitle("FocusOS Monitor")
        self.resize(1400, 980)
        self.setMinimumSize(1000, 700)
        self._build_ui()
        self.apply_theme(self.theme_name)

        self.worker_thread = QThread(self)
        self.worker = DashboardWorker(self.runtime)
        self.worker.moveToThread(self.worker_thread)
        self.request_refresh.connect(self.worker.refresh)
        self.request_control.connect(self.worker.run_control)
        self.worker.operation_completed.connect(self._handle_operation_completed)
        self.worker_thread.finished.connect(self.worker.deleteLater)
        self.worker_thread.start()

        self.timer = QTimer(self)
        self.timer.setInterval(2000)
        self.timer.timeout.connect(self.refresh_dashboard)
        self.timer.start()

        self.clock_timer = QTimer(self)
        self.clock_timer.setInterval(1000)
        self.clock_timer.timeout.connect(self._tick_clock)
        self.clock_timer.start()
        self._tick_clock()

        self.start_runtime()

    # ------------------------------------------------------------------ UI --
    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("dashboardRoot")
        layout = QVBoxLayout(root)
        layout.setContentsMargins(28, 24, 28, 28)
        layout.setSpacing(18)

        # Header
        header = QHBoxLayout()
        header.setSpacing(12)
        title_group = QVBoxLayout()
        title_group.setSpacing(0)
        title = QLabel("FocusOS")
        title.setObjectName("pageTitle")
        subtitle = QLabel("System performance and focus control")
        subtitle.setObjectName("pageSubtitle")
        title_group.addWidget(title)
        title_group.addWidget(subtitle)
        header.addLayout(title_group)
        header.addStretch()

        self.clock_label = QLabel("")
        self.clock_label.setObjectName("clockLabel")
        header.addWidget(self.clock_label)

        self.theme_button = QPushButton("Light mode")
        self.theme_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.theme_button.clicked.connect(self.toggle_theme)
        header.addWidget(self.theme_button)

        self.status_label = QLabel("STARTING")
        self.status_label.setObjectName("statusBadge")
        self.status_label.setProperty("state", "stopped")
        header.addWidget(self.status_label)
        layout.addLayout(header)

        # Controls
        controls = QHBoxLayout()
        controls.setSpacing(10)
        self.start_button = QPushButton("Start")
        self.start_button.setObjectName("primaryButton")
        self.pause_button = QPushButton("Pause")
        self.resume_button = QPushButton("Resume")
        self.stop_button = QPushButton("Stop")
        self.stop_button.setObjectName("dangerButton")
        self.emergency_button = QPushButton("Emergency disable")
        self.emergency_button.setObjectName("dangerButton")
        for button, action in (
            (self.start_button, self.start_runtime),
            (self.pause_button, self.pause_runtime),
            (self.resume_button, self.resume_runtime),
            (self.stop_button, self.stop_runtime),
            (self.emergency_button, self.emergency_disable),
        ):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(action)
            controls.addWidget(button)
        controls.addStretch()
        layout.addLayout(controls)

        # Metric cards
        metric_grid = QGridLayout()
        metric_grid.setSpacing(14)
        self.metric_cards: Dict[str, MetricCard] = {}
        self.metric_values: Dict[str, QLabel] = {}
        for index, (name, key) in enumerate(
            (("CPU", "cpu"), ("RAM", "ram"), ("Disk", "disk"), ("GPU", "gpu"))
        ):
            card = MetricCard(name, key)
            self.metric_cards[name] = card
            self.metric_values[name] = card.value_label
            metric_grid.addWidget(card, 0, index)
            metric_grid.setColumnStretch(index, 1)
        layout.addLayout(metric_grid)

        # Current focus
        focus = QWidget()
        focus.setObjectName("surfaceCard")
        focus.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        focus_layout = QVBoxLayout(focus)
        focus_layout.setContentsMargins(20, 16, 20, 16)
        focus_layout.setSpacing(6)

        focus_head = QHBoxLayout()
        focus_title = QLabel("CURRENT FOCUS")
        focus_title.setObjectName("metricName")
        focus_head.addWidget(focus_title)
        focus_head.addStretch()
        self.mode_label = QLabel("")
        self.mode_label.setObjectName("chip")
        self.score_label = QLabel("")
        self.score_label.setObjectName("chip")
        focus_head.addWidget(self.mode_label)
        focus_head.addWidget(self.score_label)

        self.focus_label = QLabel("Waiting for focus data")
        self.focus_label.setObjectName("focusApp")
        self.window_label = QLabel("")
        self.window_label.setObjectName("mutedText")
        self.window_label.setWordWrap(True)
        self.warning_label = QLabel("")
        self.warning_label.setWordWrap(True)

        focus_layout.addLayout(focus_head)
        focus_layout.addWidget(self.focus_label)
        focus_layout.addWidget(self.window_label)
        focus_layout.addWidget(self.warning_label)
        layout.addWidget(focus)

        # Charts
        charts = QHBoxLayout()
        charts.setSpacing(14)
        self.resource_chart = MetricChart("Resource usage (%)", RESOURCE_SERIES, True)
        self.process_chart = MetricChart("Process counts", PROCESS_SERIES, False)
        charts.addWidget(self.resource_chart, 1)
        charts.addWidget(self.process_chart, 1)
        layout.addLayout(charts)

        # Tables (sized to their rows; the page scrolls, not the tables)
        tables = QHBoxLayout()
        tables.setSpacing(14)
        self.process_table = self._create_table(
            ["PID", "Name", "CPU %", "RAM MB", "Class", "Priority", "Suspended"]
        )
        self.memory_table = self._create_table(["PID", "Name", "Memory MB", "Class"])
        tables.addWidget(
            self._labeled_table("Process priority plan", self.process_table), 2,
            Qt.AlignmentFlag.AlignTop,
        )
        tables.addWidget(
            self._labeled_table("Top memory consumers", self.memory_table), 1,
            Qt.AlignmentFlag.AlignTop,
        )
        layout.addLayout(tables)

        # Footer
        self.summary_label = QLabel("")
        self.summary_label.setObjectName("mutedText")
        self.action_error_label = QLabel("")
        self.action_error_label.setWordWrap(True)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.action_error_label)
        layout.addStretch()

        scroll = SmoothScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(root)
        self.setCentralWidget(scroll)

    @staticmethod
    def _create_table(headers: List[str]) -> FlatTable:
        table = FlatTable(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setAlternatingRowColors(True)
        table.setShowGrid(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        table.setFixedHeight(FlatTable.VIEW_HEIGHT)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(FlatTable.ROW_HEIGHT)
        header = table.horizontalHeader()
        header.setHighlightSections(False)
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        return table

    @staticmethod
    def _labeled_table(title: str, table: QTableWidget) -> QWidget:
        container = QWidget()
        container.setObjectName("tableCard")
        container.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(18, 16, 18, 12)
        layout.setSpacing(8)
        heading = QLabel(title)
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        layout.addWidget(table)
        return container

    # --------------------------------------------------------------- theme --
    @property
    def palette_map(self) -> Dict[str, str]:
        return THEMES[self.theme_name]

    def apply_theme(self, name: str) -> None:
        self.theme_name = name if name in THEMES else "dark"
        p = self.palette_map
        self.setStyleSheet(build_stylesheet(p))
        for card in self.metric_cards.values():
            card.apply_theme(p)
        self.resource_chart.set_theme(p)
        self.process_chart.set_theme(p)
        self.theme_button.setText("Light mode" if self.theme_name == "dark" else "Dark mode")
        self._style_warning()
        self._style_message()
        self._render_tables()
        self.settings.setValue("theme", self.theme_name)

    def toggle_theme(self) -> None:
        self.apply_theme("light" if self.theme_name == "dark" else "dark")

    def _style_warning(self) -> None:
        p = self.palette_map
        self.warning_label.setStyleSheet(
            f"color: {p['red'] if self._warning_active else p['green']};"
        )

    def _set_message(self, text: str, kind: str) -> None:
        self._message_kind = kind if text else ""
        self.action_error_label.setText(text)
        self._style_message()

    def _style_message(self) -> None:
        p = self.palette_map
        color = {"error": p["red"], "warn": p["amber"], "info": p["muted"]}.get(
            self._message_kind
        )
        self.action_error_label.setStyleSheet(f"color: {color};" if color else "")

    # ------------------------------------------------------------- updates --
    def _tick_clock(self) -> None:
        self.clock_label.setText(datetime.now().strftime("%a %d %b  %H:%M:%S"))

    def refresh_dashboard(self) -> None:
        """Request one background refresh without queuing overlapping polls."""
        if self._refresh_pending or self._control_pending or self._closing:
            return
        self._refresh_pending = True
        self.request_refresh.emit()

    def _set_status_badge(self, status: str) -> None:
        state = status.lower() if status in {"RUNNING", "PAUSED"} else "stopped"
        self.status_label.setText(status)
        if self.status_label.property("state") != state:
            self.status_label.setProperty("state", state)
            style = self.status_label.style()
            style.unpolish(self.status_label)
            style.polish(self.status_label)

    def update_dashboard(self, state: Dict[str, Any]) -> None:
        """Update displayed values without rebuilding the window or its widgets."""
        status = str(state.get("status", "STOPPED"))
        self._status = status
        self._set_status_badge(status)
        self._update_control_buttons()

        for name, key in (("CPU", "cpu_usage"), ("RAM", "ram_usage"), ("Disk", "disk_usage")):
            self.metric_cards[name].set_value(float(state.get(key, 0.0)))
        gpu = state.get("gpu_usage")
        self.metric_cards["GPU"].set_value(None if gpu is None else float(gpu))

        self.focus_label.setText(str(state.get("focus_application") or "Unknown application"))
        self.window_label.setText(f"Window: {state.get('focus_window') or 'Unknown'}")
        self.mode_label.setText(f"Mode: {state.get('focus_mode', 'idle')}")
        self.score_label.setText(f"Focus score {int(state.get('focus_score', 0))}/100")

        warnings = state.get("resource_warnings") or []
        self._warning_active = bool(warnings)
        self.warning_label.setText(
            "Resource warnings: " + " ".join(str(item) for item in warnings)
            if warnings
            else "No active resource warnings."
        )
        self._style_warning()

        if status in {"RUNNING", "PAUSED"}:
            self.history.record(state)
        self.resource_chart.set_samples(self.history.samples)
        self.process_chart.set_samples(self.history.samples)

        self._plan = list(state.get("priority_plan") or [])
        self._top_memory = list(state.get("top_memory_processes") or [])
        self._render_tables()

        self.summary_label.setText(
            f"Processes: {int(state.get('active_processes', 0))} active  |  "
            f"{int(state.get('background_processes', 0))} background  |  "
            f"{int(state.get('suspended_processes', 0))} suspended  |  "
            f"Available RAM: {self._format_bytes(state.get('ram_available_bytes', 0))}"
        )
        errors = state.get("process_action_errors") or []
        if errors:
            self._set_message(
                "Process action notes: " + "; ".join(str(error) for error in errors), "warn"
            )
        elif not self._control_pending:
            self._set_message("", "")

    def _render_tables(self) -> None:
        self.process_table.setUpdatesEnabled(False)
        self.memory_table.setUpdatesEnabled(False)
        try:
            self._update_process_table(self._plan)
            self._update_memory_table(self._top_memory)
        finally:
            self.process_table.setUpdatesEnabled(True)
            self.memory_table.setUpdatesEnabled(True)

    def _update_process_table(self, processes: List[Dict[str, Any]]) -> None:
        self.process_table.setRowCount(len(processes))
        for row, item in enumerate(processes):
            values = (
                item.get("pid", ""),
                item.get("name", ""),
                f"{float(item.get('cpu_percent', 0.0)):.1f}",
                f"{float(item.get('memory_rss', 0)) / (1024 * 1024):.1f}",
                item.get("classification", "idle"),
                item.get("recommended_priority", "normal"),
                "Yes" if item.get("suspended") else "No",
            )
            self._set_row(self.process_table, row, values, {0, 2, 3}, 4)

    def _update_memory_table(self, processes: List[Dict[str, Any]]) -> None:
        self.memory_table.setRowCount(len(processes))
        for row, item in enumerate(processes):
            values = (
                item.get("pid", ""),
                item.get("name", ""),
                f"{float(item.get('memory_mb', 0.0)):.1f}",
                item.get("classification", "idle"),
            )
            self._set_row(self.memory_table, row, values, {0, 2}, 3)

    def _set_row(
        self,
        table: QTableWidget,
        row: int,
        values: tuple[Any, ...],
        numeric_columns: set,
        class_column: int,
    ) -> None:
        p = self.palette_map
        for column, value in enumerate(values):
            cell = table.item(row, column)
            if cell is None:
                cell = QTableWidgetItem()
                table.setItem(row, column, cell)
            cell.setText(str(value))
            alignment = Qt.AlignmentFlag.AlignVCenter | (
                Qt.AlignmentFlag.AlignRight
                if column in numeric_columns
                else Qt.AlignmentFlag.AlignLeft
            )
            cell.setTextAlignment(int(alignment))
            if column == class_column:
                key = CLASS_COLOR_KEYS.get(str(value).lower(), "muted")
                cell.setForeground(QColor(p[key]))
            elif column == 0:
                cell.setForeground(QColor(p["muted"]))
            else:
                cell.setForeground(QColor(p["text"]))

    @staticmethod
    def _format_bytes(value: Any) -> str:
        size = float(value or 0)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size < 1024 or unit == "TB":
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    def _update_control_buttons(self) -> None:
        enabled = not self._control_pending and not self._closing
        self.start_button.setEnabled(enabled and self._status == "STOPPED")
        self.pause_button.setEnabled(enabled and self._status == "RUNNING")
        self.resume_button.setEnabled(enabled and self._status == "PAUSED")
        can_stop = enabled and self._status in {"RUNNING", "PAUSED"}
        self.stop_button.setEnabled(can_stop)
        self.emergency_button.setEnabled(can_stop)

    def _run_control(self, action: str) -> None:
        if self._control_pending or (self._closing and action != "stop"):
            return
        self._control_pending = True
        self._update_control_buttons()
        self._set_message("Working...", "info")
        self.request_control.emit(action)

    @Slot(str, object, str)
    def _handle_operation_completed(
        self, action: str, state: object, error: str
    ) -> None:
        if action == "refresh":
            self._refresh_pending = False
        else:
            self._control_pending = False

        if error:
            prefix = "Monitoring error" if action == "refresh" else "Action error"
            self._set_message(f"{prefix}: {error}", "error")
        elif isinstance(state, dict):
            self._set_message("", "")
            self.update_dashboard(state)

        if self._closing:
            if action == "stop":
                if isinstance(state, dict):
                    errors = state.get("process_action_errors") or []
                    if errors:
                        QMessageBox.warning(
                            self,
                            "Restore warning",
                            "Some FocusOS-managed process settings could not be restored:\n"
                            + "\n".join(str(item) for item in errors),
                        )
                elif error:
                    QMessageBox.warning(
                        self,
                        "Stop warning",
                        f"FocusOS could not finish stopping cleanly: {error}",
                    )
                self._shutdown_complete = True
                self.close()
            elif not self._control_pending:
                self._run_control("stop")
            return

        self._update_control_buttons()

    def start_runtime(self) -> None:
        self._run_control("start")

    def pause_runtime(self) -> None:
        self._run_control("pause")

    def resume_runtime(self) -> None:
        self._run_control("resume")

    def stop_runtime(self) -> None:
        self._run_control("stop")

    def emergency_disable(self) -> None:
        self._run_control("emergency_disable")

    def closeEvent(self, event: Any) -> None:
        if not self._shutdown_complete:
            event.ignore()
            if not self._closing:
                self._closing = True
                self.timer.stop()
                self.clock_timer.stop()
                self._update_control_buttons()
                if not self._control_pending:
                    self._run_control("stop")
            return

        self.worker_thread.quit()
        self.worker_thread.wait()
        event.accept()


def run_dashboard(runtime: Optional[FocusRuntime] = None) -> None:
    """Create and run the native FocusOS dashboard."""
    application = QApplication.instance()
    if application is None:
        application = QApplication([])
    application.setApplicationName("FocusOS")
    application.setStyle("Fusion")
    window = DashboardWindow(runtime)
    window.show()
    application.exec()