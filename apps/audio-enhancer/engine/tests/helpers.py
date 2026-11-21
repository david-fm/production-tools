"""Generadores de audio sintético y utilidades de comparación para los tests del motor."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

SR = 48_000


def noise(seconds: float, channels: int = 1, level: float = 0.1, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return (level * rng.standard_normal((int(seconds * SR), channels))).astype(np.float32)


def speechlike(seconds: float, channels: int = 1, seed: int = 0) -> np.ndarray:
    """Ráfagas de tonos con envolvente + ruido de fondo suave (volumen bajo, para probar normalización)."""
    t = np.arange(int(seconds * SR)) / SR
    env = (np.sin(2 * np.pi * 1.5 * t) > 0).astype(np.float32)
    tone = 0.03 * np.sin(2 * np.pi * 300 * t) * env
    out = tone[:, None] + 0.002 * noise(seconds, channels, 1.0, seed)
    return out.astype(np.float32)


def write_wav(path: Path, audio: np.ndarray) -> Path:
    sf.write(path, audio, SR, subtype="FLOAT")
    return path


def have_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def run_ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", *args], check=True)
