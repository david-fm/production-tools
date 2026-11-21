import numpy as np
import pyloudnorm
import pytest
from helpers import SR, noise

from audio_enhancer_engine.loudness import LoudnessMeter


@pytest.mark.parametrize("level", [0.01, 0.05, 0.3])
@pytest.mark.parametrize("channels", [1, 2])
def test_matches_pyloudnorm(level, channels):
    audio = noise(12, channels, level, seed=3)
    meter = LoudnessMeter(channels)
    for i in range(0, len(audio), 7000):  # trozos desiguales: el streaming no debe alterar el resultado
        meter.add(audio[i : i + 7000])
    ours = meter.integrated()
    ref = pyloudnorm.Meter(SR).integrated_loudness(audio.astype(np.float64))
    assert ours == pytest.approx(ref, abs=0.1)


def test_silence_returns_none():
    meter = LoudnessMeter(1)
    meter.add(np.zeros((SR * 2, 1), dtype=np.float32))
    assert meter.integrated() is None


def test_too_short_returns_none():
    meter = LoudnessMeter(1)
    meter.add(noise(0.2, 1))
    assert meter.integrated() is None
