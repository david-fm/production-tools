"""Tests del pipeline con un modelo nulo (identidad): validan bloques, crossfade, volumen y reanudación."""

from __future__ import annotations

import numpy as np
import pytest
import soundfile as sf
from helpers import SR, have_ffmpeg, noise, run_ffmpeg, speechlike, write_wav

from audio_enhancer_engine.denoise import IdentityDenoiser
from audio_enhancer_engine.pipeline import B, Cancelled, render
from audio_enhancer_engine.settings import Settings

pytestmark = pytest.mark.skipif(not have_ffmpeg(), reason="ffmpeg/ffprobe no disponibles")

RAW = Settings(highpass_hz=None, denoise=True, normalize=False)  # copia fiel: los bloques deben ser transparentes
DUR = B / SR * 2.4  # 2.4 bloques: dos costuras de crossfade


def read(path):
    data, sr = sf.read(path, dtype="float32", always_2d=True)
    assert sr == SR
    return data


def test_seams_are_transparent(tmp_path):
    """Con modelo identidad y sin filtros, la salida debe ser idéntica a la entrada, también en las costuras."""
    audio = noise(DUR, 2, 0.1)
    src = write_wav(tmp_path / "in.wav", audio)
    render(src, tmp_path / "out.wav", RAW, IdentityDenoiser(), work_root=tmp_path / "w")
    out = read(tmp_path / "out.wav")
    assert out.shape == audio.shape
    # PCM de 24 bits: el error máximo es de cuantización (2^-23), no del crossfade.
    assert np.abs(out - audio).max() < 2e-7


def test_filtered_blocks_match_single_pass_filter(tmp_path):
    """El filtrado por bloques con calentamiento debe coincidir con filtrar todo de una vez (error < -80 dB)."""
    from audio_enhancer_engine.dsp import apply_filter, build_filter

    settings = Settings(highpass_hz=120.0, notch_hz=50.0, denoise=False, normalize=False)
    audio = noise(DUR, 1, 0.1, seed=5)
    src = write_wav(tmp_path / "in.wav", audio)
    render(src, tmp_path / "out.wav", settings, None, work_root=tmp_path / "w")
    expected = apply_filter(build_filter(settings), audio)
    err = read(tmp_path / "out.wav") - expected
    assert np.sqrt((err**2).mean()) / np.sqrt((expected**2).mean()) < 1e-4


def test_loudness_target_within_half_lu(tmp_path):
    src = write_wav(tmp_path / "in.wav", speechlike(40, 1))
    settings = Settings(highpass_hz=None, denoise=False, normalize=True, target_lufs=-16.0)
    result = render(src, tmp_path / "out.wav", settings, None, work_root=tmp_path / "w")
    assert result.output_lufs == pytest.approx(-16.0, abs=0.5)
    assert not result.peak_limited


def test_peak_limit_prevents_clipping_and_warns(tmp_path):
    audio = speechlike(20, 1)
    audio[1000] = 0.9  # pico aislado: subir el volumen al objetivo saturaría
    src = write_wav(tmp_path / "in.wav", audio)
    settings = Settings(highpass_hz=None, denoise=False, normalize=True, target_lufs=-10.0, max_true_peak_db=-1.0)
    result = render(src, tmp_path / "out.wav", settings, None, work_root=tmp_path / "w")
    assert result.peak_limited and result.warnings
    assert np.abs(read(tmp_path / "out.wav")).max() <= 10 ** (-1.0 / 20) + 1e-4


def test_preview_equals_full_job_slice(tmp_path):
    """Vista previa y trabajo completo usan los mismos bloques: la región debe coincidir con el trozo del completo."""
    audio = noise(DUR, 1, 0.1, seed=9)
    src = write_wav(tmp_path / "in.wav", audio)
    settings = Settings(highpass_hz=100.0, denoise=True, normalize=False)
    t0, t1 = B / SR - 5, B / SR + 5  # región que cruza la primera costura
    render(src, tmp_path / "prev.wav", settings, IdentityDenoiser(), region=(t0, t1), work_root=tmp_path / "w1")
    render(src, tmp_path / "full.wav", settings, IdentityDenoiser(), work_root=tmp_path / "w2")
    prev, full = read(tmp_path / "prev.wav"), read(tmp_path / "full.wav")
    assert len(prev) == int((t1 - t0) * SR)
    assert np.abs(prev - full[int(t0 * SR) : int(t1 * SR)]).max() < 2e-7


def test_cancel_then_resume_gives_identical_output(tmp_path):
    audio = noise(DUR, 1, 0.1, seed=11)
    src = write_wav(tmp_path / "in.wav", audio)
    settings = Settings(highpass_hz=100.0, denoise=True, normalize=False)
    work = tmp_path / "w"

    calls = {"n": 0}

    class Dying(IdentityDenoiser):
        def enhance(self, a):
            calls["n"] += 1
            return super().enhance(a)

    def cancel_after_one_block() -> bool:
        return calls["n"] >= 1

    with pytest.raises(Cancelled):
        render(src, tmp_path / "x.wav", settings, Dying(), work_root=work, cancelled=cancel_after_one_block)
    resumed = render(src, tmp_path / "resumed.wav", settings, IdentityDenoiser(), work_root=work)
    assert resumed.resumed_blocks >= 1
    clean = render(src, tmp_path / "clean.wav", settings, IdentityDenoiser(), work_root=tmp_path / "w2")
    assert clean.resumed_blocks == 0
    assert np.array_equal(read(tmp_path / "resumed.wav"), read(tmp_path / "clean.wav"))


def test_changed_settings_do_not_reuse_cache(tmp_path):
    src = write_wav(tmp_path / "in.wav", noise(10, 1))
    work = tmp_path / "w"
    render(src, tmp_path / "a.wav", Settings(highpass_hz=80.0, normalize=False), IdentityDenoiser(), work_root=work)
    again = render(src, tmp_path / "b.wav", Settings(highpass_hz=200.0, normalize=False), IdentityDenoiser(), work_root=work)
    assert again.resumed_blocks == 0


def test_modified_source_invalidates_cache(tmp_path):
    src = tmp_path / "in.wav"
    write_wav(src, noise(10, 1, seed=1))
    work = tmp_path / "w"
    s = Settings(highpass_hz=None, normalize=False)
    render(src, tmp_path / "a.wav", s, IdentityDenoiser(), work_root=work)
    write_wav(src, noise(10, 1, seed=2))  # mismo nombre, otro contenido
    render(src, tmp_path / "b.wav", s, IdentityDenoiser(), work_root=work)
    assert np.abs(read(tmp_path / "b.wav") - noise(10, 1, seed=2)).max() < 2e-7


def test_input_without_audio_is_rejected(tmp_path):
    from audio_enhancer_engine.ffmpeg_io import FfmpegError

    video = tmp_path / "v.mp4"
    run_ffmpeg("-f", "lavfi", "-i", "testsrc=d=1:s=64x64:r=10", "-c:v", "mpeg4", str(video))
    with pytest.raises(FfmpegError, match="pista de audio"):
        render(video, tmp_path / "o.wav", Settings(), None, work_root=tmp_path / "w")


def test_corrupt_file_gives_readable_error(tmp_path):
    from audio_enhancer_engine.ffmpeg_io import FfmpegError

    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"RIFFxxxxWAVEnope")
    with pytest.raises(FfmpegError):
        render(bad, tmp_path / "o.wav", Settings(), None, work_root=tmp_path / "w")


def test_unicode_spaces_and_long_paths(tmp_path):
    folder = tmp_path / "ñandú café" / ("subcarpeta con espacios " * 6)
    folder.mkdir(parents=True)
    src = write_wav(folder / "grabación única.wav", noise(5, 1))
    out = folder / "salida mejorada.wav"
    render(src, out, Settings(highpass_hz=None, normalize=False), IdentityDenoiser(), work_root=tmp_path / "w")
    assert out.exists()


def test_multichannel_and_mix(tmp_path):
    src = write_wav(tmp_path / "in.wav", noise(5, 4))
    render(src, tmp_path / "each.wav", Settings(highpass_hz=None, normalize=False), IdentityDenoiser(), work_root=tmp_path / "w")
    assert read(tmp_path / "each.wav").shape[1] == 4
    render(src, tmp_path / "mix.wav", Settings(highpass_hz=None, normalize=False, channels="mix"), IdentityDenoiser(), work_root=tmp_path / "w")
    assert read(tmp_path / "mix.wav").shape[1] == 1


@pytest.mark.parametrize("codec_args,ext", [(["-c:a", "flac"], "flac"), (["-c:a", "libmp3lame"], "mp3"), (["-c:a", "aac"], "m4a")])
def test_various_input_formats(tmp_path, codec_args, ext):
    wav = write_wav(tmp_path / "ref.wav", speechlike(6, 2))
    src = tmp_path / f"in.{ext}"
    run_ffmpeg("-i", str(wav), *codec_args, str(src))
    result = render(src, tmp_path / "out.wav", Settings(highpass_hz=None, denoise=False), None, work_root=tmp_path / "w")
    assert result.duration_s == pytest.approx(6.0, abs=0.1)


def test_multiple_audio_tracks_select_index(tmp_path):
    a = write_wav(tmp_path / "a.wav", np.full((SR * 2, 1), 0.1, dtype=np.float32))
    b = write_wav(tmp_path / "b.wav", np.full((SR * 2, 1), 0.3, dtype=np.float32))
    multi = tmp_path / "multi.mkv"
    run_ffmpeg("-i", str(a), "-i", str(b), "-map", "0:a", "-map", "1:a", "-c:a", "pcm_s16le", str(multi))
    s = Settings(highpass_hz=None, denoise=False, normalize=False)
    render(multi, tmp_path / "t1.wav", s, None, work_root=tmp_path / "w", audio_index=1)
    assert read(tmp_path / "t1.wav").mean() == pytest.approx(0.3, abs=1e-3)


def test_remux_keeps_video_stream_untouched(tmp_path):
    import subprocess

    from audio_enhancer_engine import ffmpeg_io

    video = tmp_path / "v.mov"
    run_ffmpeg("-f", "lavfi", "-i", "testsrc=d=2:s=64x64:r=10", "-f", "lavfi", "-i", "sine=d=2", "-c:v", "mpeg4", "-c:a", "pcm_s16le", str(video))
    render(video, tmp_path / "a.wav", Settings(highpass_hz=None, denoise=False), None, work_root=tmp_path / "w")
    out = tmp_path / "out.mov"
    ffmpeg_io.remux(video, tmp_path / "a.wav", out)

    def video_md5(p):
        r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(p), "-map", "0:v", "-c", "copy", "-f", "md5", "-"], capture_output=True, text=True, check=True)
        return r.stdout.strip()

    assert video_md5(video) == video_md5(out)


def test_output_cannot_overwrite_input(tmp_path):
    src = write_wav(tmp_path / "in.wav", noise(3, 1))
    with pytest.raises(ValueError, match="mismo"):
        render(src, src, Settings(), None, work_root=tmp_path / "w")


def test_region_out_of_range_rejected(tmp_path):
    src = write_wav(tmp_path / "in.wav", noise(3, 1))
    with pytest.raises(ValueError, match="fuera"):
        render(src, tmp_path / "o.wav", Settings(), None, region=(1.0, 99.0), work_root=tmp_path / "w")
