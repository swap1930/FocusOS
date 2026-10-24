"""Qt Quick (QML) dashboard for FocusOS.

The Python side owns the runtime, a worker thread and the data models; the UI
lives in the ``qml`` folder next to this file and is GPU rendered.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QObject,
    QThread,
    Qt,
    QTimer,
    QUrl,
    Property,
    Signal,
    Slot,
)
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

from config.settings import RESOURCE_PROFILES
from core.focus_runtime import FocusRuntime


QML_DIR = Path(__file__).resolve().parent / "qml"
HISTORY_LIMIT = 120
TRAINING_PROCESS_KEYWORDS = (
    "code.exe",
    "devenv.exe",
    "pycharm",
    "idea64",
    "idea.exe",
    "studio64",
    "jupyter",
    "python.exe",
    "python3",
    "ollama",
    "lmstudio",
    "llama-server",
    "chrome.exe",
    "msedge.exe",
    "firefox.exe",
    "brave.exe",
    "chromium",
    "google chrome",
    "microsoft edge",
    "colab",
)


class MetricHistory:
    """Keep a bounded series of system samples for live charts."""

    def __init__(self, limit: int = HISTORY_LIMIT):
        self.limit = limit
        self.samples: List[Dict[str, Any]] = []

    def record(self, state: Dict[str, Any], timestamp: Optional[datetime] = None) -> None:
        stamp = timestamp or datetime.now()
        self.samples.append(
            {
                "t": stamp.strftime("%H:%M:%S"),
                "cpu": float(state.get("cpu_usage", 0.0)),
                "ram": float(state.get("ram_usage", 0.0)),
                "disk": float(state.get("disk_usage", 0.0)),
                "gpu": (
                    float(state["gpu_usage"])
                    if state.get("gpu_usage") is not None
                    else None
                ),
                "active": int(state.get("active_processes", 0)),
                "background": int(state.get("background_processes", 0)),
                "suspended": int(state.get("suspended_processes", 0)),
            }
        )
        if len(self.samples) > self.limit:
            del self.samples[:-self.limit]


class RowsModel(QAbstractListModel):
    """List model that updates rows in place so views keep their scroll position."""

    CellsRole = Qt.ItemDataRole.UserRole + 1
    ClassRole = Qt.ItemDataRole.UserRole + 2

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._rows: List[Tuple[List[str], str]] = []

    def roleNames(self) -> Dict[int, bytes]:  # type: ignore[override]
        return {self.CellsRole: b"cells", self.ClassRole: b"cls"}

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # type: ignore[override]
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        cells, cls = self._rows[index.row()]
        if role == self.CellsRole:
            return cells
        if role == self.ClassRole:
            return cls
        return None

    def set_rows(self, rows: List[Tuple[List[str], str]]) -> None:
        old, new = len(self._rows), len(rows)
        for row in range(min(old, new)):
            if self._rows[row] != rows[row]:
                self._rows[row] = rows[row]
                index = self.index(row)
                self.dataChanged.emit(index, index, [self.CellsRole, self.ClassRole])
        if new > old:
            self.beginInsertRows(QModelIndex(), old, new - 1)
            self._rows.extend(rows[old:])
            self.endInsertRows()
        elif new < old:
            self.beginRemoveRows(QModelIndex(), new, old - 1)
            del self._rows[new:]
            self.endRemoveRows()


class DashboardWorker(QObject):
    """Run monitoring and runtime controls away from the UI thread."""

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

    @Slot(str)
    def set_resource_profile(self, profile: str) -> None:
        try:
            state = self.runtime.set_resource_profile(profile)
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            self.operation_completed.emit(f"profile:{profile}", None, str(error))
            return
        self.operation_completed.emit(f"profile:{profile}", state, "")

    @Slot(bool, int)
    def set_ml_power_mode(self, enabled: bool, target_pid: int) -> None:
        try:
            state = self.runtime.set_ml_power_mode(
                enabled,
                target_pid if enabled and target_pid > 0 else None,
            )
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            self.operation_completed.emit("ml_power_mode", None, str(error))
            return
        self.operation_completed.emit("ml_power_mode", state, "")

    @Slot()
    def clean_disk(self) -> None:
        try:
            self.runtime.clean_disk(empty_recycle_bin=False)
            state = self.runtime.snapshot()
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            self.operation_completed.emit("clean_disk", None, str(error))
            return
        self.operation_completed.emit("clean_disk", state, "")


def _format_bytes(value: Any) -> str:
    size = float(value or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _default_state() -> Dict[str, Any]:
    return {
        "status": "STARTING",
        "cpu": 0.0,
        "ram": 0.0,
        "disk": 0.0,
        "gpu": -1.0,
        "focusApp": "Waiting for focus data",
        "focusWindow": "",
        "focusMode": "Mode: idle",
        "focusScore": "Focus score 0/100",
        "warningText": "No active resource warnings.",
        "warningActive": False,
        "summary": "",
        "resourceProfile": RESOURCE_PROFILES["balanced"]["label"],
        "mlPowerModeEnabled": False,
        "mlPowerModeActive": False,
        "mlTrainingTargetPid": 0,
        "mlTrainingTargetName": "",
        "trainingCandidates": [],
        "diskCleaned": "0.0 B",
        "diskCleanedSummary": "",
    }


class DashboardBackend(QObject):
    """Bridge between FocusRuntime and the QML user interface."""

    stateChanged = Signal()
    historyChanged = Signal()
    messageChanged = Signal()
    controlsChanged = Signal()
    resourceProfileChanged = Signal()
    darkModeChanged = Signal()
    shutdownIssue = Signal(str)
    shutdownReady = Signal()
    request_refresh = Signal()
    request_control = Signal(str)
    request_resource_profile = Signal(str)
    request_clean_disk = Signal()
    request_ml_power_mode = Signal(bool, int)

    def __init__(self, runtime: Optional[FocusRuntime] = None):
        super().__init__()
        self.runtime = runtime or FocusRuntime()
        self._history = MetricHistory()
        self._state: Dict[str, Any] = _default_state()
        self._status = "STOPPED"
        self._message = ""
        self._message_kind = ""
        self._refresh_pending = False
        self._control_pending = False
        self._profile_pending = False
        self._disk_cleaning = False
        self._startup_cleanup_pending = False
        self._resource_profile = self.runtime.resource_profile
        self._closing = False
        self._shutdown_complete = False
        self._dark = False

        self._plan_model = RowsModel(self)
        self._memory_model = RowsModel(self)

        self.worker_thread = QThread(self)
        self.worker = DashboardWorker(self.runtime)
        self.worker.moveToThread(self.worker_thread)
        self.request_refresh.connect(self.worker.refresh)
        self.request_control.connect(self.worker.run_control)
        self.request_resource_profile.connect(self.worker.set_resource_profile)
        self.request_clean_disk.connect(self.worker.clean_disk)
        self.request_ml_power_mode.connect(self.worker.set_ml_power_mode)
        self.worker.operation_completed.connect(self._handle_operation_completed)
        self.worker_thread.finished.connect(self.worker.deleteLater)
        self.worker_thread.start()

        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self.refresh_dashboard)

    # ------------------------------------------------------------ properties --
    @Property("QVariantMap", notify=stateChanged)  # type: ignore[arg-type]
    def state(self) -> Dict[str, Any]:
        return self._state

    @Property("QVariantList", notify=historyChanged)  # type: ignore[arg-type]
    def history(self) -> List[Dict[str, Any]]:
        return self._history.samples

    @Property(QObject, constant=True)
    def planModel(self) -> QObject:
        return self._plan_model

    @Property(QObject, constant=True)
    def memoryModel(self) -> QObject:
        return self._memory_model

    @Property(str, notify=messageChanged)
    def message(self) -> str:
        return self._message

    @Property(str, notify=messageChanged)
    def messageKind(self) -> str:
        return self._message_kind

    @Property(bool, notify=darkModeChanged)
    def darkMode(self) -> bool:
        return self._dark


    @Property(str, constant=True)
    def platformName(self) -> str:
        return self.runtime.platform

    @Property("QVariantList", constant=True)  # type: ignore[arg-type]
    def resourceProfiles(self) -> List[Dict[str, str]]:
        return [
            {"id": profile_id, "label": str(settings["label"])}
            for profile_id, settings in RESOURCE_PROFILES.items()
        ]

    @Property(str, notify=resourceProfileChanged)
    def resourceProfile(self) -> str:
        return self._resource_profile

    @Property(int, notify=resourceProfileChanged)
    def resourceProfileIndex(self) -> int:
        return list(RESOURCE_PROFILES).index(self._resource_profile)

    @Property(str, notify=resourceProfileChanged)
    def resourceProfileDescription(self) -> str:
        return str(RESOURCE_PROFILES[self._resource_profile]["description"])

    @Property(bool, notify=controlsChanged)
    def canChangeResourceProfile(self) -> bool:
        return self._controls_enabled() and not self._profile_pending

    @Property(bool, notify=controlsChanged)
    def canStart(self) -> bool:
        return self._controls_enabled() and self._status == "STOPPED"

    @Property(bool, notify=controlsChanged)
    def canPause(self) -> bool:
        return self._controls_enabled() and self._status == "RUNNING"

    @Property(bool, notify=controlsChanged)
    def canResume(self) -> bool:
        return self._controls_enabled() and self._status == "PAUSED"

    @Property(bool, notify=controlsChanged)
    def canStop(self) -> bool:
        return self._controls_enabled() and self._status in {"RUNNING", "PAUSED"}

    @Property(bool, notify=controlsChanged)
    def canCleanDisk(self) -> bool:
        return not self._disk_cleaning and not self._closing

    def _controls_enabled(self) -> bool:
        return not self._control_pending and not self._profile_pending and not self._closing

    # ----------------------------------------------------------------- theme --
    @Slot()
    def toggleTheme(self) -> None:
        self._dark = not self._dark
        self.darkModeChanged.emit()

    # --------------------------------------------------------------- lifecycle --
    def begin(self) -> None:
        self._timer.start()
        self.startRuntime()
        self._startup_cleanup_pending = True
        self._disk_cleaning = True
        self.controlsChanged.emit()
        self._set_message("Automatically cleaning eligible old cache/temp files...", "info")
        self.request_clean_disk.emit()

    @Slot(result=bool)
    def tryClose(self) -> bool:
        """Called when the window asks to close; stops the runtime first."""
        if self._shutdown_complete:
            return True
        if not self._closing:
            self._closing = True
            self._timer.stop()
            self.controlsChanged.emit()
            if not self._control_pending and not self._startup_cleanup_pending:
                self._run_control("stop")
        return False

    @Slot()
    def finishShutdown(self) -> None:
        self._shutdown_complete = True
        self.dispose()
        self.shutdownReady.emit()

    def dispose(self) -> None:
        self._timer.stop()
        if self.worker_thread.isRunning():
            self.worker_thread.quit()
            self.worker_thread.wait()

    # ---------------------------------------------------------------- controls --
    @Slot()
    def startRuntime(self) -> None:
        self._run_control("start")

    @Slot()
    def pauseRuntime(self) -> None:
        self._run_control("pause")

    @Slot()
    def resumeRuntime(self) -> None:
        self._run_control("resume")

    @Slot()
    def stopRuntime(self) -> None:
        self._run_control("stop")

    @Slot()
    def emergencyDisable(self) -> None:
        self._run_control("emergency_disable")

    @Slot(str)
    def setResourceProfile(self, profile: str) -> None:
        if profile not in RESOURCE_PROFILES:
            self._set_message(f"Unknown resource profile: {profile}", "error")
            return
        if self._control_pending or self._profile_pending or self._closing:
            return
        if profile == self._resource_profile:
            return
        self._profile_pending = True
        self.controlsChanged.emit()
        self._set_message("Applying resource profile...", "info")
        self.request_resource_profile.emit(profile)

    @Slot(bool, int)
    def setMLPowerMode(self, enabled: bool, target_pid: int) -> None:
        if self._control_pending or self._profile_pending or self._closing:
            return
        if enabled and target_pid <= 0:
            self._set_message("Select a training process before enabling ML mode.", "warn")
            return
        self._control_pending = True
        self.controlsChanged.emit()
        self._set_message("Updating ML training focus...", "info")
        self.request_ml_power_mode.emit(enabled, target_pid)

    @Slot()
    def cleanDisk(self) -> None:
        if self._disk_cleaning or self._closing:
            return
        self._disk_cleaning = True
        self.controlsChanged.emit()
        self._set_message("Scanning and cleaning temporary files...", "info")
        self.request_clean_disk.emit()

    def _run_control(self, action: str) -> None:
        if (
            self._control_pending
            or self._profile_pending
            or self._startup_cleanup_pending
            or (self._closing and action != "stop")
        ):
            return
        self._control_pending = True
        self.controlsChanged.emit()
        self._set_message("Working...", "info")
        self.request_control.emit(action)

    def refresh_dashboard(self) -> None:
        """Request one background refresh without queuing overlapping polls."""
        if (
            self._refresh_pending
            or self._control_pending
            or self._profile_pending
            or self._closing
        ):
            return
        self._refresh_pending = True
        self.request_refresh.emit()

    def _set_message(self, text: str, kind: str) -> None:
        if text == self._message and kind == self._message_kind:
            return
        self._message = text
        self._message_kind = kind if text else ""
        self.messageChanged.emit()

    # ----------------------------------------------------------------- updates --
    @Slot(str, object, str)
    def _handle_operation_completed(self, action: str, state: object, error: str) -> None:
        if action == "clean_disk":
            self._disk_cleaning = False
            self.controlsChanged.emit()
            if error:
                self._set_message(f"Disk cleanup error: {error}", "error")
            elif isinstance(state, dict):
                summary = str(state.get("last_disk_cleanup_summary") or "Disk cleanup complete.")
                self._set_message(summary, "info")
                self.update_dashboard(state)
            self._startup_cleanup_pending = False
            if self._closing and not self._control_pending:
                self._run_control("stop")
            return

        if action == "refresh":
            self._refresh_pending = False
        elif action.startswith("profile:"):
            self._profile_pending = False
            self.resourceProfileChanged.emit()
        else:
            self._control_pending = False

        if error:
            prefix = (
                "Monitoring error"
                if action == "refresh"
                else "Profile error"
                if action.startswith("profile:")
                else "Action error"
            )
            self._set_message(f"{prefix}: {error}", "error")
        elif isinstance(state, dict):
            self._set_message("", "")
            self.update_dashboard(state)

        if self._closing:
            if action == "stop":
                if isinstance(state, dict):
                    errors = state.get("process_action_errors") or []
                    if errors:
                        self.shutdownIssue.emit(
                            "Some FocusOS-managed process settings could not be restored:\n"
                            + "\n".join(str(item) for item in errors)
                        )
                        return
                elif error:
                    self.shutdownIssue.emit(
                        f"FocusOS could not finish stopping cleanly: {error}"
                    )
                    return
                self.finishShutdown()
            elif not self._control_pending:
                self._run_control("stop")
            return

        self.controlsChanged.emit()

    def update_dashboard(self, state: Dict[str, Any]) -> None:
        status = str(state.get("status", "STOPPED"))
        self._status = status
        resource_profile = str(
            state.get("resource_profile", self._resource_profile)
        )
        if resource_profile in RESOURCE_PROFILES and resource_profile != self._resource_profile:
            self._resource_profile = resource_profile
            self.resourceProfileChanged.emit()

        gpu = state.get("gpu_usage")
        warnings = state.get("resource_warnings") or []
        focus_warning = state.get("focus_detection_warning")
        self._state = {
            "status": status,
            "resourceProfile": str(
                RESOURCE_PROFILES[resource_profile]["label"]
                if resource_profile in RESOURCE_PROFILES
                else resource_profile
            ),
            "cpu": float(state.get("cpu_usage", 0.0)),
            "ram": float(state.get("ram_usage", 0.0)),
            "disk": float(state.get("disk_usage", 0.0)),
            "diskCleaned": _format_bytes(state.get("disk_cleaned_bytes", 0)),
            "diskCleanedSummary": str(state.get("last_disk_cleanup_summary") or ""),
            "gpu": -1.0 if gpu is None else float(gpu),
            "focusApp": str(
                (state.get("ml_training_target_name") or "Selected training process")
                if state.get("ml_power_mode_active")
                else state.get("focus_application") or "Unknown application"
            ),
            "focusWindow": (
                f"Selected ML process (PID {state.get('ml_training_target_pid')})"
                if state.get("ml_power_mode_active")
                else f"Window: {state.get('focus_window') or 'Unknown'}"
            ),
            "focusMode": f"Mode: {state.get('focus_mode', 'idle')}",
            "focusScore": f"Focus score {int(state.get('focus_score', 0))}/100",
            "warningText": (
                "Warnings: " + " ".join(
                    [*(str(item) for item in warnings), *([str(focus_warning)] if focus_warning else [])]
                )
                if warnings or focus_warning
                else "No active resource warnings."
            ),
            "warningActive": bool(warnings or focus_warning),
            "mlPowerModeActive": bool(state.get("ml_power_mode_active", False)),
            "mlPowerModeEnabled": bool(state.get("ml_power_mode_enabled", False)),
            "mlTrainingTargetPid": int(state.get("ml_training_target_pid") or 0),
            "mlTrainingTargetName": str(state.get("ml_training_target_name") or ""),
            "trainingCandidates": [
                {
                    "pid": int(item.get("pid", 0)),
                    "name": str(item.get("name", "Unknown process")),
                    "label": f"{item.get('name', 'Unknown process')} (PID {item.get('pid', 0)})",
                }
                for item in (state.get("priority_plan") or [])
                if int(item.get("pid", 0)) > 0
                and str(item.get("name", "")).casefold()
                not in self.runtime.process_manager._PROTECTED_NAMES
                and any(
                    keyword in str(item.get("name", "")).casefold()
                    for keyword in TRAINING_PROCESS_KEYWORDS
                )
            ],
            "summary": (
                f"Processes: {int(state.get('active_processes', 0))} active  |  "
                f"{int(state.get('background_processes', 0))} background  |  "
                f"{int(state.get('suspended_processes', 0))} suspended  |  "
                f"Available RAM: {_format_bytes(state.get('ram_available_bytes', 0))}"
            ),
        }
        self.stateChanged.emit()

        if status in {"RUNNING", "PAUSED"}:
            self._history.record(state)
            self.historyChanged.emit()

        self._plan_model.set_rows(
            [
                (
                    [
                        str(item.get("pid", "")),
                        str(item.get("name", "")),
                        f"{float(item.get('cpu_percent', 0.0)):.1f}",
                        f"{float(item.get('memory_rss', 0)) / (1024 * 1024):.1f}",
                        str(item.get("classification", "idle")),
                        str(item.get("recommended_priority", "normal")),
                        "Yes" if item.get("suspended") else "No",
                    ],
                    str(item.get("classification", "idle")),
                )
                for item in (state.get("priority_plan") or [])
            ]
        )
        self._memory_model.set_rows(
            [
                (
                    [
                        str(item.get("pid", "")),
                        str(item.get("name", "")),
                        f"{float(item.get('memory_mb', 0.0)):.1f}",
                        str(item.get("classification", "idle")),
                    ],
                    str(item.get("classification", "idle")),
                )
                for item in (state.get("top_memory_processes") or [])
            ]
        )

        errors = state.get("process_action_errors") or []
        if errors:
            visible_errors = [str(error) for error in errors[:3]]
            additional = len(errors) - len(visible_errors)
            details = "; ".join(visible_errors)
            if additional:
                details += f"; and {additional} more process action warning(s)"
            self._set_message(
                "Process action notes: " + details, "warn"
            )
        self.controlsChanged.emit()


def create_engine(backend: DashboardBackend) -> QQmlApplicationEngine:
    engine = QQmlApplicationEngine()
    engine.addImportPath(str(QML_DIR))
    engine.rootContext().setContextProperty("backend", backend)
    engine.load(QUrl.fromLocalFile(str(QML_DIR / "Main.qml")))
    if not engine.rootObjects():
        raise RuntimeError("FocusOS could not load its QML interface.")
    return engine


def run_dashboard(runtime: Optional[FocusRuntime] = None) -> None:
    """Create and run the Qt Quick FocusOS dashboard."""
    QQuickStyle.setStyle("Basic")
    application = QGuiApplication.instance()
    if application is None:
        application = QGuiApplication(sys.argv)
    application.setApplicationName("FocusOS")
    application.setOrganizationName("FocusOS")

    backend = DashboardBackend(runtime)
    engine = create_engine(backend)
    backend.begin()
    application.exec()
    backend.dispose()
    del engine
