# Checklist: Audio Enhancer v0.2.0 (M3) — catálogo de modelos, segundo modelo y PyTorch opcional

**Baseline de revisión:** commit `b806f9a` (rama `main`, árbol limpio, etiqueta `v0.1.0` publicada). Todo cambio de esta tarea se compara contra ese commit.

**Estado de ejecución (2026-11-23):** Fases A y B implementadas y verificadas en macOS; Fase C (PyTorch) APLAZADA a v0.3.0 por el criterio de C1 (ver `pytorch-spike-C1.md`); D2 pendiente de CI y release. Pendiente de revisión Goldfish del diff.

**Spec Review Status:** revisión Goldfish nº 1 triada (12 FIX, 0 CONTEST) e incorporada abajo; pendiente de nueva revisión o de `exec`.

**Decisiones del usuario (vinculantes):**
- Todos los modelos en formato **catálogo**; por defecto se descarga solo DeepFilterNet3 (como ahora).
- Se puede **descargar y ejecutar** cualquier modelo de Hugging Face compatible con un adaptador. Los no verificados muestran un **aviso**, pero **no se bloquea su ejecución**.
- **Ningún modelo viaja en el instalador:** todo se descarga del origen al PC de la persona.
- Alcance: gestor + segundo modelo ONNX + PyTorch opcional (en ese orden de entrega).
- **Etapas encadenables en orden fijo:** primero separar/quitar reverberación, después reducir ruido; cada etapa opcional.
- Sin audios de prueba por ahora: la calidad del segundo modelo queda como prueba manual aplazada.

**Límites acordados para "cualquier modelo de HF":**
1. Se ejecuta lo que tenga adaptador compatible (por forma de entradas/salidas); lo demás queda "descargado, no compatible".
2. De repos fuera del catálogo solo se aceptan `.onnx` y `.safetensors`. Nunca `.pt`/`.pkl`/`.bin` (pickle ejecuta código). Los pesos del catálogo con sha256 fijado son la única excepción.
3. PyTorch vive en un runtime separado descargado a la carpeta de datos del usuario, no dentro del ejecutable congelado.
4. Un modelo no verificado se ejecuta con aviso visible y confirmación previa a instalarlo (licencia desconocida/no comercial o `verified_license=false`), pero sin bloqueo.

## Fase A — Catálogo y gestor de modelos

- [x] **A1.** Esquema del catálogo en [`models.py`](../../apps/audio-enhancer/engine/src/audio_enhancer_engine/models.py): `id`, nombre, tarea (`denoise`/`separate`/`dereverb`), licencia declarada + URL de origen, tamaño, sha256, ficheros, backend (`onnx`/`torch`), `verified_license`, `default`. DeepFilterNet3 es la primera entrada y se instala por defecto. Instalador atómico con marcador `.ok` y tope de tamaño por modelo.
- [ ] **A1b. Migración de v0.1.0.** Un DeepFilterNet3 ya instalado (carpeta `deepfilternet3` y `.ok` que guarda su sha256) se reconoce como la entrada del catálogo sin volver a descargar; se compara el sha256 del marcador con el del catálogo. Contrato `models_status` → `{deepfilternet3:{installed}}` fijado y probado (lo usa `App.test.tsx`).
- [x] **A2.** Instalación genérica desde URL de origen con verificación sha256 (catálogo). Para modelos de HF fuera del catálogo se registra el sha256 calculado, aclarando en la UI que solo detecta cambios posteriores y no aporta integridad frente al origen.
- [ ] **A3. Descarga de HF endurecida.** Validar `repo` con el formato `usuario/nombre` (rechazar `..`, esquemas, URLs completas); **fijar el commit hash** resuelto y descargar solo de esa revisión; solo HTTPS y **lista de hosts** (HF y su CDN) también tras redirecciones; ficheros permitidos `.onnx`/`.safetensors` más `config.json` y `README`; **tope de ficheros y de tamaño total por repo**; regla explícita para elegir qué `.onnx` bajar cuando hay varias variantes; **comprobar espacio libre** antes; sin token del usuario ni datos enviados. El README/metadatos se muestra como **texto plano truncado**, nunca como HTML ni Markdown.
- [ ] **A3b. Ejecución de modelos no verificados (aviso, sin bloqueo).** Antes de cargar un `.onnx` de origen no catalogado: comprobar que no referencia `external_data` fuera de su carpeta y que sus dominios de operadores no exigen librerías nativas externas (ORT no carga operadores personalizados sin registro explícito). Si no pasa esas comprobaciones, se rechaza la carga con un mensaje claro; si pasa, se ejecuta con el aviso visible. `[⚠️ UNVERIFIED]`
- [x] **A4.** Comandos del motor en [`server.py`](../../apps/audio-enhancer/engine/src/audio_enhancer_engine/server.py): `models_catalog`, `install_model {id}`, `install_hf {repo}`, `remove_model {id}`; progreso y cancelación con el patrón `Tasks`. **Concurrencia:** un bloqueo por id; una segunda petición del mismo id se deduplica (espera y devuelve el mismo resultado); `remove_model` se rechaza si hay un trabajo usando ese modelo; `install_model` durante un procesamiento solo está permitido si no afecta al modelo en uso. **Cancelar borra los `.part`.** Validación estricta de parámetros (sin matar el lector).
- [x] **A5.** Interfaz: pantalla "Modelos" (lista con tarea, licencia, tamaño, estado; instalar/quitar; campo para repo de HF). Confirmación antes de instalar modelos con licencia desconocida o no comercial, y aviso permanente en los no verificados. Textos en [`i18n/es.ts`](../../apps/audio-enhancer/src/i18n/es.ts). La detección de modelo ausente de [`App.tsx`](../../apps/audio-enhancer/src/App.tsx) sigue ofreciendo DeepFilterNet3 por defecto.
- [x] **A6.** Tests: sha256 incorrecto, tamaño excesivo, extensión prohibida, traversal, nombre de repo inválido, redirección a host no permitido, instalación interrumpida, espacio insuficiente, descarga concurrente del mismo id, `remove_model` en uso, cancelación que limpia `.part`, migración v0.1.0, README renderizado como texto, y vitest de la pantalla. Servidor HTTP local en tests, sin red real.

## Fase B — Segundo modelo ONNX y etapas encadenables

- [x] **B1.** Elegir el modelo en el origen: verificar la licencia de los pesos en el repo original (no en espejos). Si no se puede verificar, entra al catálogo con `verified_license=false`. `[⚠️ UNVERIFIED]`
- [x] **B2.** Adaptador junto a [`denoise.py`](../../apps/audio-enhancer/engine/src/audio_enhancer_engine/denoise.py) que cumpla el contrato `Denoiser` (mono f32 48 kHz in → out, misma longitud). **Remuestreo** a la frecuencia del modelo (16/44,1 kHz) dentro del adaptador y vuelta a 48 kHz, con **compensación del retardo** de STFT para alinear la salida. Proveedor DirectML con la selección "el más rápido entre aceleración y CPU".
- [x] **B3.** Etapas en [`settings.py`](../../apps/audio-enhancer/engine/src/audio_enhancer_engine/settings.py): `separate/dereverb` (opcional) → `denoise` (opcional), orden fijo. Validación estricta; el **`processing_hash` incluye el id, la versión y el sha256 de cada modelo usado**, y se sube `PIPELINE_VERSION`: cambiar pesos bajo el mismo id nunca mezcla la caché. Controles y explicaciones en [`SettingsPanel.tsx`](../../apps/audio-enhancer/src/components/SettingsPanel.tsx).
- [x] **B4.** Contexto de bloque: comprobar que los 3 s de contexto (`CONTEXT_S`) bastan para la ventana del modelo; si no, ajustarlo por modelo sin romper el crossfade global.
- [x] **B5.** Tests: contrato (longitud exacta, determinismo, sin NaN); **alineación temporal** por correlación cruzada con retardo cero; pipeline con el modelo real en CI con caché indexada por **sha256 del modelo** y verificación del hash; medida objetiva con señal definida (voz grabada real corta del repo de pruebas + música/eco sintéticos añadidos, no voz sintética pura) con **umbral numérico** de atenuación del componente no deseado en dB y tolerancia de preservación de la voz, fijados al elegir el modelo. Benchmark en macOS; DirectML en la 1650 Ti.

## Fase C — PyTorch opcional (condicionada por el spike)

- [ ] **C1.** Spike antes de construir: nota en `docs/` con qué modelo útil NO existe en ONNX y qué ganancia concreta aporta. Si no hay ninguno, C2–C5 se aplazan a v0.3.0 con acuerdo del usuario y **0.2.0 se publica sin ellos**.
- [ ] **C2.** Runtime separado en la carpeta de datos del usuario (Python embebido + `torch` según haya CUDA; DirectML no aplica). **Lockfile con hashes y `--require-hashes`** para torch y sus dependencias transitivas; comprobación de espacio libre (wheels CUDA de varios GB); instalación en directorio temporal + rename (atómica y reversible); nada de `pip` sobre el ejecutable congelado.
- [ ] **C3.** Subproceso del runtime con el mismo protocolo JSON por stdio y **versión de protocolo fijada entre sidecars**; supervisión, cancelación y limpieza de procesos hijos reutilizando `kill_process_tree` ([`lib.rs`](../../apps/audio-enhancer/src-tauri/src/lib.rs)).
- [ ] **C4.** Backend `torch` en el catálogo, solo para entradas con sha256 fijado; los `.pt` exigen `torch.load(weights_only=True)` o formato safetensors. Interfaz: opción "Instalar PyTorch" con tamaño y aviso.
- [ ] **C5.** Tests de gestión del runtime (instalación interrumpida, sin disco, sin red) con un runtime falso; prueba manual real en Windows + 1650 Ti.

## Ronda 2 de revisión (Goldfish nº 2) — 12 FIX aceptados, 0 CONTEST

Decisiones del usuario: audio de prueba descargado de internet (dominio público/CC0, licencia anotada); `.safetensors` fuera de la lista de descargables hasta la Fase C; "hazlo todo de una" (el usuario acepta que algo falle en esta versión: es de uso propio).

- [x] **R2-1.** B5: señal sintética para tests estructurales; clip corto CC0/PD de voz para medir atenuación; licencia en `THIRD_PARTY_NOTICES.md`.
- [x] **R2-2.** A3b: `external_data` se rechaza por completo en modelos no catalogados (y se dice). Tests: con `external_data`, con dominio de operadores personalizado, y uno válido.
- [x] **R2-3.** Límite 2 pasa a: de repos fuera del catálogo solo `.onnx` (+ `config.json`/README).
- [x] **R2-4.** Etapa `separate`: cada entrada del catálogo declara el stem que conserva; encadenado por bloque; contexto de cada etapa sumado a `CONTEXT_S`; cada adaptador compensa su retardo; test de alineación por etapa.
- [x] **R2-5.** A4: los trabajos reservan sus modelos (contador de uso); install/remove del mismo id se rechazan con mensaje claro mientras estén en uso; se rechazan modelos sin `.ok`; `install_hf` usa `owner--repo` + revisión normalizados como clave y carpeta.
- [x] **R2-6.** `PIPELINE_VERSION` sube: la caché de v0.1.0 se invalida (se purga por caducidad); ajustes antiguos sin etapas se rellenan con los valores actuales; forma canónica de etapa desactivada en el hash; test de preajustes v0.1.0.
- [x] **R2-7.** CI: B5 descarga el modelo con sha256 fijado; si falla la descarga, falla el job; A6 sin red real.
- [x] **R2-8.** A1b: sha256 distinto → "versión distinta", se ofrece reinstalar; quitar el único modelo → aviso habitual.
- [x] **R2-9.** Tope de tamaño por streaming; tests sin `Content-Length` y con fichero que cambia a mitad.
- [x] **R2-10.** C1: PyTorch solo si cubre una tarea sin alternativa ONNX o mejora una métrica objetiva fijada en la nota del spike; si no, v0.3.0.
- [x] **R2-11.** Tests de aviso permanente, confirmación previa y combinaciones de etapas (una, ninguna, orden).

## Cierre

- [x] **D1.** Documentación: README de la app, `THIRD_PARTY_NOTICES.md` (cada modelo con licencia y origen, "se descarga, no se redistribuye"), contrato del protocolo del motor, [`docs/verification/`](../verification/M0.md). Indica qué fases entran en la versión publicada.
- [ ] **D2.** CI verde en Windows y macOS ([`ci.yml`](../../.github/workflows/ci.yml)), instaladores generados, versión `0.2.0` (con o sin Fase C según C1), etiqueta y release como pre-release.

## Pruebas empíricas aplazadas `[⏳ ACK]`

- Calidad percibida del segundo modelo con audio real (no hay audios todavía): A/B a ciegas.
- DirectML con el segundo modelo en la GTX 1650 Ti (velocidad y VRAM) con `scripts/benchmark.py`.
- Instalación y ejecución del runtime PyTorch con CUDA en Windows real.
- Descarga real desde Hugging Face con la red de su pareja (proxies/firewall).

## Riesgos sin verificar `[⚠️ UNVERIFIED]`

- Licencia de los pesos del modelo de separación/dereverb en su repo de origen (los espejos dicen MIT).
- Que DirectML ejecute todos los operadores del modelo elegido.
- Que el modelo de separación funcione bien sobre diálogo y no solo sobre música.
- Formato y límites de la API pública de Hugging Face (listado de ficheros, revisiones, redirecciones a CDN).
- Que ONNX Runtime rechace por sí mismo `external_data` fuera de la carpeta del modelo en la versión fijada (1.22.0); si no, la comprobación de A3b es la única barrera.
- Viabilidad y tamaño de un runtime PyTorch autocontenido instalable en el PC del usuario.

## Exclusiones acordadas

- Ningún modelo se incluye en el instalador.
- No se ejecuta código de pesos en formato pickle de repos fuera del catálogo.
- Sin procesamiento en la nube ni cuentas de Hugging Face del usuario.
- Sin soporte de CUDA/PyTorch en macOS en esta versión.
- Sin firmar instaladores (como en v0.1.0).
- Decisión del usuario: modelos no verificados se ejecutan con aviso, sin bloqueo (A3b mantiene solo las comprobaciones técnicas de seguridad de carga).

---

### 🔍 Assumption Lifecycle Legend:

- `[⚠️ UNVERIFIED]`: Siloed external contract. Requires indisputable evidence to verify.
- `[⏳ ACK]`: Acknowledged assumption. Factual evidence unavailable; risk accepted and opaque-box empirical test strictly scheduled.
