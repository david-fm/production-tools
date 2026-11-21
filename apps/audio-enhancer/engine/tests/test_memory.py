"""La memoria no debe crecer con la duración del audio (procesado por bloques + memmap).

Por defecto se prueba con 10 y 30 min sintéticos; para la prueba de 3 h: AE_LONG_MINUTES=180 pytest -k memory.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap

import pytest
import soundfile as sf
from helpers import SR, have_ffmpeg, noise

pytestmark = pytest.mark.skipif(not have_ffmpeg(), reason="ffmpeg no disponible")

RUNNER = textwrap.dedent(
    """
    import json, resource, sys
    from audio_enhancer_engine.denoise import IdentityDenoiser
    from audio_enhancer_engine.pipeline import render
    from audio_enhancer_engine.settings import Settings
    src, dst, work = sys.argv[1:4]
    r = render(src, dst, Settings(highpass_hz=80.0), IdentityDenoiser(), work_root=__import__("pathlib").Path(work))
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    rss_mb = rss / (1024 * 1024) if sys.platform == "darwin" else rss / 1024
    print(json.dumps({"rss_mb": rss_mb, "duration_s": r.duration_s}))
    """
)


def _make_wav(path, minutes):
    with sf.SoundFile(path, "w", samplerate=SR, channels=1, subtype="FLOAT") as f:
        for i in range(int(minutes * 60 / 30)):  # trozos de 30 s: el propio generador usa poca memoria
            f.write(noise(30, 1, 0.05, seed=i))


def _run(tmp_path, minutes):
    src, dst = tmp_path / f"in{minutes}.wav", tmp_path / f"out{minutes}.wav"
    _make_wav(src, minutes)
    res = subprocess.run(
        [sys.executable, "-c", RUNNER, str(src), str(dst), str(tmp_path / f"w{minutes}")],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    for p in (src, dst):
        p.unlink()
    return json.loads(res.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(sys.platform == "win32", reason="resource no existe en Windows; se mide con psutil en CI de Windows")
def test_peak_memory_does_not_scale_with_duration(tmp_path):
    long_min = float(os.environ.get("AE_LONG_MINUTES", "30"))
    short = _run(tmp_path, 5)
    long = _run(tmp_path, long_min)
    assert long["duration_s"] == pytest.approx(long_min * 60, abs=1)
    assert long["rss_mb"] < 700, long  # tope absoluto
    assert long["rss_mb"] - short["rss_mb"] < 150, (short, long)  # y sin crecimiento con la duración
