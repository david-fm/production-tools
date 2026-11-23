# Checklist: Audio Enhancer v0.3.0 — UX, cadena lineal de cajas y reproductor de prueba

**Baseline de revisión:** commit `6b7fb87` (rama `main`, etiqueta `v0.2.0`). Cambios sin seguimiento previos a esta tarea: `.agents/`, `.claude/`, `skills-lock.json` (los instaló `npx skills add ...ui-ux-pro-max`; contenido de terceros, ver P1) y [`egm_lite_alternatives_v0.3.0.md`](egm_lite_alternatives_v0.3.0.md) (parte de esta tarea). Todo lo demás está limpio.

**Decisiones del usuario (vinculantes):**
1. **Cadena lineal** (Entrada → cajas → Salida). Sin grafo libre.
2. **Los filtros también son cajas** (recorte de graves, zumbido). `Entrada`, `Volumen` y `Salida` fijas en los extremos.
3. **Dos pestañas, Audio y Cadena** (más «Modelos»), con la configuración de la caja seleccionada debajo de la cadena; en Audio se ve la cadena activa en solo lectura. «Iteramos desde ahí».
4. **Mover el fragmento tras probar:** la prueba se marca «desactualizada» y «Probar de nuevo» la rehace (la caché de bloques acelera).
5. Cada modelo tiene su **configuración propia con valores por defecto**; se configura por caja.
6. El reproductor de prueba debe permitir **mover la posición de reproducción** y reproducir **solo lo editado**.
7. PyTorch queda para **v0.4.0**.

**Estado de ejecución (2026-11-23):** A–D, P1 y P2 hechos y verificados en macOS (162 tests del motor, 74 de la interfaz, 3 de Rust, e2e de 24 comprobaciones, capturas revisadas). P3 (CI y release) hecho: CI verde y pre-release v0.3.0 publicado. Pendiente: revisión Goldfish del diff.

**Reglas de diseño que se aplican** (de la skill, solo las que valen para escritorio): arrastrar nunca es la única forma de reordenar (WCAG 2.5.7); controles ≥ 44 px; contraste ≥ 4,5:1; foco visible; `prefers-reduced-motion`; estado con `aria-pressed`/`aria-selected`; nada de emojis como iconos. No se adopta su patrón de *landing page*.

## Fase A — Motor: cadena de etapas con parámetros por caja

- [x] **A1. Esquema de la cadena** en [`settings.py`](../../apps/audio-enhancer/engine/src/audio_enhancer_engine/settings.py): `Settings.chain` = lista ordenada de etapas `{id, kind: "highpass" | "notch" | "model", model?: str, enabled: bool, params: {…}}`. Se mantienen los ajustes globales de salida (`channels`, `output_format`, `normalize`, `target_lufs`, `max_true_peak_db`), que pertenecen a las cajas fijas `Volumen`/`Salida`. Validación estricta (tipos, rangos, ids únicos, modelo válido, `Volumen` siempre al final por construcción).
- [x] **A2. Migración de ajustes antiguos** (v0.1.0 y v0.2.0, planos: `highpass_hz`, `notch_hz`, `denoise`, `separate_model`, …) a cadena, conservando el **orden efectivo de v0.2.0**: graves → zumbido → separar → reducir ruido. `Settings.from_dict` acepta ambos formatos; el producto de la migración con los mismos valores da el mismo audio que v0.2.0 (test de regresión bit a bit con `IdentityDenoiser` y con `highpass`/`notch`).
- [x] **A3. Esquema de parámetros por caja** declarado en el catálogo ([`models.py`](../../apps/audio-enhancer/engine/src/audio_enhancer_engine/models.py)) y para los filtros: lista de `{id, tipo (number|choice|bool), rango/opciones, defecto, etiqueta, ayuda}`. Solo parámetros que el adaptador soporta de verdad: **todos** los modelos → `intensidad` (mezcla con la entrada de su caja); **MDX** → `conservar` (`voz` | `resto`, ya existe como `keep`); **filtros** → los actuales (frecuencia, 50/60 Hz, armónicos). Modelos de HF → solo `intensidad`. Valores por defecto = los actuales. Los valores se validan contra el esquema; un parámetro desconocido se rechaza.
- [x] **A4. Ejecución de la cadena** en [`stages.py`](../../apps/audio-enhancer/engine/src/audio_enhancer_engine/stages.py), [`denoise.py`](../../apps/audio-enhancer/engine/src/audio_enhancer_engine/denoise.py) y [`pipeline.py`](../../apps/audio-enhancer/engine/src/audio_enhancer_engine/pipeline.py): cada etapa se aplica por bloque en orden, con su intensidad (mezcla con su propia entrada) y parámetros; los filtros usan [`dsp.py`](../../apps/audio-enhancer/engine/src/audio_enhancer_engine/dsp.py) por etapa en lugar del filtro monolítico. Se permite repetir una caja. **Contexto:** la suma de `context_s` de las etapas debe caber en `CONTEXT_S`; si no, error legible al construir la cadena (no resultados erróneos en silencio).
- [x] **A5. Hash de caché** (`processing_hash`): incluye el **orden** de la cadena, los parámetros de cada etapa activa y la huella (sha256) de cada modelo; las etapas desactivadas no entran (forma canónica); sube `PIPELINE_VERSION` (3): la caché de v0.2.0 se invalida y se purga con el mecanismo de caducidad existente.
- [x] **A6. Protocolo** ([`server.py`](../../apps/audio-enhancer/engine/src/audio_enhancer_engine/server.py)): `models_catalog` devuelve también el esquema de parámetros y valores por defecto; nuevo `stage_catalog` (cajas disponibles: filtros + modelos instalados compatibles, con esquema); `enhance` acepta el formato de cadena **y** el plano antiguo (compatibilidad). Validación estricta sin matar el lector.
- [x] **A7. Tests del motor:** migración (A2), orden importa (A→B ≠ B→A con etapas reales y con una etapa de prueba), etapa repetida, etapa desactivada (hash canónico y mismo audio que sin ella), parámetros inválidos/desconocidos/fuera de rango, volumen siempre último, límite de contexto, esquema en el catálogo, protocolo con ambos formatos, binario congelado con una cadena de 2 modelos.

## Fase B — Interfaz: estructura, cadena de cajas y configuración por caja

- [x] **B1. Tipos y migración en la interfaz** ([`settings.ts`](../../apps/audio-enhancer/src/settings.ts), [`presets.ts`](../../apps/audio-enhancer/src/presets.ts)): tipo `Chain`/`Stage`, `sanitize` por esquema, **migración de los preajustes guardados** (localStorage v1 → v2) y de los preajustes de fábrica a cadenas. Preset = cadena completa + salida.
- [x] **B2. Estructura y navegación** ([`App.tsx`](../../apps/audio-enhancer/src/App.tsx), [`styles.css`](../../apps/audio-enhancer/src/styles.css)): una sola cabecera (título una vez), pestañas **Audio · Cadena · Modelos** con ARIA (`tablist`/`tab`/`tabpanel`, flechas del teclado), estado del motor discreto, sin botones sueltos. La pestaña activa conserva el estado de las otras (no se pierde la prueba ni la cadena).
- [x] **B3. `ChainEditor`** (componente nuevo): cajas en fila con conectores; seleccionar, **añadir** (menú con filtros y modelos instalados), **quitar**, **activar/desactivar** (puenteo) y **reordenar con arrastrar y con botones «Mover antes/después»** (teclado). Extremos fijos no movibles. Cada caja muestra nombre, estado (activa/desactivada, modelo sin instalar, licencia sin verificar). Se adapta a ventana estrecha (envuelve). Objetivos táctiles ≥ 44 px.
- [x] **B4. `StageSettings`** (componente nuevo, dirigido por esquema): panel de la caja seleccionada, debajo de la cadena; controles generados por tipo (slider, select, interruptor), con ayuda en lenguaje llano, **«Restablecer»** por caja y valores por defecto del esquema. Para modelos: licencia/tamaño/aviso de no verificado. `Volumen` y `Salida` presentan aquí LUFS/pico y canales/formato. Reemplaza al `SettingsPanel` actual.
- [x] **B5. Pestaña Audio** ([`App.tsx`](../../apps/audio-enhancer/src/App.tsx)): onda con fragmento, banda con la **cadena activa en solo lectura** (enlace a «Cadena»), jerarquía clara de acciones («Probar» y «Procesar todo» no compiten), sin texto cortado ni columna de ajustes interminable.
- [x] **B6. Cadena por defecto y estados vacíos:** la cadena inicial equivale al «Equilibrado» actual; textos de ayuda y estados vacíos en [`i18n/es.ts`](../../apps/audio-enhancer/src/i18n/es.ts) (todo en español, claves preparadas para otros idiomas).

## Fase C — Reproductor de prueba

- [x] **C1. `PreviewPlayer`** (sustituye a [`ABPlayer.tsx`](../../apps/audio-enhancer/src/components/ABPlayer.tsx)): reproducir/pausa, **barra de posición con arrastre y teclado**, tiempo `0:04 / 0:10`, **bucle** opcional, alternar Original/Mejorado conservando la posición, compensación de volumen (se mantiene), reproducción **solo del fragmento** (la barra abarca solo el fragmento; al terminar se detiene o repite).
- [x] **C2. Cabezal correcto:** el cabezal se calculaba con el inicio del fragmento *actual* en lugar del que se usó al probar, así que salía en el sitio equivocado si se movía el fragmento después de probar (corregido: el reproductor informa tiempo absoluto con el fragmento de SU prueba). Mapear `inicio_del_fragmento + t`, dibujarlo siempre dentro del fragmento y mostrarlo también en pausa.
- [x] **C3. Prueba desactualizada:** la prueba guarda una instantánea de (cadena + salida + fragmento). Si cambia cualquiera, el reproductor lo marca («desactualizada»), el botón principal pasa a «Probar de nuevo» y no se presenta como si fuera el resultado actual. Mover los extremos del fragmento también la desactualiza.
- [x] **C4. Archivos de prueba:** los de la ranura anterior no se reproducen ni se confunden con la nueva prueba (hoy hay dos ranuras alternas); comprobar que Original y Mejorado corresponden al mismo fragmento y que no se reproduce nada fuera de él.

## Fase D — Diseño, capturas y verificación visual

- [x] **D1. Revisión visual con capturas** en cada estado: inicio, archivo cargado, pestañas Audio/Cadena/Modelos, caja seleccionada, prueba actualizada y desactualizada, error, ventana estrecha (~700 px), modo oscuro, y **ventana real de Tauri** con el script de captura por identificador de ventana (macOS; sin pantalla completa, para no capturar otras apps). Revisión manual de cada captura y corrección de defectos antes de cerrar.
- [x] **D2. Pulido según las reglas de diseño:** tokens de color/espaciado, contraste, foco visible en todos los controles, `prefers-reduced-motion`, jerarquía tipográfica, texto sin recortes.
- [x] **D3. Tests de interfaz (vitest):** `ChainEditor` (añadir, quitar, desactivar, reordenar con botones y con teclado, extremos fijos), `StageSettings` (esquema → controles, restablecer, valores por defecto), `PreviewPlayer` (seek, bucle, clamp al fragmento, A/B conserva la posición, desactualizada), cabezal absoluto, migración de ajustes y de preajustes, pestañas ARIA.
- [x] **D4. e2e con el motor real** ([`e2e/run.mjs`](../../apps/audio-enhancer/e2e/run.mjs)): armar una cadena, cambiar el orden y verificar que la prueba queda desactualizada, re-probar, mover la barra de reproducción dentro del fragmento, ajustes por caja, preajuste → cadena.

## Proceso y cierre

- [x] **P1. Higiene del repo:** añadir `.agents/`, `.claude/skills/` y `skills-lock.json` a [`.gitignore`](../../.gitignore) (contenido de terceros instalado en el proyecto; no se publica). El usuario decide si quiere la skill de forma global.
- [x] **P2. Documentación:** README de la app y del motor (contrato de la cadena y de los esquemas de parámetros), `docs/verification/`, cambios visibles.
- [x] **P3. Versión 0.3.0**, CI verde en Windows y macOS, instaladores, etiqueta y pre-release.

## Pruebas empíricas aplazadas `[⏳ ACK]`

- Aspecto y usabilidad en **Windows** (WebView2): solo se capturan macOS y Chromium.
- Calidad percibida de cadenas con varios modelos en audio real (no hay audios de prueba).
- Tiempo y VRAM de una cadena de varios modelos en la GTX 1650 Ti (los modelos se cargan a la vez).
- Arrastrar y soltar de cajas en la ventana real (la automatización de la ventana nativa no es posible desde aquí).

## Riesgos sin verificar `[⚠️ UNVERIFIED]`

- Que `<audio>` con el protocolo `asset:` de Tauri soporte **búsqueda con peticiones de rango** en WKWebView y WebView2 (la barra de posición depende de ello). Si no, el reproductor debe caer a cargar el fragmento completo en memoria (`Blob`), que es viable porque dura ≤ 60 s.
- Que la suma de contextos de varias etapas quepa en `CONTEXT_S` con cadenas reales (A4 lo comprueba y falla de forma legible si no).
- Que el reordenado con arrastre HTML5 funcione igual en WebView2 que en Chromium (los botones y el teclado son la vía garantizada).

## Exclusiones acordadas

- Sin grafo libre (ramas/mezclas paralelas); la intensidad por caja cubre mezclar con el original.
- Sin parámetros inventados: solo los que el adaptador soporta.
- Sin PyTorch (v0.4.0), sin firmar instaladores, sin soporte de otros idiomas más allá de dejar las claves preparadas.
- Las cajas `Entrada`, `Volumen` y `Salida` no se mueven ni se quitan.

---

### 🔍 Assumption Lifecycle Legend:

- `[⚠️ UNVERIFIED]`: Siloed external contract. Requires indisputable evidence to verify.
- `[⏳ ACK]`: Acknowledged assumption. Factual evidence unavailable; risk accepted and opaque-box empirical test strictly scheduled.
