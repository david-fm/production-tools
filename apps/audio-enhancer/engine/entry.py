"""Punto de entrada para PyInstaller (evita imports relativos en el script principal)."""

from audio_enhancer_engine.server import main

if __name__ == "__main__":
    main()
