# Benchmarks del motor

Criterios de aprobación (M1): **VRAM máxima < 4096 MB** y **factor de tiempo real >= 1.0** en el proveedor
elegido. Si la aceleración (DirectML) falla o es más lenta que CPU, el motor usa CPU automáticamente
(`DeepFilterNet3._keep_fastest`). Si CPU queda por debajo de x1.0 en la máquina objetivo, se replantea el alcance.

Reproducir: `uv run python scripts/benchmark.py --minutes 2` (con audio real: `--audio ruta.wav`, 48 kHz).

## macOS (Apple M1, onnxruntime 1.22.0) - medido 2026-11-21

Audio sintético (voz sintética + ruido), bloque de producción de 36 s (30 s + contexto):

| Proveedor | Tiempo | Factor de tiempo real | 1 h de audio mono |
|---|---|---|---|
| CPU | 0,47 s | x76,5 | ~0,8 min |
| CoreML | 1,18 s | x30,5 | ~2,0 min |

Conclusión: en macOS el motor usa **CPU** (CoreML es más lento). Memoria: ver `tests/test_memory.py`
(30 min sintéticos, RSS máximo < 700 MB y sin crecimiento con la duración).

## Windows x64, GTX 1650 Ti 4 GB (DirectML) - **PENDIENTE de medir en el equipo real**

No hay Windows ni GPU NVIDIA disponibles en el entorno de desarrollo (Wine no ejecuta numpy/onnxruntime).
Ejecutar `scripts/benchmark.py` en el equipo de destino y pegar aquí la salida.

| Proveedor | Tiempo | Factor de tiempo real | VRAM máx. |
|---|---|---|---|
| CPU | _pendiente_ | _pendiente_ | - |
| DirectML | _pendiente_ | _pendiente_ | _pendiente_ |
