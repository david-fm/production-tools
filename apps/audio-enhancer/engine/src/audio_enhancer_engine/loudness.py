"""Medición de loudness integrado según ITU-R BS.1770-4 / EBU R128, en streaming (sin cargar todo en RAM).

Simplificación documentada: todos los canales pesan 1.0 (correcto para mono/estéreo/5.1 sin
considerar el peso extra de surround). Se valida contra `pyloudnorm` en los tests.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import sosfilt, sosfilt_zi, tf2sos

from .settings import SAMPLE_RATE

# Filtro K (48 kHz): etapa 1 = realce de agudos, etapa 2 = pasa-altos (BS.1770-4, tabla 1 y 2).
_K_SOS = np.vstack(
    [
        tf2sos(
            [1.53512485958697, -2.69169618940638, 1.19839281085285],
            [1.0, -1.69065929318241, 0.73248077421585],
        ),
        tf2sos([1.0, -2.0, 1.0], [1.0, -1.99004745483398, 0.99007225036621]),
    ]
)
_BLOCK = int(0.4 * SAMPLE_RATE)  # ventana de 400 ms
_HOP = int(0.1 * SAMPLE_RATE)  # solape del 75 %


class LoudnessMeter:
    """Acumula audio (n, canales) en trozos; `integrated()` devuelve LUFS (o None si no hay audio medible)."""

    def __init__(self, channels: int) -> None:
        self.channels = channels
        self._zi = [sosfilt_zi(_K_SOS) * 0.0 for _ in range(channels)]
        self._pending = np.zeros(0, dtype=np.float64)  # potencia sumada de muestras aún sin completar un bin de 100 ms
        self._bin_sums: list[float] = []

    def add(self, chunk: np.ndarray) -> None:
        chunk = np.asarray(chunk, dtype=np.float64)
        if chunk.ndim == 1:
            chunk = chunk[:, None]
        power = np.zeros(chunk.shape[0], dtype=np.float64)
        for ch in range(self.channels):
            y, self._zi[ch] = sosfilt(_K_SOS, chunk[:, ch], zi=self._zi[ch])
            power += y * y
        data = np.concatenate([self._pending, power])
        full = len(data) // _HOP
        if full:
            self._bin_sums.extend(data[: full * _HOP].reshape(full, _HOP).sum(axis=1).tolist())
        self._pending = data[full * _HOP :]

    def integrated(self) -> float | None:
        bins = np.asarray(self._bin_sums)
        n_windows = len(bins) - 3
        if n_windows < 1:
            return None
        windows = (bins[:-3] + bins[1:-2] + bins[2:-1] + bins[3:]) / _BLOCK
        with np.errstate(divide="ignore"):
            lufs = -0.691 + 10 * np.log10(windows)
        absolute = windows[lufs > -70.0]
        if len(absolute) == 0:
            return None
        relative_gate = -0.691 + 10 * np.log10(absolute.mean()) - 10.0
        gated = windows[lufs > relative_gate]
        if len(gated) == 0:
            return None
        return float(-0.691 + 10 * np.log10(gated.mean()))
