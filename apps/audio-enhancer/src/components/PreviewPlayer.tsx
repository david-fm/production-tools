import { useEffect, useRef, useState } from "react";
import { compensatedVolumes, formatTime } from "../format";
import { es } from "../i18n/es";

interface Props {
  originalUrl: string;
  enhancedUrl: string;
  originalLufs: number | null;
  enhancedLufs: number | null;
  /** Fragmento del archivo que contiene esta prueba (segundos del archivo original). */
  region: [number, number];
  /** La cadena, un ajuste o el fragmento cambiaron después de probar. */
  stale?: boolean;
  /** Posición actual en segundos DEL ARCHIVO (inicio del fragmento + tiempo de reproducción). */
  onTime?: (seconds: number) => void;
}

type Which = "original" | "enhanced";

/**
 * Reproduce SOLO el fragmento de prueba (original y mejorado, alternando sin perder la posición).
 * La barra de posición abarca únicamente el fragmento; no se puede salir de él.
 */
export function PreviewPlayer({ originalUrl, enhancedUrl, originalLufs, enhancedLufs, region, stale, onTime }: Props) {
  const orig = useRef<HTMLAudioElement>(null);
  const enh = useRef<HTMLAudioElement>(null);
  const fallback = Math.max(0.1, region[1] - region[0]);
  const [which, setWhich] = useState<Which>("enhanced");
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(fallback);
  const [loop, setLoop] = useState(false);
  const [compensate, setCompensate] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const el = (w: Which) => (w === "original" ? orig.current : enh.current);

  useEffect(() => {
    const v = compensatedVolumes(originalLufs, enhancedLufs, compensate);
    if (orig.current) orig.current.volume = v.original;
    if (enh.current) enh.current.volume = v.enhanced;
  }, [originalLufs, enhancedLufs, compensate, originalUrl, enhancedUrl]);

  useEffect(() => {
    // Nueva prueba: todo vuelve al principio del fragmento.
    setPlaying(false); setError(null); setTime(0); setDuration(fallback);
  }, [originalUrl, enhancedUrl, fallback]);

  const report = (t: number) => { setTime(t); onTime?.(region[0] + t); };

  const seek = (t: number) => {
    const clamped = Math.min(Math.max(0, t), duration);
    for (const a of [orig.current, enh.current]) if (a) a.currentTime = clamped;
    report(clamped);
  };

  const switchTo = (next: Which) => {
    if (next === which) return;
    const from = el(which);
    const to = el(next);
    if (from && to) {
      to.currentTime = from.currentTime;
      from.pause();
      if (playing) void to.play().catch((e) => setError(String(e)));
    }
    setWhich(next);
  };

  const toggle = () => {
    const a = el(which);
    if (!a) return;
    if (playing) { a.pause(); setPlaying(false); return; }
    if (time >= duration - 0.05) seek(0); // al final: empezar de nuevo
    a.play().then(() => setPlaying(true), (e) => setError(String(e)));
  };

  const onEnded = () => {
    if (loop) {
      seek(0);
      void el(which)?.play().catch((e) => setError(String(e)));
    } else {
      setPlaying(false);
      report(duration);
    }
  };

  const meta = (w: Which) => (e: React.SyntheticEvent<HTMLAudioElement>) => {
    const d = e.currentTarget.duration;
    if (w === which && Number.isFinite(d) && d > 0) setDuration(d);
  };
  const tick = (w: Which) => (e: React.SyntheticEvent<HTMLAudioElement>) => { if (w === which) report(e.currentTarget.currentTime); };

  return (
    <div className={`player${stale ? " stale" : ""}`}>
      <audio ref={orig} src={originalUrl} preload="auto" onEnded={onEnded} onLoadedMetadata={meta("original")} onTimeUpdate={tick("original")}
             onError={() => setError("No se pudo cargar el audio original")} />
      <audio ref={enh} src={enhancedUrl} preload="auto" onEnded={onEnded} onLoadedMetadata={meta("enhanced")} onTimeUpdate={tick("enhanced")}
             onError={() => setError("No se pudo cargar el audio mejorado")} />
      {stale && (
        <div className="banner warn" role="status">
          <p><strong>{es.stalePreview}</strong></p>
          <p>{es.staleHelp}</p>
        </div>
      )}
      <p className="hint">{es.previewRange(formatTime(region[0]), formatTime(region[1]))} · {es.previewOnlyHelp}</p>
      <div className="player-row">
        <button type="button" className="play" onClick={toggle} aria-pressed={playing}>{playing ? es.pause : es.play}</button>
        <span className="time" aria-hidden="true">{formatTime(time)} / {formatTime(duration)}</span>
        <input type="range" className="seek" aria-label={es.seek} aria-valuetext={`${formatTime(time)} de ${formatTime(duration)}`}
               min={0} max={duration} step={0.01} value={Math.min(time, duration)} onChange={(e) => seek(Number(e.target.value))} />
      </div>
      <div className="player-row">
        <div role="group" aria-label="A/B" className="segmented">
          <button type="button" aria-pressed={which === "original"} onClick={() => switchTo("original")}>
            {es.original}{originalLufs !== null && <small> {es.lufsOf(originalLufs)}</small>}
          </button>
          <button type="button" aria-pressed={which === "enhanced"} onClick={() => switchTo("enhanced")}>
            {es.enhanced}{enhancedLufs !== null && <small> {es.lufsOf(enhancedLufs)}</small>}
          </button>
        </div>
        <label className="check"><input type="checkbox" checked={loop} onChange={(e) => setLoop(e.target.checked)} />{es.loop}</label>
      </div>
      <label className="check" title={es.loudnessCompHelp}>
        <input type="checkbox" checked={compensate} onChange={(e) => setCompensate(e.target.checked)} />
        {es.loudnessComp}
      </label>
      <p className="help">{es.loudnessCompHelp}</p>
      {error && <p role="alert" className="error">{error}</p>}
    </div>
  );
}
