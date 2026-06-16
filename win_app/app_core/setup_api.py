"""
First-run setup endpoints.

``GET  /api/setup/status`` — what's present (model / GPU / CUDA libs) and whether
the app is ready to use.
``POST /api/setup/start``  — kick off the model + CUDA download in a background
thread (idempotent while running).
``GET  /api/setup/stream`` — SSE stream of progress messages for the setup screen.
"""
import json
import logging
import queue
import threading
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from win_app.app_core import bootstrap

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/setup", tags=["setup"])

_state = {"running": False, "done": False, "error": None, "message": ""}
_lock = threading.Lock()
_listeners: list[queue.Queue] = []


def _emit(message: str, fraction: Optional[float] = None):
    _state["message"] = message
    event = {
        "message": message,
        "fraction": fraction,
        "running": _state["running"],
        "done": _state["done"],
        "error": _state["error"],
    }
    for q in list(_listeners):
        q.put(event)


def _run():
    try:
        if not bootstrap.model_present():
            bootstrap.download_model(_emit)
        bootstrap.ensure_cuda_libs(_emit)
        _state["done"] = True
        _state["running"] = False
        _emit("Setup complete.", 1.0)
    except Exception as e:  # noqa: BLE001 — surface any failure to the UI
        log.exception("First-run setup failed")
        _state["error"] = str(e)
        _state["running"] = False
        _emit(f"Setup failed: {e}")


@router.get("/status")
def setup_status():
    return {
        "ready": bootstrap.model_present(),
        "model_present": bootstrap.model_present(),
        "gpu_present": bootstrap.gpu_present(),
        "cuda_libs_present": bootstrap.cuda_libs_present(),
        "running": _state["running"],
        "done": _state["done"],
        "error": _state["error"],
        "message": _state["message"],
    }


@router.post("/start")
def setup_start():
    with _lock:
        if _state["running"]:
            return {"running": True}
        _state.update(running=True, done=False, error=None, message="Starting…")
        threading.Thread(target=_run, name="first-run-setup", daemon=True).start()
    return {"running": True}


@router.get("/stream")
def setup_stream():
    q: queue.Queue = queue.Queue()
    _listeners.append(q)

    def gen():
        try:
            snapshot = {
                "message": _state["message"],
                "running": _state["running"],
                "done": _state["done"],
                "error": _state["error"],
            }
            yield f"data: {json.dumps(snapshot)}\n\n"
            while True:
                event = q.get()
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("done") or event.get("error"):
                    break
        finally:
            if q in _listeners:
                _listeners.remove(q)

    return StreamingResponse(gen(), media_type="text/event-stream")
