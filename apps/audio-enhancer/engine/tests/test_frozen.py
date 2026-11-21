"""Prueba el binario CONGELADO (PyInstaller): carga ONNX Runtime y lista proveedores.

Se omite si el binario de este equipo no está construido (en CI se construye antes).
Cierra el [UNVERIFIED] de "ONNX Runtime funciona dentro del sidecar congelado".
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import soundfile as sf
from conftest import EngineClient
from helpers import SR, speechlike, write_wav

BINARIES = Path(__file__).resolve().parents[2] / "src-tauri" / "binaries"


def _host_triple() -> str | None:
    try:
        out = subprocess.run(["rustc", "-vV"], capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    return next((ln.split(": ", 1)[1] for ln in out.splitlines() if ln.startswith("host: ")), None)


def _frozen_binary() -> Path | None:
    triple = _host_triple()
    if triple is None:
        return None
    exe = ".exe" if sys.platform == "win32" else ""
    path = BINARIES / f"audio-enhancer-engine-{triple}{exe}"
    return path if path.exists() else None


@pytest.mark.skipif(_frozen_binary() is None, reason="sidecar congelado no construido")
def test_frozen_binary_lists_onnx_providers():
    binary = _frozen_binary()
    assert binary is not None
    client = EngineClient([str(binary)])
    try:
        reply = client.rpc({"id": 1, "cmd": "providers"}, timeout=90)
        assert reply["ok"] is True, reply
        providers = reply["result"]
        assert "CPUExecutionProvider" in providers
        if sys.platform == "win32":
            assert "DmlExecutionProvider" in providers
        if sys.platform == "darwin":
            assert "CoreMLExecutionProvider" in providers
        print("Proveedores en binario congelado:", providers)  # queda en el log del CI
    finally:
        client.close()


def _ffmpeg_env(tmp_path: Path) -> dict[str, str]:
    """Carpeta con ffmpeg/ffprobe sin sufijo de triple, como los deja Tauri junto al ejecutable instalado."""
    env = dict(os.environ)
    triple = _host_triple()
    exe = ".exe" if sys.platform == "win32" else ""
    ff = BINARIES / f"ffmpeg-{triple}{exe}"
    if ff.exists():
        folder = tmp_path / "ffbin"
        folder.mkdir()
        for name in ("ffmpeg", "ffprobe"):
            shutil.copy2(BINARIES / f"{name}-{triple}{exe}", folder / f"{name}{exe}")
        env["AUDIO_ENHANCER_FFMPEG_DIR"] = str(folder)
    env["AUDIO_ENHANCER_WORK_DIR"] = str(tmp_path / "work")
    return env


@pytest.mark.skipif(_frozen_binary() is None, reason="sidecar congelado no construido")
@pytest.mark.parametrize("denoise", [False, True])
def test_frozen_binary_processes_audio_end_to_end(tmp_path, denoise):
    """Un trabajo real en el binario congelado: numpy, scipy, soundfile, ffmpeg y (opcional) el modelo ONNX."""
    binary = _frozen_binary()
    assert binary is not None
    src = write_wav(tmp_path / "in.wav", speechlike(8, 1))
    client = EngineClient([str(binary)], env=_ffmpeg_env(tmp_path))
    try:
        client.send({"id": 1, "cmd": "enhance", "input": str(src), "output": str(tmp_path / "out.wav"),
                     "settings": {"denoise": denoise}})  # fmt: skip
        while True:
            msg = client.recv(timeout=180)
            if msg.get("id") == 1 and "ok" in msg:
                break
        assert msg["ok"] is True, msg
        assert sf.info(tmp_path / "out.wav").frames == 8 * SR
    finally:
        client.close()
