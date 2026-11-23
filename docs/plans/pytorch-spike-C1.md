# C1 — ¿Hace falta PyTorch en v0.2.0?

**Decisión: se aplaza a v0.3.0** (criterio fijado en la revisión Goldfish: solo si un modelo cubre una tarea sin
alternativa ONNX o mejora una métrica objetiva).

## Qué hay hoy

- Reducción de ruido: DeepFilterNet3 (ONNX).
- Aislar voz / quitar música y fondo: Kim Vocal 2 (MDX-Net, ONNX). Medido con voz de dominio público + música sintética:
  la música baja ~45 dB y la voz se conserva (-1,1 dB), con alineación temporal exacta.

## El hueco real: quitar reverberación en audio mono

- `Reverb_HQ_By_FoxJoy` (MDX-Net ONNX) solo detecta la reverberación comparando L/R. Con mono duplicado su salida es ~0
  (medido: rms 0,0003 frente a 0,05 con colas decorrelacionadas). No sirve para nuestro pipeline (canal a canal).
- Candidatos aún sin evaluar: `UVR-DeEcho-DeReverb.onnx` (223 MB, arquitectura VR, necesitaría adaptador propio) y
  `deverb_bs_roformer` (364 MB, pesado para 4 GB de VRAM). Resemble Enhance cubre la tarea pero solo existe en PyTorch.

## Por qué no se construye ahora

1. No hay un modelo concreto que lo exija hoy; los candidatos ONNX del hueco no se han evaluado todavía.
2. Un runtime PyTorch con CUDA son varios GB, con lockfile con hashes y un segundo sidecar: infraestructura grande sin
   beneficio visible hasta tener el modelo y audios reales de prueba (no los hay).
3. No se puede verificar sin la GPU de la usuaria; el riesgo de dejar algo a medias es alto.

## Siguiente paso propuesto

Evaluar los dos candidatos ONNX de dereverb con audio real. Solo si ninguno funciona, construir C2–C5 con Resemble
Enhance como primer modelo.
