"""Runtime configuration for the FocusOS prototype."""

FOCUSOS_NAME = "FocusOS"
DEFAULT_LOG_LEVEL = "INFO"
SYSTEM_MODE = "monitoring"

# Add exact executable names here to opt in to automatic suspension.
AUTO_SUSPEND_ALLOWLIST = ()
AUTO_SUSPEND_DELAY_SECONDS = 120
# Optimize safe, current-user background processes while FocusOS is running.
AUTO_OPTIMIZE_USER_PROCESSES = True

RESOURCE_PROFILE_DEFAULT = "balanced"
RESOURCE_PROFILE_AUTO = True
TASK_PROFILE_MAP = {
    "coding": "focus",
    "ml_training": "focus",
    "presentation": "focus",
    "communication": "focus",
    "rendering": "performance",
    "browsing": "balanced",
    "idle": "balanced",
}
RESOURCE_PROFILES = {
    "focus": {
        "label": "Focus",
        "description": (
            "Auto-tuned for coding and deep work: aggressive background memory "
            "cleanup after 1 minute; warning thresholds: CPU 70%, RAM 75%, disk 90%."
        ),
        "suspend_delay_seconds": 60,
        "cpu_warning": 70.0,
        "ram_warning": 75.0,
        "disk_warning": 90.0,
    },
    "balanced": {
        "label": "Balanced",
        "description": (
            "Default policy for general browsing: background memory cleanup "
            "after 2 minutes; warning thresholds: CPU 80%, RAM 85%, disk 90%."
        ),
        "suspend_delay_seconds": AUTO_SUSPEND_DELAY_SECONDS,
        "cpu_warning": 80.0,
        "ram_warning": 85.0,
        "disk_warning": 90.0,
    },
    "performance": {
        "label": "Performance",
        "description": (
            "Auto-tuned for rendering and heavy workloads: relaxed background memory "
            "cleanup after 5 minutes; warning thresholds: CPU 90%, RAM 90%, disk 95%."
        ),
        "suspend_delay_seconds": 300,
        "cpu_warning": 90.0,
        "ram_warning": 90.0,
        "disk_warning": 95.0,
    },
}

# ---------------------------------------------------------------------------
# ML Power Mode – activated automatically when focus_mode == "ml_training"
# ---------------------------------------------------------------------------
# Suspend background apps after only 10 s instead of the profile default.
ML_POWER_MODE_SUSPEND_DELAY = 10.0
# Priority class used to boost the ML/AI training process on Windows.
# HIGH_PRIORITY_CLASS gives maximum CPU scheduling without risking a system
# freeze (REALTIME_PRIORITY_CLASS is intentionally avoided).
ML_POWER_MODE_BOOST_CLASS = "high"

CLEANUP_MIN_AGE_DAYS = 7
CLEANUP_DIAGNOSTIC_MIN_AGE_DAYS = 30
CLEANUP_AUTO_MIN_AGE_SECONDS = 60 * 60
CLEANUP_MAX_CANDIDATES = 1000
