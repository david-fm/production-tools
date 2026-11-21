// Todas las cadenas visibles viven aquí (español primero). Para añadir un idioma:
// crear en.ts con las mismas claves y seleccionar según la preferencia del usuario.
export const es = {
  appTitle: "Audio Enhancer",
  subtitle: "Mejora la calidad del audio de tus grabaciones.",

  // Motor y modelo
  engineChecking: "Iniciando el motor de audio…",
  engineReady: (version: string) => `Motor de audio listo (v${version})`,
  engineError: (reason: string) => `Error: ${reason}`,
  accel: "Procesamiento",
  accelCpu: "CPU",
  modelMissing:
    "La primera vez se descarga el modelo de reducción de ruido (≈8 MB, una sola vez). Se verifica su integridad antes de usarlo.",
  modelInstall: "Descargar modelo ahora",
  modelInstalling: "Descargando modelo…",
  modelReady: "Modelo de reducción de ruido instalado",

  // Pantalla inicial
  howTitle: "Cómo funciona",
  steps: [
    "Abre una grabación de audio o un video.",
    "Elige un fragmento corto y prueba los ajustes.",
    "Compara el antes y el después sin que el volumen te engañe.",
    "Cuando suene bien, aplícalo a todo el archivo.",
  ],
  privacy: "Todo se procesa en tu equipo: tus grabaciones no salen de él.",

  // Archivo
  openFile: "Abrir archivo de audio o video…",
  dropHint: "o arrastra aquí un archivo",
  fileFilterName: "Audio y video",
  loadingFile: "Preparando el archivo (se decodifica una sola vez)…",
  noAudio: "El archivo no tiene pistas de audio.",
  audioTrack: "Pista de audio",
  trackLabel: (i: number, ch: number, codec: string) =>
    `Pista ${i + 1}: ${ch} canal${ch === 1 ? "" : "es"} (${codec})`,
  duration: "Duración",

  // Selección y vista previa
  selection: "Fragmento de prueba",
  selectionHelp:
    "Arrastra sobre la forma de onda para elegir un fragmento (hasta 60 s). Prueba tus ajustes ahí antes de procesar todo.",
  selectionStart: "Inicio (s)",
  selectionEnd: "Fin (s)",
  previewButton: "Probar este fragmento",
  previewRunning: "Procesando fragmento…",
  previewFirstHint: "Elige un fragmento y pulsa “Probar este fragmento” para comparar antes y después.",
  original: "Original",
  enhanced: "Mejorado",
  play: "Reproducir",
  pause: "Pausa",
  loudnessComp: "Compensar volumen al comparar",
  loudnessCompHelp:
    "Lo más fuerte suena “mejor” aunque no lo sea. Esto iguala el volumen de ambos para que compares calidad, no volumen.",
  previewLoudnessNote:
    "El volumen final del trabajo completo se ajusta con más exactitud que en la prueba; puede diferir ≈1 LU.",
  lufsOf: (value: number) => `${value.toFixed(1)} LUFS`,

  // Ajustes
  settings: "Ajustes",
  preset: "Preajuste",
  presetHelp: "Un punto de partida para tu situación. Puedes cambiar cualquier valor después.",
  savePreset: "Guardar como preajuste…",
  presetNamePrompt: "Nombre del preajuste",
  deletePreset: "Borrar",
  customPresets: "Mis preajustes",
  builtinPresets: "Preajustes",

  denoise: "Reducción de ruido (IA)",
  denoiseHelp:
    "Elimina ruido de fondo constante (viento, aire acondicionado, ventiladores, siseo) conservando la voz.",
  denoiseStrength: "Intensidad",
  denoiseStrengthHelp:
    "100 % usa solo el audio limpiado. Valores más bajos mezclan parte del original: más natural, con algo de ruido.",

  highpass: "Recortar graves",
  highpassHelp:
    "Quita retumbos y viento por debajo de esta frecuencia. 80–100 Hz es seguro para voz; sube a 120 Hz si hay mucho viento.",
  off: "Desactivado",
  hz: "Hz",

  notch: "Zumbido eléctrico",
  notchHelp:
    "Elimina el zumbido de la red eléctrica y sus armónicos. Usa 50 Hz en Europa y gran parte de Latinoamérica, 60 Hz en América del Norte, México y Centroamérica.",

  normalize: "Ajustar volumen",
  normalizeHelp:
    "Lleva todo el audio a un volumen objetivo medido en LUFS (la medida estándar de volumen percibido).",
  target: "Objetivo",
  targetWeb: "−16 LUFS (YouTube, redes, podcast)",
  targetTv: "−23 LUFS (TV, EBU R128)",
  targetCustom: "Personalizado",
  truePeak: "Pico máximo de muestra",
  truePeakHelp:
    "Techo para evitar saturación. Mide el pico de las muestras (no el true-peak entre muestras); −1 dB deja margen suficiente en casi todos los casos.",

  channels: "Canales",
  channelsHelp: "“Cada uno por separado” conserva estéreo o multicanal. “Mezclar a mono” suma todo en un canal.",
  channelsEach: "Cada uno por separado",
  channelsMix: "Mezclar a mono",
  format: "Formato de salida",
  formatWav: "WAV 24 bits (recomendado para editar)",
  formatFlac: "FLAC 24 bits (más pequeño)",

  // Trabajo completo
  fullJob: "Audio completo",
  fullJobHelp:
    "Aplica estos ajustes a todo el archivo. Los bloques ya procesados se guardan: si se interrumpe, se retoma donde quedó.",
  processAll: "Procesar todo el audio…",
  processVideo: "Guardar video con el audio mejorado…",
  processVideoHelp: "El video se copia sin recomprimir; solo cambia el audio.",
  cancel: "Cancelar",
  stages: {
    decodificando: "Decodificando",
    procesando: "Procesando",
    uniendo: "Uniendo bloques",
    escribiendo: "Escribiendo archivo",
    listo: "Listo",
  } as Record<string, string>,
  jobDone: "Listo. Archivo guardado:",
  jobResult: (inLufs: string, outLufs: string) => `Volumen: ${inLufs} → ${outLufs}`,
  jobCancelled: "Trabajo cancelado.",
  resumed: (n: number) => `Se reutilizaron ${n} bloque${n === 1 ? "" : "s"} ya procesados.`,
  saveDialogTitle: "Guardar audio mejorado",
  saveVideoDialogTitle: "Guardar video con audio mejorado",
  dismiss: "Cerrar",

  // Espacio temporal
  cacheLabel: (bytes: number) =>
    `Archivos temporales: ${bytes >= 1e9 ? (bytes / 1e9).toFixed(1) + " GB" : (bytes / 1e6).toFixed(0) + " MB"}`,
  clearCache: "Liberar espacio",
  clearCacheHelp:
    "Borra los archivos temporales (audio decodificado y bloques procesados). La próxima vez se recalculan; se limpian solos tras 7 días sin uso.",

  // Presets integrados
  presets: {
    default: { name: "Equilibrado", description: "Limpieza suave, ruido reducido y volumen para web." },
    exterior: { name: "Entrevista en exterior", description: "Viento y ruido ambiente: recorte de graves y limpieza completa." },
    estudio: { name: "Locución en estudio", description: "Ruido leve: limpieza parcial para conservar naturalidad." },
    hum50: { name: "Zumbido 50 Hz", description: "Quita zumbido eléctrico de 50 Hz y armónicos." },
    hum60: { name: "Zumbido 60 Hz", description: "Quita zumbido eléctrico de 60 Hz y armónicos." },
    tv: { name: "Entrega para TV (−23 LUFS)", description: "Limpieza y volumen EBU R128." },
    volumen: { name: "Solo volumen", description: "Sin IA ni filtros: únicamente ajusta el volumen." },
  } as Record<string, { name: string; description: string }>,
} as const;
