"""Adaptador para modelos MDX-Net (UVR) en ONNX: aislar voz o quitar reverberación.

Un modelo MDX-Net recibe un espectrograma STFT estéreo (re/im de L y R) de `dim_t` tramas y
`dim_f` bins, y devuelve el "stem primario" (voz, o reverberación según el modelo). El adaptador:
remuestrea 48 kHz -> 44,1 kHz, procesa en trozos solapados (mismo esquema que Ultimate Vocal
Remover), y devuelve mono a 48 kHz con la MISMA longitud que la entrada (cumple `Denoiser`).
El STFT va incluido en este módulo (numpy), así que no depende de PyTorch.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import numpy as np
from scipy.signal import resample_poly

from .settings import SAMPLE_RATE

log = logging.getLogger(__name__)

MODEL_SR = 44_100
HOP = 1024


@dataclass(frozen=True)
class MdxParams:
    n_fft: int
    dim_f: int
    dim_t: int
    compensate: float = 1.0
    #: "primary": la salida del modelo es lo que se quiere conservar (voz).
    #: "residual": se conserva mezcla - salida (p. ej. el modelo devuelve la reverberación).
    keep: str = "primary"


def _stft(x: np.ndarray, n_fft: int, window: np.ndarray) -> np.ndarray:
    """x: (n,) -> (n_fft//2+1, frames), como torch.stft(center=True, ventana Hann periódica)."""
    pad = n_fft // 2
    xp = np.pad(x, (pad, pad), mode="reflect")
    frames = 1 + (len(xp) - n_fft) // HOP
    idx = np.arange(n_fft)[None, :] + HOP * np.arange(frames)[:, None]
    return np.fft.rfft(xp[idx] * window, axis=1).T.astype(np.complex64)


def _istft(spec: np.ndarray, n_fft: int, window: np.ndarray, length: int) -> np.ndarray:
    frames = spec.shape[1]
    out = np.zeros(HOP * (frames - 1) + n_fft, dtype=np.float64)
    norm = np.zeros_like(out)
    chunks = np.fft.irfft(spec.T, n=n_fft, axis=1) * window
    w2 = window**2
    for t in range(frames):
        s = t * HOP
        out[s : s + n_fft] += chunks[t]
        norm[s : s + n_fft] += w2
    out = out / np.maximum(norm, 1e-8)
    pad = n_fft // 2
    return out[pad : pad + length].astype(np.float32)


class MdxNet:
    """Carga un `.onnx` MDX-Net. `providers=None` elige el más rápido entre aceleración y CPU."""

    def __init__(self, model_path: str, params: MdxParams, providers: list[str] | None = None) -> None:
        import onnxruntime as ort

        from .denoise import preferred_providers

        self.params = params
        self.window = np.hanning(params.n_fft + 1)[:-1].astype(np.float64)  # Hann periódica
        self.chunk = HOP * (params.dim_t - 1)
        self.trim = params.n_fft // 2
        self.gen = self.chunk - 2 * self.trim
        if self.gen <= 0:
            raise ValueError("Parámetros MDX incoherentes (n_fft demasiado grande para dim_t).")
        self._path = model_path
        self.providers = providers or preferred_providers()
        self._session = self._open(ort, self.providers)
        if providers is None and self.providers[0] != "CPUExecutionProvider":
            self._keep_fastest(ort)

    def _open(self, ort, providers: list[str]):
        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        return ort.InferenceSession(self._path, sess_options=opts, providers=providers)

    def _keep_fastest(self, ort) -> None:
        probe = (0.05 * np.random.default_rng(1).standard_normal(self.chunk)).astype(np.float32)

        def timed(session) -> float:
            self._session = session
            self._run_chunk(probe, probe)  # calentamiento
            t0 = time.perf_counter()
            self._run_chunk(probe, probe)
            return time.perf_counter() - t0

        accel_session = self._session
        try:
            accel = timed(accel_session)
        except Exception:  # noqa: BLE001
            accel = float("inf")
        cpu_session = self._open(ort, ["CPUExecutionProvider"])
        cpu = timed(cpu_session)
        if accel < cpu:
            self._session = accel_session
        else:
            self._session, self.providers = cpu_session, ["CPUExecutionProvider"]
        log.info("MDX: aceleración %.2fs vs CPU %.2fs -> %s", accel, cpu, self.providers)

    def _run_chunk(self, left: np.ndarray, right: np.ndarray) -> np.ndarray:
        """Un trozo de `chunk` muestras por canal -> (2, chunk) del stem primario."""
        p = self.params
        specs = [_stft(c.astype(np.float64), p.n_fft, self.window)[: p.dim_f] for c in (left, right)]
        x = np.stack([specs[0].real, specs[0].imag, specs[1].real, specs[1].imag])[None].astype(np.float32)
        y = self._session.run(None, {self._session.get_inputs()[0].name: x})[0][0]
        res = []
        for i in range(2):
            spec = np.zeros((p.n_fft // 2 + 1, p.dim_t), dtype=np.complex64)
            spec[: p.dim_f] = y[2 * i] + 1j * y[2 * i + 1]
            res.append(_istft(spec, p.n_fft, self.window, self.chunk))
        return np.stack(res) * p.compensate

    def _separate(self, mono44: np.ndarray) -> np.ndarray:
        n = len(mono44)
        pad = self.gen + self.trim - (n % self.gen)
        padded = np.concatenate([np.zeros(self.trim, np.float32), mono44, np.zeros(pad, np.float32)])
        out = []
        for start in range(0, n + pad - self.trim, self.gen):
            piece = padded[start : start + self.chunk]
            if len(piece) < self.chunk:
                piece = np.pad(piece, (0, self.chunk - len(piece)))
            y = self._run_chunk(piece, piece)  # mono duplicado a estéreo
            out.append(y.mean(axis=0)[self.trim : self.chunk - self.trim])
        return np.concatenate(out)[:n]

    def enhance(self, audio: np.ndarray, keep: str | None = None) -> np.ndarray:
        keep = keep or self.params.keep
        n = len(audio)
        if n == 0:
            return audio.astype(np.float32, copy=True)
        mono44 = resample_poly(audio.astype(np.float64), MODEL_SR // 300, SAMPLE_RATE // 300).astype(np.float32)
        primary44 = self._separate(mono44)
        kept44 = primary44 if keep == "primary" else mono44 - primary44
        out = resample_poly(kept44.astype(np.float64), SAMPLE_RATE // 300, MODEL_SR // 300)
        out = out[:n] if len(out) >= n else np.pad(out, (0, n - len(out)))
        return np.nan_to_num(out).astype(np.float32)

    #: contexto adicional (s) que el pipeline debe dar a este modelo además de CONTEXT_S
    @property
    def context_s(self) -> float:
        return self.trim / MODEL_SR
