import { useEffect, useRef, useState } from "react";
import { compensatedVolumes } from "../format";
import { es } from "../i18n/es";

interface Props {
  originalUrl: string;
  enhancedUrl: string;
  originalLufs: number | null;
  enhancedLufs: number | null;
  onTime?: (seconds: number) => void;
}

type Which = "original" | "enhanced";

/**
 * Reproduce el fragmento original y el mejorado alternando sin perder la posición.
 * Con la compensación activa, el más fuerte se atenúa hasta igualar al más débil.
 */
export function ABPlayer({ originalUrl, enhancedUrl, originalLufs, enhancedLufs, onTime }: Props) {
  const orig = useRef<HTMLAudioElement>(null);
  const enh = useRef<HTMLAudioElement>(null);
  const [which, setWhich] = useState<Which>("enhanced");
  const [playing, setPlaying] = useState(false);
  const [compensate, setCompensate] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const current = () => (which === "original" ? orig.current : enh.current);

  useEffect(() => {
    const v = compensatedVolumes(originalLufs, enhancedLufs, compensate);
    if (orig.current) orig.current.volume = v.original;
    if (enh.current) enh.current.volume = v.enhanced;
  }, [originalLufs, enhancedLufs, compensate, originalUrl, enhancedUrl]);

  useEffect(() => {
    setPlaying(false);
    setError(null);
  }, [originalUrl, enhancedUrl]);

  const switchTo = (next: Which) => {
    if (next === which) return;
    const from = current();
    const to = next === "original" ? orig.current : enh.current;
    if (from && to) {
      to.currentTime = from.currentTime;
      from.pause();
      if (playing) void to.play().catch((e) => setError(String(e)));
    }
    setWhich(next);
  };

  const toggle = () => {
    const el = current();
    if (!el) return;
    if (playing) {
      el.pause();
      setPlaying(false);
    } else {
      el.play().then(
        () => setPlaying(true),
        (e) => setError(String(e)),
      );
    }
  };

  return (
    <div className="ab-player">
      <audio ref={orig} src={originalUrl} preload="auto" onEnded={() => setPlaying(false)} onError={() => setError("No se pudo cargar el audio original")} onTimeUpdate={(e) => which === "original" && onTime?.(e.currentTarget.currentTime)} />
      <audio ref={enh} src={enhancedUrl} preload="auto" onEnded={() => setPlaying(false)} onError={() => setError("No se pudo cargar el audio mejorado")} onTimeUpdate={(e) => which === "enhanced" && onTime?.(e.currentTarget.currentTime)} />
      <div className="ab-controls">
        <button type="button" onClick={toggle} aria-pressed={playing}>
          {playing ? es.pause : es.play}
        </button>
        <div role="group" aria-label="A/B" className="segmented">
          <button type="button" aria-pressed={which === "original"} onClick={() => switchTo("original")}>
            {es.original}
            {originalLufs !== null && <small> {es.lufsOf(originalLufs)}</small>}
          </button>
          <button type="button" aria-pressed={which === "enhanced"} onClick={() => switchTo("enhanced")}>
            {es.enhanced}
            {enhancedLufs !== null && <small> {es.lufsOf(enhancedLufs)}</small>}
          </button>
        </div>
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
