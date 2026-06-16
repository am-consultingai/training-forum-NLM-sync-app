"""
First-run provisioning.

The installer is deliberately lean, so the heavy pieces are fetched once on first
launch into the per-user app home:

* the Hebrew transcription model (``ivrit-ai/whisper-large-v3-ct2``, ~3 GB), and
* on NVIDIA machines, the CUDA runtime libraries (cuBLAS + cuDNN).

The CUDA libs are fetched by downloading the official ``nvidia-*-cu12`` wheels
straight from PyPI and unzipping the DLLs — this works inside a frozen PyInstaller
app where ``pip`` is not available. Non-NVIDIA machines skip the CUDA step and run
transcription on CPU.
"""
import io
import json
import logging
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from typing import Callable, Optional

from backend import paths
from backend.config import settings

log = logging.getLogger(__name__)

MODEL_REPO = "ivrit-ai/whisper-large-v3-ct2"

# (package on PyPI, version-prefix filter or None for latest)
_CUDA_WHEELS = [
    ("nvidia-cublas-cu12", None),
    ("nvidia-cudnn-cu12", "9."),  # ctranslate2 (CUDA 12) needs cuDNN 9.x
]

# progress(message, fraction)  — fraction is 0..1, or None for indeterminate.
ProgressCb = Callable[[str, Optional[float]], None]


# ── State checks ─────────────────────────────────────────────────────────────

def model_dir() -> str:
    """Where the model lives / will be downloaded — the configured whisper path
    (defaults to the app-home model dir; an env override points elsewhere in dev)."""
    return settings.whisper_model_path


def model_present() -> bool:
    return os.path.isfile(os.path.join(model_dir(), "model.bin"))


def gpu_present() -> bool:
    """Best-effort NVIDIA detection that avoids importing heavy libraries."""
    if shutil.which("nvidia-smi"):
        try:
            subprocess.run(["nvidia-smi"], capture_output=True, timeout=10, check=True)
            return True
        except Exception:
            return False
    if sys.platform == "win32":
        return os.path.exists(os.path.join(os.environ.get("WINDIR", r"C:\Windows"),
                                           "System32", "nvml.dll"))
    return False


def cuda_libs_present() -> bool:
    d = paths.cuda_dir()
    if not os.path.isdir(d):
        return False
    for _root, _dirs, files in os.walk(d):
        if any(f.startswith(("cublas", "libcublas")) for f in files):
            return True
    return False


# ── Model download ───────────────────────────────────────────────────────────

def download_model(progress: Optional[ProgressCb] = None) -> str:
    from huggingface_hub import snapshot_download

    target = model_dir()
    os.makedirs(target, exist_ok=True)
    if progress:
        progress(f"Downloading transcription model ({MODEL_REPO}, ~3 GB)…", None)
    snapshot_download(repo_id=MODEL_REPO, local_dir=target)
    if progress:
        progress("Transcription model ready.", 1.0)
    return target


# ── CUDA libraries (NVIDIA only) ───────────────────────────────────────────────

def _platform_tag() -> str:
    if sys.platform == "win32":
        return "win_amd64"
    if sys.platform == "darwin":
        return "macosx"  # no CUDA on mac; gpu_present() is False there anyway
    return "manylinux"  # linux x86_64 wheels


def _pick_wheel_url(pkg: str, version_prefix: Optional[str]) -> str:
    with urllib.request.urlopen(f"https://pypi.org/pypi/{pkg}/json", timeout=30) as r:
        data = json.load(r)
    tag = _platform_tag()
    releases = data.get("releases", {})
    versions = sorted(releases.keys(), reverse=True)
    if version_prefix:
        versions = [v for v in versions if v.startswith(version_prefix)]
    for version in versions:
        for f in releases[version]:
            if f["filename"].endswith(".whl") and tag in f["filename"]:
                return f["url"]
    raise RuntimeError(f"No {tag} wheel found for {pkg}")


def ensure_cuda_libs(progress: Optional[ProgressCb] = None) -> bool:
    """Install CUDA runtime DLLs into the app home (NVIDIA machines only).
    Returns True if libs are present afterwards, False if skipped (no GPU)."""
    if not gpu_present():
        log.info("No NVIDIA GPU detected — skipping CUDA libraries (CPU mode).")
        return False
    if cuda_libs_present():
        return True

    target = paths.cuda_dir()
    os.makedirs(target, exist_ok=True)
    for i, (pkg, version_prefix) in enumerate(_CUDA_WHEELS, start=1):
        if progress:
            progress(f"Installing GPU acceleration ({pkg})…", None)
        url = _pick_wheel_url(pkg, version_prefix)
        with urllib.request.urlopen(url, timeout=120) as resp:
            blob = resp.read()
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            zf.extractall(target)
    if progress:
        progress("GPU acceleration ready.", 1.0)
    return True
