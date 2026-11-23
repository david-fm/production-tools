"""Etapas deterministas de limpieza (filtros)."""

from __future__ import annotations

from typing import ClassVar

import numpy as np
from scipy.signal import butter, iirnotch, sosfilt, tf2sos

from .settings import SAMPLE_RATE, Settings


def build_filter(settings: Settings) -> np.ndarray | None:
    """Cascada SOS con pasa-altos y notches de zumbido; None si no hay nada que filtrar."""
    sections: list[np.ndarray] = []
    if settings.highpass_hz is not None:
        sections.append(butter(2, settings.highpass_hz, btype="highpass", fs=SAMPLE_RATE, output="sos"))
    if settings.notch_hz is not None:
        for k in range(1, settings.notch_harmonics + 1):
            freq = settings.notch_hz * k
            if freq < SAMPLE_RATE / 2 * 0.9:
                b, a = iirnotch(freq, Q=30.0, fs=SAMPLE_RATE)
                sections.append(tf2sos(b, a))
    return np.vstack(sections) if sections else None


def apply_filter(sos: np.ndarray | None, audio: np.ndarray) -> np.ndarray:
    """Filtra (n, canales) con estado inicial en cero. El llamador aporta contexto previo de calentamiento."""
    if sos is None:
        return audio
    return sosfilt(sos, audio, axis=0).astype(np.float32)


class SosFilter:
    """Una etapa de filtro de la cadena (misma interfaz que un modelo: `enhance` sobre un canal)."""

    providers: ClassVar[list[str]] = []
    context_s = 0.0

    def __init__(self, sos: np.ndarray) -> None:
        self.sos = sos

    def enhance(self, audio: np.ndarray) -> np.ndarray:
        return sosfilt(self.sos, audio).astype(np.float32)


def highpass_sos(hz: float) -> np.ndarray:
    return butter(2, hz, btype="highpass", fs=SAMPLE_RATE, output="sos")


def notch_sos(hz: float, harmonics: int) -> np.ndarray | None:
    sections = []
    for k in range(1, int(harmonics) + 1):
        freq = hz * k
        if freq < SAMPLE_RATE / 2 * 0.9:
            b, a = iirnotch(freq, Q=30.0, fs=SAMPLE_RATE)
            sections.append(tf2sos(b, a))
    return np.vstack(sections) if sections else None
