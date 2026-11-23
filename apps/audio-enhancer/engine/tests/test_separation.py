"""Segundo modelo (Kim Vocal 2, MDX-Net) y etapas encadenadas, con el modelo real y voz de dominio público.

Se descarga una vez del origen (66 MB, sha256 verificado); sin red y sin caché, se omite.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from helpers import have_ffmpeg

from audio_enhancer_engine import models, stages
from audio_enhancer_engine.pipeline import render
from audio_enhancer_engine.settings import Settings, Stage

CLIP = Path(__file__).parent / "data" / "speech_pd_8s.wav"
ffmpeg_needed = pytest.mark.skipif(not have_ffmpeg(), reason="ffmpeg no disponible")


@pytest.fixture(scope="module")
def kim():
    try:
        models.install("kim-vocal-2")
    except (OSError, models.ModelError) as exc:
        pytest.skip(f"modelo no disponible: {exc}")
    with models.use_models(["kim-vocal-2"]):
        yield stages.load_model("kim-vocal-2")


@pytest.fixture(scope="module")
def clip():
    audio, sr = sf.read(CLIP, dtype="float32")
    assert sr == 48_000 and audio.ndim == 1
    return audio


def music_like(n: int) -> np.ndarray:
    t = np.arange(n) / 48_000
    tones = (0.05 * np.sin(2 * np.pi * f * t) * (0.5 + 0.5 * np.sin(2 * np.pi * 0.7 * t + f)) for f in (220, 277, 330, 440, 554, 880))
    return sum(tones).astype(np.float32)


@pytest.mark.parametrize("n", [1, 100, 48_000 * 3 + 17])
def test_contract_exact_length_finite_and_deterministic(kim, n):
    x = (0.05 * np.random.default_rng(n).standard_normal(n)).astype(np.float32)
    a, b = kim.enhance(x), kim.enhance(x)
    assert a.shape == x.shape and a.dtype == np.float32 and np.isfinite(a).all()
    assert np.array_equal(a, b)


def test_removes_background_music_and_keeps_the_voice(kim, clip):
    music = music_like(len(clip))
    out = kim.enhance(clip + music)
    coef, *_ = np.linalg.lstsq(np.stack([clip, music], 1).astype(np.float64), out.astype(np.float64), rcond=None)
    speech_gain, music_gain = coef
    assert 0.7 < speech_gain < 1.1  # la voz se conserva (>= -3 dB)
    assert abs(music_gain) < 10 ** (-25 / 20)  # la música baja >= 25 dB (medido ~45 dB)


def test_output_is_time_aligned_with_the_input(kim, clip):
    out = kim.enhance(clip + music_like(len(clip)))
    seg = slice(0, 20_000)
    xc = np.correlate(out[seg], clip[seg], "full")
    assert abs(int(np.argmax(xc)) - (20_000 - 1)) <= 2  # retardo cero (+-2 muestras)


@ffmpeg_needed
@pytest.mark.parametrize(
    ("separate", "denoise"),
    [(None, False), ("kim-vocal-2", False), (None, True), ("kim-vocal-2", True)],
    ids=["ninguna", "solo-separar", "solo-ruido", "ambas"],
)
def test_stage_combinations_through_the_pipeline(kim, clip, tmp_path, separate, denoise):
    if denoise:
        try:
            models.install("deepfilternet3")
        except (OSError, models.ModelError) as exc:
            pytest.skip(f"modelo no disponible: {exc}")
    src = tmp_path / "in.wav"
    sf.write(src, clip + music_like(len(clip)), 48_000, subtype="FLOAT")
    s = Settings(highpass_hz=None, normalize=False, denoise=denoise, separate_model=separate)
    with models.use_models(stages.needed_models(s)):
        chain = stages.build_chain(s)
        assert (chain is None) == (separate is None and not denoise)
        render(src, tmp_path / "out.wav", s, chain, work_root=tmp_path / "w")
    out, _ = sf.read(tmp_path / "out.wav", dtype="float32")
    assert len(out) == len(clip) and np.isfinite(out).all()


@ffmpeg_needed
def test_separation_through_the_pipeline_attenuates_music(kim, clip, tmp_path):
    music = music_like(len(clip))
    src = tmp_path / "in.wav"
    sf.write(src, clip + music, 48_000, subtype="FLOAT")
    s = Settings(highpass_hz=None, normalize=False, denoise=False, separate_model="kim-vocal-2")
    with models.use_models(["kim-vocal-2"]):
        render(src, tmp_path / "out.wav", s, stages.build_chain(s), work_root=tmp_path / "w")
    out, _ = sf.read(tmp_path / "out.wav", dtype="float32")
    coef, *_ = np.linalg.lstsq(np.stack([clip, music], 1).astype(np.float64), out.astype(np.float64), rcond=None)
    assert abs(coef[1]) < 10 ** (-20 / 20) and coef[0] > 0.6


def test_cache_hash_depends_on_model_fingerprint_and_stage_canonical_form():
    s = Settings(separate_model="kim-vocal-2")
    assert s.processing_hash({"kim-vocal-2": "a"}) != s.processing_hash({"kim-vocal-2": "b"})  # pesos distintos
    off = Settings(separate_model=None, separate_strength=0.3)
    assert off.processing_hash() == Settings().processing_hash()  # etapa desactivada: forma canónica
    assert Settings(denoise=False, denoise_strength=0.2).processing_hash() == Settings(denoise=False).processing_hash()


def test_v010_settings_without_stage_fields_still_load():
    old = {"highpass_hz": 80.0, "notch_hz": None, "notch_harmonics": 3, "denoise": True, "denoise_strength": 0.7,
           "normalize": True, "target_lufs": -16.0, "max_true_peak_db": -1.0, "channels": "each",
           "output_format": "wav24", "version": 1}  # fmt: skip
    s = Settings.from_dict(old)
    assert s.separate_model is None and s.denoise_strength == 0.7


@pytest.mark.parametrize("bad", [{"separate_model": 5}, {"separate_model": "../x"}, {"separate_strength": 2}, {"separate_strength": "a"}])
def test_invalid_stage_settings_are_rejected(bad):
    with pytest.raises((ValueError, TypeError)):
        Settings.from_dict(bad)


@ffmpeg_needed
def test_keep_residual_keeps_the_background_instead_of_the_voice(kim, clip, tmp_path):
    music = music_like(len(clip))
    src = tmp_path / "in.wav"
    sf.write(src, clip + music, 48_000, subtype="FLOAT")
    s = Settings(chain=(Stage("s", "model", "kim-vocal-2", params={"keep": "residual"}),), normalize=False)
    with models.use_models(stages.needed_models(s)):
        render(src, tmp_path / "out.wav", s, stages.build_chain(s), work_root=tmp_path / "w")
    out, _ = sf.read(tmp_path / "out.wav", dtype="float32")
    coef, *_ = np.linalg.lstsq(np.stack([clip, music], 1).astype(np.float64), out.astype(np.float64), rcond=None)
    assert coef[1] > 0.8 and abs(coef[0]) < 0.3  # queda la música, se va la voz


@ffmpeg_needed
def test_two_models_in_either_order_run_and_differ(kim, clip, tmp_path):
    try:
        models.install("deepfilternet3")
    except (OSError, models.ModelError) as exc:
        pytest.skip(f"modelo no disponible: {exc}")
    src = tmp_path / "in.wav"
    sf.write(src, clip + music_like(len(clip)), 48_000, subtype="FLOAT")
    outs = []
    for name, order in (("a", ("kim-vocal-2", "deepfilternet3")), ("b", ("deepfilternet3", "kim-vocal-2"))):
        s = Settings(chain=tuple(Stage(f"s{i}", "model", m) for i, m in enumerate(order)), normalize=False)
        with models.use_models(stages.needed_models(s)):
            render(src, tmp_path / f"{name}.wav", s, stages.build_chain(s), work_root=tmp_path / "w")
        out, _ = sf.read(tmp_path / f"{name}.wav", dtype="float32")
        assert len(out) == len(clip) and np.isfinite(out).all()
        outs.append(out)
    assert np.abs(outs[0] - outs[1]).max() > 1e-4  # el orden de las cajas cambia el resultado
