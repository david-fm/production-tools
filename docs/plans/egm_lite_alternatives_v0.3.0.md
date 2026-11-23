# Alternatives Considered — v0.3.0: UX, cadena de cajas y reproductor de prueba

> **BLUF:** Recomiendo una **cadena lineal de cajas** (Entrada → cajas → Salida), reordenable con arrastrar **y con botones/teclado**, con un panel de configuración por caja generado desde un **esquema declarado por cada modelo** (con valores por defecto). No recomiendo un grafo libre (ramas y mezclas): el audio de una caja pasa a la siguiente, que es lo que pediste, y un grafo multiplicaría el coste de motor, caché y pruebas sin un caso de uso concreto.

## 1. Modelo de la cadena

| Opción | Qué es | Pros | Contras |
|---|---|---|---|
| **L1 (recomendada)** | Lista ordenada de cajas; cada una tiene `modelo/filtro + parámetros`; la salida de una es la entrada de la siguiente | Coincide con lo pedido; el pipeline por bloques y la caché ya son lineales; fácil de hacer accesible por teclado; presets = cadena completa | Sin ramas ni mezclas paralelas |
| L2 | Grafo libre con nodos y cables (p. ej. @xyflow/react) | Máxima flexibilidad (mezclar voz aislada con original, ramas) | Motor con DAG, caché por nodo, sincronización de bloques entre ramas, más pruebas; accesibilidad de cables por teclado es difícil; dependencia grande |
| L3 | Ajustes planos como hoy (solo reordenar etapas fijas) | Ya existe | No cumple "cajitas conectadas" |

**Si hace falta mezclar** (p. ej. 70 % voz aislada + 30 % original) ya existe el control de *intensidad* por caja (mezcla con su propia entrada); cubre el 90 % de ese caso sin grafo.

## 2. Qué es una caja

- **Fijas:** `Entrada` (el archivo) al principio, `Volumen` (normalización LUFS + limitador) y `Salida` al final. El volumen debe ser lo último: se mide sobre el resultado final en dos pasadas.
- **Movibles/añadibles/quitables:** `Recorte de graves`, `Zumbido eléctrico`, y cada modelo instalado (`Reducir ruido`, `Aislar voz`, modelos de HF compatibles). Se permite repetir una caja.
- **Parámetros:** solo los que el adaptador realmente soporta, declarados en el catálogo (`params: [{id, tipo, rango, defecto, ayuda}]`). Hoy: intensidad (todos), y para los MDX la opción «conservar voz / conservar el resto». Más parámetros solo cuando exista soporte real; no inventar controles.
- **Valores por defecto:** cada entrada del catálogo trae su configuración por defecto; «Restablecer» por caja.

## 3. Layout (propuesta)

```
┌ Audio Enhancer ───────────────────────────────── [Modelos] ┐
│  [ Audio ]  [ Cadena ]                  motor listo · CPU │
├────────────────────────────────────────────────────────────┤
│ Cadena (pestaña):                                          │
│  [Entrada]→[Graves 80Hz]→[Aislar voz]→[Reducir ruido]→[Volumen]→[Salida]
│                               ▲ seleccionada                │
│  ┌ Configuración de «Aislar voz» ──────────────────────┐   │
│  │ Intensidad ▬▬▬▬▬○ 100 %    Conservar: (voz)(resto)  │   │
│  │ [Restablecer]   Licencia sin verificar · 67 MB      │   │
│  └─────────────────────────────────────────────────────┘   │
├────────────────────────────────────────────────────────────┤
│ Audio (pestaña): onda con fragmento resaltado y cabezal;   │
│  banda con la cadena activa (solo lectura);                │
│  [Probar]  ▶ ──●────────── 0:04/0:10  [Original|Mejorado]  │
│  «Prueba desactualizada» si la cadena cambió               │
└────────────────────────────────────────────────────────────┘
```

Alternativa (X): un único panel con las tres zonas siempre visibles. Descartada por ancho: en una ventana de 1100 px queda todo comprimido (ya se ve en la captura actual de la barra de ajustes recortada).

## 4. Reproductor de prueba

- El audio de prueba contiene **solo el fragmento** procesado. El deslizador de reproducción (seek) abarca solo ese fragmento; no puede salirse.
- El cabezal se dibuja sobre la onda **dentro de la región** y siempre visible (hoy solo aparece al reproducir).
- **Bucle** opcional del fragmento; el cambio Original/Mejorado conserva la posición.
- **Prueba desactualizada**: si cambia la cadena o un parámetro tras probar, el reproductor lo marca y el botón principal pasa a «Probar de nuevo». Así no se escucha por error algo que no corresponde a los ajustes actuales.
- Mover los extremos del fragmento tras probar → también desactualiza (los bloques ya calculados se reutilizan por la caché, así que re-probar es rápido).
- Búsqueda en `<audio>` con el protocolo `asset:` de Tauri requiere peticiones con rango: `[⚠️ UNVERIFIED]` en WebView2/WKWebView hasta probarlo en la ventana real.

## 5. Notas del proceso de diseño

- La skill `ui-ux-pro-max` devuelve para esta consulta un patrón de *landing page* («Product Demo + Features»): no aplica a una app de escritorio. Solo se usan sus reglas de UX: arrastrar no puede ser la única forma (WCAG 2.5.7), controles ≥ 44 px, contraste 4,5:1, foco visible, `prefers-reduced-motion`, estados por `aria-pressed`.
- Capturas: la ventana real de Tauri se puede capturar (`screencapture -l <id>`), pero no se pueden manejar los diálogos nativos de abrir archivo ni el arrastrar y soltar. Los estados con un archivo cargado se capturan en Chromium con el motor real (e2e).
