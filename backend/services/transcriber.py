import glob
import logging
import os
import sys
from typing import Callable, Optional

from backend import paths

os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

log = logging.getLogger(__name__)


def _register_app_home_cuda() -> bool:
    """Make CUDA libs that first-run setup downloaded into the app home loadable.

    The nvidia-*-cu12 wheels unzip to <cuda_dir>/nvidia/<pkg>/{bin,lib}. On Windows
    the DLLs live in bin/ and must be registered with os.add_dll_directory(); on
    Linux the .so files live in lib/ and go on LD_LIBRARY_PATH. Returns True if a
    cuBLAS library was found there."""
    nvidia_base = os.path.join(paths.cuda_dir(), "nvidia")
    if not os.path.isdir(nvidia_base):
        return False
    sub = "bin" if sys.platform == "win32" else "lib"
    lib_dirs = [
        os.path.join(nvidia_base, pkg, sub)
        for pkg in os.listdir(nvidia_base)
        if os.path.isdir(os.path.join(nvidia_base, pkg, sub))
    ]
    found = any(
        glob.glob(os.path.join(d, "cublas*")) or glob.glob(os.path.join(d, "libcublas.so*"))
        for d in lib_dirs
    )
    if not found:
        return False
    if sys.platform == "win32":
        for d in lib_dirs:
            try:
                os.add_dll_directory(d)
            except (OSError, AttributeError):
                pass
    else:
        os.environ["LD_LIBRARY_PATH"] = ":".join(lib_dirs) + ":" + os.environ.get("LD_LIBRARY_PATH", "")
    return True


def _cublas_available() -> bool:
    """Check if libcublas is loadable — app-home download, venv, or system install."""
    # First-run-downloaded libs in the per-user app home (the packaged-app path).
    if _register_app_home_cuda():
        return True
    # Standard system paths (Linux)
    system_paths = [
        "/usr/local/cuda*/lib64/libcublas.so*",
        "/usr/lib/*/libcublas.so*",
        "/usr/lib/libcublas.so*",
    ]
    if any(glob.glob(p) for p in system_paths):
        return True
    # venv-installed via pip (nvidia-cublas-cu12) — dev on Linux
    for site in sys.path:
        if glob.glob(os.path.join(site, "nvidia", "cublas", "lib", "libcublas.so*")):
            # Add the venv nvidia lib dirs to LD_LIBRARY_PATH so ctranslate2 finds them
            nvidia_base = os.path.join(site, "nvidia")
            extra = ":".join(
                os.path.join(nvidia_base, pkg, "lib")
                for pkg in os.listdir(nvidia_base)
                if os.path.isdir(os.path.join(nvidia_base, pkg, "lib"))
            ) if os.path.isdir(nvidia_base) else ""
            if extra:
                os.environ["LD_LIBRARY_PATH"] = extra + ":" + os.environ.get("LD_LIBRARY_PATH", "")
            return True
    return False


def detect_device() -> tuple[str, str]:
    """Return (device, compute_type). Uses CUDA only if the runtime libs exist."""
    if not _cublas_available():
        # Block ctranslate2 from trying CUDA — avoids 'libcublas not found' errors
        os.environ["CUDA_VISIBLE_DEVICES"] = ""
        log.info("CUDA runtime libs not found — using CPU (int8)")
        return "cpu", "int8"

    try:
        import ctranslate2
        types = ctranslate2.get_supported_compute_types("cuda")
        if types:
            compute = "float16" if "float16" in types else "int8_float32" if "int8_float32" in types else "int8"
            log.info("GPU available — using CUDA (%s)", compute)
            return "cuda", compute
    except Exception as e:
        log.info("CUDA probe failed (%s) — using CPU", e)

    return "cpu", "int8"


class Transcriber:
    def __init__(self, model_path: str, device: str = "auto", compute_type: str = "auto"):
        from faster_whisper import WhisperModel
        if device == "auto" or compute_type == "auto":
            detected_device, detected_compute = detect_device()
            device = detected_device if device == "auto" else device
            compute_type = detected_compute if compute_type == "auto" else compute_type
        log.info("Loading Whisper model on %s (%s)", device, compute_type)
        self._model = WhisperModel(model_path, device=device, compute_type=compute_type)
        self._model_path = model_path
        self.device = device
        self.compute_type = compute_type

    def transcribe_file(
        self,
        audio_path: str,
        output_path: str,
        progress_callback: Optional[Callable[[float], None]] = None,
    ) -> str:
        segments, info = self._model.transcribe(audio_path, language="he", beam_size=5)
        total = info.duration or 1.0
        parts = []
        for segment in segments:
            parts.append(segment.text)
            if progress_callback:
                progress_callback(min(segment.end / total, 1.0))
        if progress_callback:
            progress_callback(1.0)

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(parts))

        return output_path
