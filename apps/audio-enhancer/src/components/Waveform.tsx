import { useCallback, useEffect, useRef } from "react";
import { formatTime } from "../format";

export interface Peaks {
  min: number[];
  max: number[];
  duration_s: number;
}

interface Props {
  peaks: Peaks;
  region: [number, number] | null;
  onRegionChange: (start: number, end: number) => void;
  playhead?: number | null;
  ariaLabel: string;
}

const HEIGHT = 120;

/** Forma de onda en <canvas> a partir de picos calculados por el motor (válido para audios de horas). */
export function Waveform({ peaks, region, onRegionChange, playhead, ariaLabel }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const dragStart = useRef<number | null>(null);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const dpr = window.devicePixelRatio || 1;
    const width = canvas.clientWidth;
    canvas.width = Math.max(1, Math.floor(width * dpr));
    canvas.height = HEIGHT * dpr;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const css = getComputedStyle(canvas);
    const wave = css.getPropertyValue("--wave").trim() || "#2563eb";
    const sel = css.getPropertyValue("--selection").trim() || "rgba(37,99,235,0.25)";
    const head = css.getPropertyValue("--playhead").trim() || "#dc2626";
    ctx.clearRect(0, 0, width, HEIGHT);

    const n = peaks.min.length;
    const mid = HEIGHT / 2;
    ctx.fillStyle = wave;
    for (let x = 0; x < width; x++) {
      const i = Math.min(n - 1, Math.floor((x / width) * n));
      const lo = Math.max(-1, peaks.min[i] ?? 0);
      const hi = Math.min(1, peaks.max[i] ?? 0);
      const y1 = mid - hi * mid;
      const y2 = mid - lo * mid;
      ctx.fillRect(x, y1, 1, Math.max(1, y2 - y1));
    }
    if (region) {
      const x1 = (region[0] / peaks.duration_s) * width;
      const x2 = (region[1] / peaks.duration_s) * width;
      ctx.fillStyle = sel;
      ctx.fillRect(x1, 0, Math.max(2, x2 - x1), HEIGHT);
    }
    if (playhead != null && playhead >= 0) {
      ctx.fillStyle = head;
      ctx.fillRect((playhead / peaks.duration_s) * width, 0, 2, HEIGHT);
    }
  }, [peaks, region, playhead]);

  useEffect(() => {
    draw();
    const onResize = () => draw();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [draw]);

  const timeAt = (clientX: number): number => {
    const rect = canvasRef.current!.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
    return ratio * peaks.duration_s;
  };

  return (
    <div className="waveform">
      <canvas
        ref={canvasRef}
        role="img"
        aria-label={ariaLabel}
        style={{ width: "100%", height: HEIGHT, touchAction: "none", cursor: "crosshair" }}
        onPointerDown={(e) => {
          (e.target as HTMLCanvasElement).setPointerCapture(e.pointerId);
          dragStart.current = timeAt(e.clientX);
        }}
        onPointerMove={(e) => {
          if (dragStart.current === null) return;
          const t = timeAt(e.clientX);
          onRegionChange(Math.min(dragStart.current, t), Math.max(dragStart.current, t));
        }}
        onPointerUp={() => {
          dragStart.current = null;
        }}
      />
      <div className="waveform-axis">
        <span>0:00</span>
        <span>{formatTime(peaks.duration_s)}</span>
      </div>
    </div>
  );
}
