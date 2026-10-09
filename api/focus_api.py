"""Local API endpoint definitions for FocusOS operations."""

from typing import Callable, Dict

from fastapi import FastAPI, HTTPException

from core.focus_runtime import FocusRuntime
from core.storage_manager import StorageManager


class FocusAPI:
    """Acts as the controller layer between the UI and the core system."""

    def __init__(self, runtime: FocusRuntime | None = None):
        self.status = "ready"
        self.runtime = runtime or FocusRuntime()
        self.storage_manager = StorageManager()

    def healthcheck(self):
        """Return the health status of the service."""
        return {"status": self.status}

    def get_state(self):
        """Refresh live monitoring while enabled and return the shared state."""
        if self.runtime.state.status in {"RUNNING", "PAUSED"}:
            return self.runtime.refresh()
        return self.runtime.snapshot()

    def create_app(self) -> FastAPI:
        """Build the local HTTP API used by the dashboard."""
        app = FastAPI(title="FocusOS Local API")

        @app.get("/health")
        def healthcheck():
            return self.healthcheck()

        @app.get("/state")
        def get_state():
            return self.get_state()

        @app.post("/start")
        def start():
            return self.runtime.start()

        @app.post("/pause")
        def pause():
            return self._run_control(self.runtime.pause)

        @app.post("/resume")
        def resume():
            return self._run_control(self.runtime.resume)

        @app.post("/stop")
        def stop():
            return self.runtime.stop()

        @app.post("/emergency-disable")
        def emergency_disable():
            return self.runtime.emergency_disable()

        @app.get("/storage/candidates")
        def storage_candidates():
            return self.storage_manager.scan_candidates()

        return app

    @staticmethod
    def _run_control(action: Callable[[], Dict[str, object]]) -> Dict[str, object]:
        try:
            return action()
        except RuntimeError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
