# Avisos de terceros

Audio Enhancer incorpora o descarga los siguientes componentes de terceros.

## ffmpeg / ffprobe (LGPL v2.1 o posterior)

Se distribuyen como **ejecutables independientes** (la app los invoca como procesos; no se enlazan con ella),
compilados **sin** `--enable-gpl` ni `--enable-nonfree`.

- macOS: compilado desde el código fuente oficial, <https://ffmpeg.org/releases/ffmpeg-8.1.2.tar.xz>, con la
  configuración de `scripts/prepare_ffmpeg.py` (incluida en este repositorio).
- Windows: build LGPL de <https://github.com/BtbN/FFmpeg-Builds> (release `autobuild-2026-11-20-12-40`,
  `ffmpeg-n8.1.3-39-g660b5aa7db-win64-lgpl-8.1.zip`); el código fuente corresponde al tag `n8.1.3` de
  <https://git.ffmpeg.org/ffmpeg.git>.

Tienes derecho a obtener el código fuente de ffmpeg y a sustituir estos ejecutables por otra build LGPL
(la app los busca junto a su ejecutable o en la variable `AUDIO_ENHANCER_FFMPEG_DIR`).
Licencia completa: <https://www.gnu.org/licenses/old-licenses/lgpl-2.1.html>.

## DeepFilterNet3 (MIT o Apache-2.0, a elección)

Modelo y algoritmo de Hendrik Schröter y colaboradores, <https://github.com/Rikorose/DeepFilterNet>.
Los pesos ONNX se descargan en el primer uso desde ese repositorio y se verifican con SHA-256.
El pre/post-procesado en `engine/src/audio_enhancer_engine/denoise.py` es una adaptación en numpy basada en
el proyecto original y en la exportación sin PyTorch de <https://huggingface.co/SayedShaun/DeepFilterNet3-onnx>
(MIT o Apache-2.0).

Copyright (c) 2021 Hendrik Schröter. Licencias: <https://github.com/Rikorose/DeepFilterNet#license>.

## Bibliotecas de Python y JavaScript

ONNX Runtime (MIT), NumPy (BSD-3), SciPy (BSD-3), python-soundfile / libsndfile (BSD-3 / LGPL-2.1),
PyInstaller (GPL-2.0 con excepción para el programa congelado), React (MIT), Tauri (MIT o Apache-2.0).
