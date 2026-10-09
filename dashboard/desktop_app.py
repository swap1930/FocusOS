"""Native, in-place updating desktop dashboard for FocusOS."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.focus_runtime import FocusRuntime


HISTORY_LIMIT = 120
RESOURCE_SERIES = [
    ("CPU %", QColor("#61afef")),
    ("RAM %", QColor("#c678dd")),
    ("Disk %", QColor("#e5c07b")),
    ("GPU %", QColor("#56b6c2")),
]
PROCESS_SERIES = [
    ("Active", QColor("#98c379")),
    ("Background", QColor("#e5c07b")),
    ("Suspended", QColor("#e06c75")),
]


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
    """Small QPainter-based line chart that updates without replacing widgets."""

    def __init__(self, title: str, series: List[tuple[str, QColor]], fixed_scale: bool):
        super().__init__()
        self.title = title
        self.series = series
        self.fixed_scale = fixed_scale
        self.samples: List[Dict[str, Any]] = []
        self.setMinimumHeight(220)

    def set_samples(self, samples: List[Dict[str, Any]]) -> None:
        self.samples = samples
        self.update()

    def paintEvent(self, event: Any) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#1e222a"))

        left, top, right, bottom = 42, 34, 16, 34
        plot = self.rect().adjusted(left, top, -right, -bottom)
        painter.setPen(QColor("#e6e6e6"))
        painter.drawText(12, 22, self.title)

        if not self.samples:
            painter.setPen(QColor("#9da5b4"))
            painter.drawText(plot, Qt.AlignmentFlag.AlignCenter, "Waiting for samples")
            return

        max_value = 100.0 if self.fixed_scale else 1.0
        if not self.fixed_scale:
            observed = [
                float(sample[name])
                for sample in self.samples
                for name, _ in self.series
                if sample.get(name) is not None
            ]
            max_value = max(5.0, max(observed, default=0.0) * 1.15)

        painter.setPen(QPen(QColor("#39414d"), 1))
        for grid_step in range(5):
            y = plot.bottom() - (plot.height() * grid_step / 4)
            painter.drawLine(plot.left(), round(y), plot.right(), round(y))
            painter.setPen(QColor("#9da5b4"))
            painter.drawText(4, round(y) + 4, f"{max_value * grid_step / 4:.0f}")
            painter.setPen(QPen(QColor("#39414d"), 1))
        painter.drawRect(plot)

        for series_name, color in self.series:
            points = [
                sample.get(series_name)
                for sample in self.samples
                if sample.get(series_name) is not None
            ]
            if not points:
                continue
            path = QPainterPath()
            for index, value in enumerate(points):
                x = plot.left() + (
                    0 if len(points) == 1
                    else plot.width() * index / (len(points) - 1)
                )
                y = plot.bottom() - min(float(value), max_value) / max_value * plot.height()
                if index == 0:
                    path.moveTo(x, y)
                else:
                    path.lineTo(x, y)
            painter.setPen(QPen(color, 2))
            painter.drawPath(path)

        legend_x = left
        legend_y = self.height() - 8
        for name, color in self.series:
            if not any(sample.get(name) is not None for sample in self.samples):
                continue
            painter.setPen(QPen(color, 3))
            painter.drawLine(legend_x, legend_y - 4, legend_x + 14, legend_y - 4)
            painter.setPen(QColor("#c8ccd4"))
            painter.drawText(legend_x + 19, legend_y, name)
            legend_x += 84


class DashboardWindow(QMainWindow):
    """FocusOS desktop control center using stable Qt widgets."""

    def __init__(self, runtime: Optional[FocusRuntime] = None):
        super().__init__()
        self.runtime = runtime or FocusRuntime()
        self.history = MetricHistory()
        self.setWindowTitle("FocusOS Monitor")
        self.resize(1250, 900)
        self.setMinimumSize(980, 700)
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #171a21; color: #e6e6e6; }
            QLabel { color: #e6e6e6; }
            QPushButton {
                background: #2c313c; border: 1px solid #414754;
                border-radius: 5px; padding: 8px 14px; color: #f0f0f0;
            }
            QPushButton:hover { background: #3a4150; }
            QPushButton:disabled { color: #777d88; background: #22262e; }
            QTableWidget {
                background: #1e222a; alternate-background-color: #242a34;
                gridline-color: #39414d; border: 1px solid #39414d;
            }
            QHeaderView::section {
                background: #252b35; color: #d7dae0; padding: 5px;
                border: 0; border-bottom: 1px solid #39414d;
            }
            """
        )
        self._build_ui()
        initial_state = self.runtime.start()
        self.update_dashboard(initial_state)
        self.timer = QTimer(self)
        self.timer.setInterval(2000)
        self.timer.timeout.connect(self.refresh_dashboard)
        self.timer.start()

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel("FocusOS")
        title.setStyleSheet("font-size: 26px; font-weight: 700;")
        self.status_label = QLabel("Starting")
        self.status_label.setStyleSheet("font-size: 15px; color: #98c379;")
        header.addWidget(title)
        header.addStretch()
        header.addWidget(QLabel("Status:"))
        header.addWidget(self.status_label)
        layout.addLayout(header)

        controls = QHBoxLayout()
        self.start_button = QPushButton("Start")
        self.pause_button = QPushButton("Pause")
        self.resume_button = QPushButton("Resume")
        self.stop_button = QPushButton("Stop")
        self.emergency_button = QPushButton("Emergency disable")
        for button, action in (
            (self.start_button, self.start_runtime),
            (self.pause_button, self.pause_runtime),
            (self.resume_button, self.resume_runtime),
            (self.stop_button, self.stop_runtime),
            (self.emergency_button, self.emergency_disable),
        ):
            button.clicked.connect(action)
            controls.addWidget(button)
        controls.addStretch()
        layout.addLayout(controls)

        metric_grid = QGridLayout()
        self.metric_values: Dict[str, QLabel] = {}
        for index, name in enumerate(("CPU", "RAM", "Disk", "GPU")):
            card = QWidget()
            card.setStyleSheet(
                "background: #222731; border: 1px solid #343b47; border-radius: 7px;"
            )
            card_layout = QVBoxLayout(card)
            name_label = QLabel(name)
            name_label.setStyleSheet("font-size: 13px; color: #aab1bd;")
            value_label = QLabel("--")
            value_label.setStyleSheet("font-size: 24px; font-weight: 700;")
            card_layout.addWidget(name_label)
            card_layout.addWidget(value_label)
            self.metric_values[name] = value_label
            metric_grid.addWidget(card, 0, index)
        layout.addLayout(metric_grid)

        focus = QWidget()
        focus.setStyleSheet(
            "background: #222731; border: 1px solid #343b47; border-radius: 7px;"
        )
        focus_layout = QVBoxLayout(focus)
        focus_title = QLabel("Current focus")
        focus_title.setStyleSheet("font-size: 16px; font-weight: 600;")
        self.focus_label = QLabel("Waiting for focus data")
        self.window_label = QLabel("")
        self.mode_label = QLabel("")
        self.warning_label = QLabel("")
        self.warning_label.setWordWrap(True)
        focus_layout.addWidget(focus_title)
        focus_layout.addWidget(self.focus_label)
        focus_layout.addWidget(self.window_label)
        focus_layout.addWidget(self.mode_label)
        focus_layout.addWidget(self.warning_label)
        layout.addWidget(focus)

        charts = QHBoxLayout()
        self.resource_chart = MetricChart("Resource usage (%)", RESOURCE_SERIES, True)
        self.process_chart = MetricChart("Process counts", PROCESS_SERIES, False)
        charts.addWidget(self.resource_chart)
        charts.addWidget(self.process_chart)
        layout.addLayout(charts)

        tables = QHBoxLayout()
        self.process_table = self._create_table(
            ["PID", "Name", "CPU %", "RAM MB", "Class", "Priority", "Suspended"]
        )
        self.memory_table = self._create_table(["PID", "Name", "Memory MB", "Class"])
        tables.addWidget(self._labeled_table("Process priority plan", self.process_table), 2)
        tables.addWidget(self._labeled_table("Top memory consumers", self.memory_table), 1)
        layout.addLayout(tables, 1)

        self.summary_label = QLabel("")
        self.action_error_label = QLabel("")
        self.action_error_label.setWordWrap(True)
        self.action_error_label.setStyleSheet("color: #e06c75;")
        layout.addWidget(self.summary_label)
        layout.addWidget(self.action_error_label)

        self.setCentralWidget(root)

    @staticmethod
    def _create_table(headers: List[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        return table

    @staticmethod
    def _labeled_table(title: str, table: QTableWidget) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        heading = QLabel(title)
        heading.setStyleSheet("font-size: 15px; font-weight: 600;")
        layout.addWidget(heading)
        layout.addWidget(table)
        return container

    def refresh_dashboard(self) -> None:
        """Refresh the runtime once and update existing widgets in place."""
        try:
            state = (
                self.runtime.refresh()
                if self.runtime.state.status in {"RUNNING", "PAUSED"}
                else self.runtime.snapshot()
            )
        except (OSError, RuntimeError) as error:
            self.action_error_label.setText(f"Monitoring error: {error}")
            return
        self.update_dashboard(state)

    def update_dashboard(self, state: Dict[str, Any]) -> None:
        """Update displayed values without rebuilding the window or its widgets."""
        status = str(state.get("status", "STOPPED"))
        self.status_label.setText(status)
        self.start_button.setEnabled(status == "STOPPED")
        self.pause_button.setEnabled(status == "RUNNING")
        self.resume_button.setEnabled(status == "PAUSED")
        self.stop_button.setEnabled(status in {"RUNNING", "PAUSED"})
        self.emergency_button.setEnabled(status in {"RUNNING", "PAUSED"})

        for name, key in (("CPU", "cpu_usage"), ("RAM", "ram_usage"), ("Disk", "disk_usage")):
            self.metric_values[name].setText(f"{float(state.get(key, 0.0)):.1f}%")
        gpu = state.get("gpu_usage")
        self.metric_values["GPU"].setText("N/A" if gpu is None else f"{float(gpu):.1f}%")

        self.focus_label.setText(f"Application: {state.get('focus_application') or 'Unknown'}")
        self.window_label.setText(f"Window: {state.get('focus_window') or 'Unknown'}")
        self.mode_label.setText(
            f"Mode: {state.get('focus_mode', 'idle')} | "
            f"Focus score: {int(state.get('focus_score', 0))}/100"
        )
        warnings = state.get("resource_warnings") or []
        self.warning_label.setText(
            "Resource warnings: " + " ".join(str(item) for item in warnings)
            if warnings
            else "No active resource warnings."
        )
        self.warning_label.setStyleSheet(
            "color: #e06c75;" if warnings else "color: #98c379;"
        )

        if status in {"RUNNING", "PAUSED"}:
            self.history.record(state)
        self.resource_chart.set_samples(self.history.samples)
        self.process_chart.set_samples(self.history.samples)
        self._update_process_table(state.get("priority_plan") or [])
        self._update_memory_table(state.get("top_memory_processes") or [])

        self.summary_label.setText(
            f"Processes: {int(state.get('active_processes', 0))} active  |  "
            f"{int(state.get('background_processes', 0))} background  |  "
            f"{int(state.get('suspended_processes', 0))} suspended  |  "
            f"Available RAM: {self._format_bytes(state.get('ram_available_bytes', 0))}"
        )
        errors = state.get("process_action_errors") or []
        self.action_error_label.setText(
            "Process action notes: " + "; ".join(str(error) for error in errors)
            if errors
            else ""
        )

    def _update_process_table(self, processes: List[Dict[str, Any]]) -> None:
        self.process_table.setRowCount(min(len(processes), 20))
        for row, item in enumerate(processes[:20]):
            values = (
                item.get("pid", ""),
                item.get("name", ""),
                f"{float(item.get('cpu_percent', 0.0)):.1f}",
                f"{float(item.get('memory_rss', 0)) / (1024 * 1024):.1f}",
                item.get("classification", "idle"),
                item.get("recommended_priority", "normal"),
                "Yes" if item.get("suspended") else "No",
            )
            self._set_row(self.process_table, row, values)

    def _update_memory_table(self, processes: List[Dict[str, Any]]) -> None:
        self.memory_table.setRowCount(len(processes))
        for row, item in enumerate(processes):
            values = (
                item.get("pid", ""),
                item.get("name", ""),
                f"{float(item.get('memory_mb', 0.0)):.1f}",
                item.get("classification", "idle"),
            )
            self._set_row(self.memory_table, row, values)

    @staticmethod
    def _set_row(table: QTableWidget, row: int, values: tuple[Any, ...]) -> None:
        for column, value in enumerate(values):
            table.setItem(row, column, QTableWidgetItem(str(value)))

    @staticmethod
    def _format_bytes(value: Any) -> str:
        size = float(value or 0)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size < 1024 or unit == "TB":
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    def _run_control(self, action: Any) -> None:
        try:
            state = action()
        except RuntimeError as error:
            self.action_error_label.setText(str(error))
            return
        self.action_error_label.clear()
        self.update_dashboard(state)

    def start_runtime(self) -> None:
        self._run_control(self.runtime.start)

    def pause_runtime(self) -> None:
        self._run_control(self.runtime.pause)

    def resume_runtime(self) -> None:
        self._run_control(self.runtime.resume)

    def stop_runtime(self) -> None:
        self._run_control(self.runtime.stop)

    def emergency_disable(self) -> None:
        self._run_control(self.runtime.emergency_disable)

    def closeEvent(self, event: Any) -> None:
        if self.runtime.state.status in {"RUNNING", "PAUSED"}:
            state = self.runtime.stop()
            errors = state.get("process_action_errors") or []
            if errors:
                QMessageBox.warning(
                    self,
                    "Restore warning",
                    "Some FocusOS-managed process settings could not be restored:\n"
                    + "\n".join(str(error) for error in errors),
                )
        event.accept()


def run_dashboard(runtime: Optional[FocusRuntime] = None) -> None:
    """Create and run the native FocusOS dashboard."""
    application = QApplication.instance()
    if application is None:
        application = QApplication([])
    application.setApplicationName("FocusOS")
    window = DashboardWindow(runtime)
    window.show()
    application.exec()
