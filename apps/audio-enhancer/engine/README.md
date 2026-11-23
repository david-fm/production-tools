# Motor de audio: contrato por stdio

La app (shell Rust) ejecuta el motor como proceso hijo y se comunica por **stdio con JSON por línea**.
Se eligió stdio en lugar de HTTP local para no abrir puertos: no hay conflictos de puerto, tokens, CORS ni avisos del firewall de Windows.

## Reglas

- **stdin:** una petición por línea: `{"id": <número>, "cmd": "<comando>", ...parámetros}`.
- **stdout:** solo mensajes JSON, uno por línea. Nunca se imprime nada más (los logs van a **stderr**).
  - Respuesta: `{"id": N, "ok": true, "result": ...}` o `{"id": N, "ok": false, "error": "texto"}`.
  - Evento de progreso: `{"event": "progress", "id": N, "value": 0.0..1.0}`.
- Entrada inválida (JSON roto, comando desconocido) responde `ok: false` y **no** detiene el motor.

## Comandos

Todos aceptan `id`. Los trabajos largos aceptan además `job` (texto): clave para `cancel` y para correlacionar
los eventos de progreso (`{"event":"progress","id":N,"job":"...","value":0..1,"stage":"..."}`). Dos tareas con la
misma clave no pueden ejecutarse a la vez. El hilo lector nunca ejecuta trabajo lento: `ping`, `cancel` y
`shutdown` responden siempre.

| cmd | Parámetros | Resultado |
|---|---|---|
| `ping` / `health` | - | `"pong"` / `{version}` |
| `providers` | - | proveedores de ONNX Runtime presentes en el binario |
| `preferred_providers` | - | orden que usará el motor (DirectML en Windows si existe; CPU siempre al final) |
| `probe` | `path` | duración, si tiene video, pistas de audio |
| `waveform` | `path`, `points`, `audio_index`, `channels` | picos mín/máx para dibujar (decodifica y cachea el origen) |
| `extract` | `input`, `output`, `region`, ... | escribe la región original (WAV) y su `lufs` |
| `enhance` | `input`, `output`, `settings`, `region?`, `audio_index?`, `remux?` | trabajo completo, o vista previa si hay `region` ([inicio_s, fin_s]). Con `remux` la salida es un video `.mov/.mkv/.mp4` con el audio mejorado y el video sin recomprimir |
| `models_status` | - | compatibilidad v0.1.0: `{deepfilternet3: {installed, path}}` |
| `models_catalog` | - | catálogo + modelos de HF instalados: id, tarea, licencia, `verified_license`, tamaño, `status` (`installed`/`missing`/`outdated`), `in_use` |
| `install_model` | `model` (id; por defecto `deepfilternet3`), `job?` | instalación atómica con sha256, progreso y cancelación; las peticiones del mismo id se serializan |
| `install_hf` | `repo` (`usuario/nombre`), `file?`, `job?` | descarga un `.onnx` de Hugging Face fijando la revisión (commit); solo HTTPS a hosts de HF; no verificado |
| `remove_model` | `model` | borra un modelo; se rechaza si un trabajo lo está usando |
| `cache_info` / `clear_cache` | - | bytes de archivos temporales / libera todo |
| `cancel` | `target?` (clave `job` o `id`) | cancela esa tarea, o todas si se omite |
| `progress_demo` | `steps`, `delay` | tarea de prueba |
| `shutdown` | - | cierre ordenado |

## Modelos y etapas (models.py, stages.py, mdx.py)

- **Ningún modelo viaja en el instalador**: se descargan del origen al equipo del usuario (`models_dir`), con tope de
  bytes en streaming, comprobación de espacio libre y sha256 (catálogo). El marcador `.ok` guarda la huella; el de
  v0.1.0 (sha256 del paquete) sigue siendo válido.
- **Etapas en orden fijo**: `separate_model` (opcional, p. ej. `kim-vocal-2`) → reducción de ruido (opcional). Cada etapa
  mezcla con su entrada según su intensidad. El `processing_hash` incluye la huella de cada modelo y la versión del
  pipeline (2): cambiar pesos o versión invalida la caché de bloques; una etapa desactivada no entra en el hash.
- **Modelos de Hugging Face** (no verificados): solo `.onnx`; se rechazan los que traen `external_data` o dominios de
  operadores personalizados (en la instalación y otra vez al cargarlos). Se ejecutan los de tipo MDX-Net (entrada
  `[N,4,F,T]`); el resto queda "descargado, no compatible". El aviso de licencia/origen es visible pero no bloquea.
- **Limitación conocida**: el modelo de reverberación de UVR (Reverb_HQ_By_FoxJoy) solo detecta la cola comparando los
  canales L/R; con audio mono (el pipeline procesa cada canal por separado) su salida es ~0, así que no se incluye.

## Cómo procesa (pipeline.py)

- El origen se decodifica **una vez** con ffmpeg a float32 de 48 kHz y se guarda en la caché de trabajo
  (`AUDIO_ENHANCER_WORK_DIR`, por defecto la carpeta temporal del sistema). Se lee por trozos: la memoria no depende de la duración.
- El audio se divide en bloques de 30 s sobre una **rejilla global**; cada bloque se calcula con 3 s de contexto a cada lado
  y se une al siguiente con un crossfade lineal de 100 ms. Vista previa y trabajo completo usan los mismos bloques,
  así que la región probada coincide con lo que saldrá en el archivo final y los bloques ya calculados se reutilizan.
- Cada bloque se guarda de forma atómica. Reanudar = saltarse los bloques existentes. La clave de caché incluye la huella del
  origen (tamaño, fecha, primer MiB) y el hash de los ajustes que afectan al audio, por lo que ajustes u origen distintos nunca
  reutilizan bloques ajenos.
- Volumen: medición EBU R128 integrada (BS.1770-4). En el trabajo completo se mide sobre el audio ya procesado; en la
  vista previa se usa la ganancia calculada sobre el original completo (puede diferir ~1 LU). El límite "Pico máximo" compara
  contra el **pico de muestra**, no contra el true-peak entre muestras.
- Cachés sin uso durante 7 días (`AUDIO_ENHANCER_CACHE_DAYS`) se borran solas; `clear_cache` las borra todas.
- Los archivos temporales tienen nombres únicos por trabajo y se eliminan siempre (también al cancelar o fallar);
  un archivo de salida incompleto se borra.
- Se necesitan ~3x el tamaño del audio decodificado (≈1,4 GB por hora estéreo a 48 kHz) libres en disco; si no hay, el error lo indica antes de empezar.

## Fallos y recuperación

| Situación | Comportamiento |
|---|---|
| El motor muere | La shell detecta el fin del proceso, falla las llamadas pendientes con un error legible y lo reinicia (500 ms). |
| El motor se cuelga | Heartbeat `ping` cada 5 s (límite de 5 s). Tras 2 fallos seguidos la shell mata **todo el árbol de procesos** (PyInstaller `--onefile` crea dos) y lo reinicia. En el arranque en frío hay 60 s de margen hasta el primer `pong`. |
| Una llamada tarda demasiado | Límite de 30 s por defecto; los trabajos largos piden un límite grande y reportan avance por eventos. |
| La app se cierra o muere | La shell envía `shutdown` y mata el proceso. Si la app muere sin poder hacerlo (p. ej. SIGKILL), **stdin se cierra y el motor termina solo**. |
| Trabajo interrumpido | Reanudación por bloques con hash de ajustes y huella del origen (ver arriba). |

Archivos grandes (vista previa, resultados) **no** viajan por stdio: se escriben a disco y la interfaz los lee por el protocolo de assets de Tauri.

## Desarrollo

```bash
uv sync
uv run pytest                          # tests del motor + binario congelado si existe (requiere ffmpeg)
uv run python scripts/build_sidecar.py # PyInstaller → ../src-tauri/binaries/audio-enhancer-engine-<triple>
```
