"""Pruebas con el modelo real (requieren descargarlo una vez: ~8 MB, sha256 verificado)."""

from __future__ import annotations

import numpy as np
import pytest
from helpers import SR

from audio_enhancer_engine.denoise import DeepFilterNet3
from audio_enhancer_engine.models import ensure_deepfilternet3


@pytest.fixture(scope="module")
def model():
    try:
        folder = ensure_deepfilternet3()
    except OSError as exc:  # sin red y sin caché: se omite, no se falla
        pytest.skip(f"modelo no disponible: {exc}")
    return DeepFilterNet3(folder)


def test_reduces_stationary_noise_and_keeps_length(model):
    rng = np.random.default_rng(0)
    t = np.arange(SR * 8) / SR
    tone = 0.2 * np.sin(2 * np.pi * 220 * t) * (np.sin(2 * np.pi * 1.0 * t) > 0)  # 0.5 s sí / 0.5 s no
    noisy = (tone + 0.05 * rng.standard_normal(len(t))).astype(np.float32)
    out = model.enhance(noisy)
    assert out.shape == noisy.shape and np.isfinite(out).all()
    quiet = slice(int(3.6 * SR), int(3.9 * SR))  # tramo sin tono
    rms = lambda a: float(np.sqrt((a**2).mean()))
    assert rms(out[quiet]) < 0.5 * rms(noisy[quiet])  # al menos 6 dB menos de ruido


def test_is_deterministic_on_same_provider(model):
    rng = np.random.default_rng(1)
    x = (0.05 * rng.standard_normal(SR * 3)).astype(np.float32)
    assert np.array_equal(model.enhance(x), model.enhance(x))


def test_empty_and_very_short_input(model):
    assert len(model.enhance(np.zeros(0, dtype=np.float32))) == 0
    out = model.enhance(np.zeros(100, dtype=np.float32))
    assert len(out) == 100 and np.isfinite(out).all()
