"""Runtime configuration for the FocusOS prototype."""

FOCUSOS_NAME = "FocusOS"
DEFAULT_LOG_LEVEL = "INFO"
SYSTEM_MODE = "monitoring"

# Add exact executable names here to opt in to automatic suspension.
AUTO_SUSPEND_ALLOWLIST = ()
AUTO_SUSPEND_DELAY_SECONDS = 120
# Optimize safe, current-user background processes while FocusOS is running.
AUTO_OPTIMIZE_USER_PROCESSES = True

CLEANUP_MIN_AGE_DAYS = 7
CLEANUP_DIAGNOSTIC_MIN_AGE_DAYS = 30
CLEANUP_AUTO_MIN_AGE_SECONDS = 60 * 60
CLEANUP_MAX_CANDIDATES = 1000
