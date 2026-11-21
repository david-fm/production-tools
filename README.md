# production-tools

Monorepo de herramientas para producción audiovisual. Cada herramienta vive en `apps/` y es independiente.

| Herramienta | Descripción | Estado |
|---|---|---|
| [`apps/audio-enhancer`](apps/audio-enhancer) | App de escritorio (Windows y macOS) para mejorar la calidad del audio: reducción de ruido, vista previa A/B y presets explicados. | En desarrollo (M0: esqueleto) |

## Privacidad

Las aplicaciones **no envían telemetría**. Tus grabaciones se procesan localmente y nunca salen de tu equipo.
El único tráfico de red previsto es la descarga opcional de modelos de IA (a partir de la v0.2.0), a petición del usuario.

## Instalación sin firmar

Los instaladores todavía no están firmados, así que el sistema mostrará un aviso:

- **macOS (Gatekeeper):** al abrir por primera vez, clic derecho sobre la app → *Abrir* → *Abrir*. Si dice que "está dañada", ejecuta `xattr -cr "/Applications/Audio Enhancer.app"`.
- **Windows (SmartScreen):** en *Windows protegió su PC*, pulsa *Más información* → *Ejecutar de todos modos*.

## Desarrollo

Requisitos: Node + pnpm, Rust (vía `rustup`), Python 3.12 + [uv](https://docs.astral.sh/uv/).
Ver el README de cada app.

## Licencias de terceros

- **ffmpeg**: se distribuye únicamente una build **LGPL** (sin `--enable-gpl`), como ejecutable separado; el CI falla si la build contiene `--enable-gpl` o `--enable-nonfree`. Código fuente y configuración: ver [THIRD_PARTY_NOTICES.md](apps/audio-enhancer/THIRD_PARTY_NOTICES.md).
- Modelos de IA: cada uno declara su licencia en el manifiesto (v0.2.0).

## Licencia

MIT (ver [LICENSE](LICENSE)). **Pendiente de confirmar por el titular antes del primer push público.**
