"""Smoke tests for the initial FocusOS scaffold."""

from core.focus_engine import FocusEngine


def test_focus_engine_initializes():
    engine = FocusEngine()
    assert engine.detect_active_application() is None
