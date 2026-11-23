"""Reducción de ruido. DeepFilterNet3 sobre ONNX Runtime, con el pre/post-procesado en numpy.

El procesado (STFT, bandas ERB, normalización, máscara y filtro profundo) sigue el proyecto
DeepFilterNet de Hendrik Schröter (MIT/Apache-2.0), adaptado de la exportación ONNX sin PyTorch
publicada por SayedShaun/DeepFilterNet3-onnx (MIT/Apache-2.0). Ver THIRD_PARTY_NOTICES.md.
"""

from __future__ import annotations

import configparser
import logging
import math
import os
import sys
from typing import Protocol

import numpy as np

from .settings import SAMPLE_RATE

log = logging.getLogger(__name__)

MEAN_NORM_INIT = (-60.0, -90.0)
UNIT_NORM_INIT = (0.001, 0.0001)
ERB_NORM_SCALE = 40.0


class Denoiser(Protocol):
    """Contrato de cualquier modelo de reducción de ruido: mono float32 a 48 kHz in -> out (misma longitud)."""

    def enhance(self, audio: np.ndarray) -> np.ndarray: ...


class Chain:
    """Etapas en orden fijo (separar -> reducir ruido), cada una con su intensidad (mezcla con la entrada de la etapa)."""

    def __init__(self, stages: list[tuple[Denoiser, float]], fingerprints: dict[str, str], providers: list[str]) -> None:
        self.stages, self.fingerprints, self.providers = stages, fingerprints, providers

    def enhance(self, audio: np.ndarray) -> np.ndarray:
        x = audio.astype(np.float32, copy=False)
        for model, strength in self.stages:
            if strength <= 0:
                continue
            wet = model.enhance(x)
            x = wet if strength >= 1 else (strength * wet + (1.0 - strength) * x).astype(np.float32)
        return x.astype(np.float32, copy=False)


class IdentityDenoiser:
    """Modelo nulo para tests: devuelve la entrada."""

    def enhance(self, audio: np.ndarray) -> np.ndarray:
        return audio.astype(np.float32, copy=True)


def preferred_providers() -> list[str]:
    """Orden de preferencia de ONNX Runtime según la plataforma; CPU siempre al final como respaldo."""
    import onnxruntime as ort

    available = set(ort.get_available_providers())
    # CoreML se omite por defecto: con longitudes variables suele ser más lento o fallar; se valida en el benchmark.
    wanted = ["DmlExecutionProvider"] if sys.platform == "win32" else []
    return [p for p in wanted if p in available] + ["CPUExecutionProvider"]


def _freq2erb(f: np.ndarray | float) -> np.ndarray | float:
    return 9.265 * np.log1p(f / (24.7 * 9.265))


def _erb2freq(e: float) -> float:
    return 24.7 * 9.265 * (math.exp(e / 9.265) - 1.0)


def erb_widths(sr: int, fft_size: int, nb_bands: int, min_nb_freqs: int) -> np.ndarray:
    """Cantidad de bins STFT en cada banda ERB (port de `erb_fb` de libDF)."""
    freq_width = sr / fft_size
    erb_low, erb_high = _freq2erb(0.0), _freq2erb(float(sr // 2))
    step = (erb_high - erb_low) / nb_bands
    widths = np.zeros(nb_bands, dtype=np.int64)
    prev_freq = freq_over = 0
    for i in range(1, nb_bands + 1):
        fb = round(_erb2freq(erb_low + i * step) / freq_width)
        nb_freqs = fb - prev_freq - freq_over
        if nb_freqs < min_nb_freqs:
            freq_over, nb_freqs = min_nb_freqs - nb_freqs, min_nb_freqs
        else:
            freq_over = 0
        widths[i - 1] = nb_freqs
        prev_freq = fb
    widths[nb_bands - 1] += 1
    too_large = int(widths.sum()) - (fft_size // 2 + 1)
    if too_large > 0:
        widths[nb_bands - 1] -= too_large
    return widths


class DeepFilterNet3:
    """Carga enc/erb_dec/df_dec.onnx desde `model_dir` (ver models.py para descargarlos)."""

    def __init__(self, model_dir: str | os.PathLike[str], providers: list[str] | None = None) -> None:
        import onnxruntime as ort

        cfg = configparser.ConfigParser()
        if not cfg.read(os.path.join(model_dir, "config.ini")):
            raise FileNotFoundError(f"Falta config.ini en {model_dir}")
        df = cfg["df"]
        self.sr = int(df["sr"])
        if self.sr != SAMPLE_RATE:
            raise ValueError(f"El modelo espera {self.sr} Hz y el motor trabaja a {SAMPLE_RATE} Hz")
        self.fft_size, self.hop = int(df["fft_size"]), int(df["hop_size"])
        self.nb_erb, self.nb_df = int(df["nb_erb"]), int(df["nb_df"])
        self.df_order, self.df_lookahead = int(df["df_order"]), int(df["df_lookahead"])
        self.conv_lookahead = int(cfg["deepfilternet"]["conv_lookahead"])
        self.norm_alpha = round(math.exp(-(self.hop / self.sr) / 1.0), 2)  # norm_tau = 1 s
        n = self.fft_size
        s = np.sin(0.5 * np.pi * (np.arange(n, dtype=np.float64) + 0.5) / (n // 2))
        self.window = np.sin(0.5 * np.pi * s * s).astype(np.float32)  # ventana Vorbis
        self.erb_w = erb_widths(self.sr, n, self.nb_erb, int(df["min_nb_erb_freqs"]))
        self.erb_inv = np.zeros((self.nb_erb, n // 2 + 1), dtype=np.float32)
        start = 0
        for band, w in enumerate(self.erb_w):
            self.erb_inv[band, start : start + w] = 1.0
            start += w

        self.providers = providers or preferred_providers()
        self._sessions = self._load(ort, model_dir, self.providers)
        if providers is None and self.providers[0] != "CPUExecutionProvider":
            self._keep_fastest(ort, model_dir)

    def _keep_fastest(self, ort, model_dir) -> None:
        """Si hay aceleración (DirectML), se mide contra CPU con 6 s de audio y se usa la más rápida.

        Evita que una GPU lenta o un operador mal soportado empeoren el resultado frente a la CPU.
        """
        import time

        probe = (0.05 * np.random.default_rng(0).standard_normal(6 * self.sr)).astype(np.float32)

        def timed() -> float:
            self.enhance(probe[: self.sr])  # calentamiento (compilación de kernels)
            t0 = time.perf_counter()
            self.enhance(probe)
            return time.perf_counter() - t0

        try:
            accel = timed()
        except Exception:  # noqa: BLE001
            accel = float("inf")
        accel_sessions, accel_providers = self._sessions, self.providers
        self.providers = ["CPUExecutionProvider"]
        self._sessions = self._load(ort, model_dir, self.providers)
        cpu = timed()
        if accel < cpu:
            self._sessions, self.providers = accel_sessions, accel_providers
        log.info("Selección de proveedor: aceleración %.2fs vs CPU %.2fs -> %s", accel, cpu, self.providers)

    def _load(self, ort, model_dir, providers):
        def build(prov: list[str]):
            opts = ort.SessionOptions()
            return {
                name: ort.InferenceSession(os.path.join(model_dir, f"{name}.onnx"), opts, providers=prov)
                for name in ("enc", "erb_dec", "df_dec")
            }

        try:
            return build(providers)
        except Exception:
            if providers == ["CPUExecutionProvider"]:
                raise
            log.warning("Falló %s; se usa CPU", providers)
            self.providers = ["CPUExecutionProvider"]
            return build(self.providers)

    # --- STFT / ISTFT (equivalentes a libDF analysis/synthesis) ---
    def _stft(self, x: np.ndarray) -> np.ndarray:
        n, hop = self.fft_size, self.hop
        xp = np.concatenate([np.zeros(hop, dtype=np.float32), x.astype(np.float32)])
        frames_n = len(x) // hop
        idx = np.arange(frames_n)[:, None] * hop + np.arange(n)[None, :]
        wnorm = 1.0 / (n * n / (2.0 * hop))
        return (np.fft.rfft(xp[idx] * self.window[None, :], axis=1) * wnorm).astype(np.complex64)

    def _istft(self, spec: np.ndarray) -> np.ndarray:
        n, hop = self.fft_size, self.hop
        frames = np.fft.irfft(spec, n=n, axis=1) * n * self.window[None, :]
        out = np.zeros((spec.shape[0] + 1) * hop, dtype=np.float32)
        for t in range(spec.shape[0]):
            out[t * hop : t * hop + n] += frames[t]
        return out[: spec.shape[0] * hop]

    def _features(self, spec: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        a = self.norm_alpha
        power = np.abs(spec) ** 2
        erb_power = np.empty((spec.shape[0], self.nb_erb), dtype=np.float32)
        start = 0
        for band, w in enumerate(self.erb_w):
            erb_power[:, band] = power[:, start : start + w].mean(axis=1)
            start += w
        erb_db = 10.0 * np.log10(erb_power + 1e-10)
        state = np.linspace(MEAN_NORM_INIT[0], MEAN_NORM_INIT[1], self.nb_erb).astype(np.float32)
        erb_feat = np.empty_like(erb_db)
        for t in range(erb_db.shape[0]):
            state = erb_db[t] * (1 - a) + state * a
            erb_feat[t] = (erb_db[t] - state) / ERB_NORM_SCALE
        ustate = np.linspace(UNIT_NORM_INIT[0], UNIT_NORM_INIT[1], self.nb_df).astype(np.float32)
        spec_feat = np.empty((spec.shape[0], self.nb_df), dtype=np.complex64)
        for t in range(spec.shape[0]):
            x = spec[t, : self.nb_df]
            ustate = np.abs(x) * (1 - a) + ustate * a
            spec_feat[t] = x / np.sqrt(ustate)
        return erb_feat, spec_feat

    def enhance(self, audio: np.ndarray) -> np.ndarray:
        audio = np.asarray(audio, dtype=np.float32).reshape(-1)
        n_len, n_fft = len(audio), self.fft_size
        if n_len == 0:
            return audio.copy()
        spec = self._stft(np.concatenate([audio, np.zeros(n_fft, dtype=np.float32)]))
        erb_feat, spec_feat = self._features(spec)

        look = self.conv_lookahead
        erb_in = np.pad(erb_feat[look:], ((0, look), (0, 0)))[None, None]
        sf = np.stack([spec_feat.real, spec_feat.imag], axis=0)
        sf = np.pad(sf[:, look:], ((0, 0), (0, look), (0, 0)))[None]
        e0, e1, e2, e3, emb, c0, _lsnr = self._sessions["enc"].run(
            None, {"feat_erb": erb_in.astype(np.float32), "feat_spec": sf.astype(np.float32)}
        )
        (mask,) = self._sessions["erb_dec"].run(None, {"emb": emb, "e3": e3, "e2": e2, "e1": e1, "e0": e0})
        (coefs,) = self._sessions["df_dec"].run(["coefs"], {"emb": emb, "c0": c0})  # la 2.ª salida (alfa) no se usa

        spec_m = spec * (mask[0, 0] @ self.erb_inv)
        order, nb_df = self.df_order, self.nb_df
        c = coefs[0].reshape(spec.shape[0], nb_df, order, 2)
        c = c[..., 0] + 1j * c[..., 1]
        xp = np.pad(spec[:, :nb_df], ((order - 1 - self.df_lookahead, self.df_lookahead), (0, 0)))
        out = np.zeros((spec.shape[0], nb_df), dtype=np.complex64)
        for k in range(order):
            out += xp[k : k + spec.shape[0]] * c[:, :, k]
        spec_m[:, :nb_df] = out
        delay = n_fft - self.hop
        return self._istft(spec_m)[delay : n_len + delay].astype(np.float32)
