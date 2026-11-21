"""Descarga verificada de modelos (versión mínima de M1; el gestor completo con interfaz es v0.2.0)."""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import tarfile
import threading
import urllib.request
import uuid
from pathlib import Path

DFN3_URL = "https://github.com/Rikorose/DeepFilterNet/raw/main/models/DeepFilterNet3_onnx.tar.gz"
DFN3_SHA256 = "c94d91f70911001c946e0fabb4aa9adc37045f45a03b56008cb0c8244cb63616"
MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024  # el paquete real pesa ~8 MB
_FILES = ("enc.onnx", "erb_dec.onnx", "df_dec.onnx", "config.ini")
_MARKER = ".ok"  # se escribe al final: una instalación interrumpida nunca parece completa
_install_lock = threading.Lock()


def default_models_dir() -> Path:
    override = os.environ.get("AUDIO_ENHANCER_MODELS_DIR")
    if override:
        return Path(override)
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/Library/Application Support")
    return Path(base) / "AudioEnhancer" / "models"


def model_folder(models_dir: Path | None = None) -> Path:
    return (models_dir or default_models_dir()) / "deepfilternet3"


def is_installed(folder: Path) -> bool:
    return (folder / _MARKER).is_file() and all((folder / f).is_file() for f in _FILES)


def _download() -> bytes:
    with urllib.request.urlopen(DFN3_URL, timeout=60) as resp:
        blob = resp.read(MAX_DOWNLOAD_BYTES + 1)
    if len(blob) > MAX_DOWNLOAD_BYTES:
        raise RuntimeError("La descarga del modelo supera el tamaño esperado; se descartó.")
    return blob


def ensure_deepfilternet3(models_dir: Path | None = None) -> Path:
    """Devuelve la carpeta con DeepFilterNet3; la descarga y verifica sha256 si no está instalada.

    La instalación es atómica: se extrae a una carpeta temporal y se publica con un único rename.
    """
    target = model_folder(models_dir)
    with _install_lock:
        if is_installed(target):
            return target
        blob = _download()
        digest = hashlib.sha256(blob).hexdigest()
        if digest != DFN3_SHA256:
            raise RuntimeError(f"sha256 del modelo no coincide (esperado {DFN3_SHA256}, recibido {digest})")
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.parent / f".deepfilternet3.{uuid.uuid4().hex}.tmp"
        tmp.mkdir()
        try:
            with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
                for member in tar.getmembers():
                    name = os.path.basename(member.name)  # nunca se usa la ruta del archivo: sin path traversal
                    if member.isfile() and name in _FILES:
                        data = tar.extractfile(member)
                        assert data is not None
                        (tmp / name).write_bytes(data.read())
            missing = [f for f in _FILES if not (tmp / f).is_file()]
            if missing:
                raise RuntimeError(f"El paquete del modelo no contiene: {missing}")
            (tmp / _MARKER).write_text(DFN3_SHA256)
            shutil.rmtree(target, ignore_errors=True)  # instalación previa incompleta, si la hubo
            os.replace(tmp, target)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return target
