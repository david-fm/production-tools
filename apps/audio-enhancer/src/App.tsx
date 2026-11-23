import { convertFileSrc } from "@tauri-apps/api/core";
import { getCurrentWebview } from "@tauri-apps/api/webview";
import { appCacheDir, join } from "@tauri-apps/api/path";
import { open, save } from "@tauri-apps/plugin-dialog";
import { useCallback, useEffect, useRef, useState } from "react";
import { ABPlayer } from "./components/ABPlayer";
import { ModelsPanel, type ModelInfo } from "./components/ModelsPanel";
import { SettingsPanel } from "./components/SettingsPanel";
import { Waveform, type Peaks } from "./components/Waveform";
import { cancelJob, engineCall, LONG_TIMEOUT_S, onEngineProgress, type EngineProgress } from "./engine";
import { clampRegion, fileName, formatTime, MAX_PREVIEW_S } from "./format";
import { es } from "./i18n/es";
import { loadCustomPresets, saveCustomPresets, upsertPreset, type CustomPreset } from "./presets";
import { DEFAULT_SETTINGS, type Settings } from "./settings";

interface AudioStream { index: number; channels: number; sample_rate: number; codec: string }
interface Probe { duration_s: number | null; has_video: boolean; audio_streams: AudioStream[] }
interface JobResult {
  output: string; duration_s: number; input_lufs: number | null; output_lufs: number | null;
  gain_db: number; peak_limited: boolean; resumed_blocks: number; warnings: string[];
}
interface Loaded { path: string; probe: Probe; peaks: Peaks; audioIndex: number }
interface Preview { originalUrl: string; enhancedUrl: string; originalLufs: number | null; enhancedLufs: number | null }

const MEDIA_FILTER = [{ name: es.fileFilterName, extensions: ["wav", "mp3", "flac", "m4a", "aac", "ogg", "opus", "aif", "aiff", "mp4", "mov", "mkv", "mxf", "avi", "mts", "m2ts", "webm"] }];
const fmtLufs = (v: number | null) => (v === null ? "—" : es.lufsOf(v));

export function App() {
  const [engineStatus, setEngineStatus] = useState<string>(es.engineChecking);
  const [engineOk, setEngineOk] = useState(false);
  const [providers, setProviders] = useState<string[]>([]);
  const [modelInstalled, setModelInstalled] = useState<boolean | null>(null);
  const [busy, setBusy] = useState<null | "loading" | "preview" | "full" | "model">(null);
  const [progress, setProgress] = useState<{ value: number; stage: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [region, setRegion] = useState<[number, number] | null>(null);
  const [settings, setSettings] = useState<Settings>(DEFAULT_SETTINGS);
  const [customPresets, setCustomPresets] = useState<CustomPreset[]>(() => loadCustomPresets());
  const [preview, setPreview] = useState<Preview | null>(null);
  const [playhead, setPlayhead] = useState<number | null>(null);
  const [result, setResult] = useState<JobResult | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [showModels, setShowModels] = useState(false);
  const [catalog, setCatalog] = useState<ModelInfo[]>([]);
  const [cacheBytes, setCacheBytes] = useState<number | null>(null);
  const activeJob = useRef<string | null>(null);
  const busyRef = useRef(false); // síncrono: evita arrancar dos trabajos antes de que React re-renderice
  const cancelRequested = useRef(false);
  const counter = useRef(0);
  const settingsRef = useRef(settings);
  settingsRef.current = settings;

  const refreshCache = useCallback(() => {
    engineCall<{ bytes: number }>("cache_info").then((r) => setCacheBytes(r.bytes)).catch(() => setCacheBytes(null));
  }, []);

  const refreshCatalog = useCallback(() => {
    engineCall<ModelInfo[] | null>("models_catalog").then((r) => setCatalog(r ?? [])).catch(() => setCatalog([]));
  }, []);

  // --- Motor: comprobación con reintentos (puede estar reiniciándose) ---
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const check = async () => {
      try {
        const health = await engineCall<{ version: string }>("health");
        const list = await engineCall<string[]>("preferred_providers");
        const models = await engineCall<{ deepfilternet3: { installed: boolean } }>("models_status");
        if (cancelled) return;
        setEngineStatus(es.engineReady(health.version));
        setProviders(list);
        setModelInstalled(models.deepfilternet3.installed);
        setEngineOk(true);
        refreshCache();
        refreshCatalog();
      } catch (e) {
        if (cancelled) return;
        setEngineOk(false);
        setEngineStatus(es.engineError(String(e)));
        timer = setTimeout(check, 2000);
      }
    };
    void check();
    return () => { cancelled = true; if (timer) clearTimeout(timer); };
  }, [refreshCache, refreshCatalog]);

  // --- Progreso de trabajos ---
  useEffect(() => {
    const un = onEngineProgress((e: EngineProgress) => {
      if (e.job && e.job === activeJob.current) setProgress({ value: e.value, stage: e.stage ?? "" });
    });
    return () => { void un.then((f) => f()); };
  }, []);

  /** Ejecuta un trabajo en exclusiva. Devuelve undefined si ya había otro en curso, falló o se canceló. */
  const runJob = useCallback(async <T,>(kind: NonNullable<typeof busy>, job: string, fn: () => Promise<T>): Promise<T | undefined> => {
    if (busyRef.current) return undefined;
    busyRef.current = true;
    cancelRequested.current = false;
    activeJob.current = job;
    setBusy(kind);
    setProgress({ value: 0, stage: "" });
    setError(null);
    try {
      return await fn();
    } catch (e) {
      const msg = String(e);
      if (msg.includes("cancelado")) setNotice(es.jobCancelled);
      else setError(msg);
      return undefined;
    } finally {
      activeJob.current = null;
      busyRef.current = false;
      setBusy(null);
      setProgress(null);
      refreshCache();
    }
  }, [refreshCache]);

  /** Cambia de fase dentro de un trabajo (cada fase tiene su propia clave); respeta una cancelación pendiente. */
  const phase = (key: string) => {
    if (cancelRequested.current) throw new Error("cancelado");
    activeJob.current = key;
    return key;
  };

  // --- Abrir archivo ---
  const loadFile = useCallback(async (path: string) => {
    if (busyRef.current) return; // p. ej. un archivo soltado mientras hay un trabajo en curso
    setResult(null); setNotice(null); setPreview(null);
    const n = ++counter.current;
    await runJob("loading", `load-${n}`, async () => {
      const probe = await engineCall<Probe>("probe", { path });
      if (probe.audio_streams.length === 0) throw new Error(es.noAudio);
      const peaks = await engineCall<Peaks>("waveform", { path, points: 1600, audio_index: 0, channels: settingsRef.current.channels },
        { job: phase(`wave-${n}`), timeoutS: LONG_TIMEOUT_S });
      setLoaded({ path, probe, peaks, audioIndex: 0 });
      setRegion(clampRegion(0, Math.min(10, peaks.duration_s), peaks.duration_s));
    });
  }, [runJob]);

  const chooseFile = async () => {
    const picked = await open({ multiple: false, filters: MEDIA_FILTER });
    if (typeof picked === "string") await loadFile(picked);
  };

  const loadFileRef = useRef(loadFile);
  loadFileRef.current = loadFile;
  useEffect(() => {
    let disposed = false;
    let unlisten: (() => void) | undefined;
    getCurrentWebview().onDragDropEvent((event) => {
      if (event.payload.type === "drop" && event.payload.paths[0]) void loadFileRef.current(event.payload.paths[0]);
    }).then((f) => {
      if (disposed) f(); // el efecto ya se limpió (p. ej. StrictMode): no dejar el listener registrado
      else unlisten = f;
    }).catch(() => undefined);
    return () => { disposed = true; unlisten?.(); };
  }, []);

  // --- Vista previa del fragmento ---
  const runPreview = async () => {
    if (!loaded || !region || busyRef.current) return;
    const n = ++counter.current;
    const slot = n % 2;
    await runJob("preview", `preview-${n}`, async () => {
      const dir = await join(await appCacheDir(), "preview");
      const origPath = await join(dir, `orig-${slot}.wav`);
      const procPath = await join(dir, `proc-${slot}.wav`);
      const orig = await engineCall<{ lufs: number | null }>("extract",
        { input: loaded.path, output: origPath, region, audio_index: loaded.audioIndex, channels: settings.channels }, { job: phase(`preview-${n}-original`) });
      const proc = await engineCall<JobResult>("enhance",
        { input: loaded.path, output: procPath, region, audio_index: loaded.audioIndex, settings }, { job: phase(`preview-${n}-mejorado`), timeoutS: LONG_TIMEOUT_S });
      setPreview({
        originalUrl: `${convertFileSrc(origPath)}?v=${n}`,
        enhancedUrl: `${convertFileSrc(procPath)}?v=${n}`,
        originalLufs: orig.lufs,
        enhancedLufs: proc.output_lufs,
      });
      setModelInstalled(true);
    });
  };

  // --- Trabajo completo ---
  const processAll = async (asVideo: boolean) => {
    if (!loaded || busyRef.current) return;
    const base = fileName(loaded.path).replace(/\.[^.]+$/, "");
    const target = await save({
      title: asVideo ? es.saveVideoDialogTitle : es.saveDialogTitle,
      defaultPath: asVideo ? `${base}_mejorado.mov` : `${base}_mejorado.${settings.output_format === "flac24" ? "flac" : "wav"}`,
      filters: asVideo ? [{ name: "Video", extensions: ["mov", "mkv", "mp4"] }] : [{ name: "Audio", extensions: [settings.output_format === "flac24" ? "flac" : "wav"] }],
    });
    if (!target || busyRef.current) return;
    setResult(null); setNotice(null);
    const jobKey = `full-${++counter.current}`;
    const res = await runJob("full", jobKey, () =>
      engineCall<JobResult>("enhance", { input: loaded.path, output: target, audio_index: loaded.audioIndex, settings, remux: asVideo },
        { job: jobKey, timeoutS: LONG_TIMEOUT_S }));
    if (res) { setResult(res); setModelInstalled(true); }
  };

  const installModel = async () => {
    const jobKey = `model-${++counter.current}`;
    await runJob("model", jobKey, async () => {
      await engineCall("install_model", {}, { job: jobKey, timeoutS: LONG_TIMEOUT_S });
      setModelInstalled(true);
    });
  };

  const cancel = () => {
    cancelRequested.current = true; // también detiene las fases siguientes de una vista previa
    if (activeJob.current) void cancelJob(activeJob.current);
  };

  const clearCache = async () => {
    await engineCall("clear_cache");
    refreshCache();
  };

  const updateRegion = (a: number, b: number) => loaded && setRegion(clampRegion(a, b, loaded.peaks.duration_s));
  const working = busy !== null;

  return (
    <main>
      <header>
        <h1>{es.appTitle}</h1>
        <p>{es.subtitle}</p>
        <p className="status" role="status">
          {engineStatus}
          {engineOk && providers.length > 0 && <> · {es.accel}: {providers[0].replace("ExecutionProvider", "").replace(/^Cpu$/i, es.accelCpu).replace("Dml", "GPU (DirectML)")}</>}
        </p>
        {engineOk && !showModels && <button type="button" onClick={() => setShowModels(true)} disabled={working}>{es.models}</button>}
      </header>

      {showModels && (
        <ModelsPanel
          onClose={() => setShowModels(false)}
          onChanged={() => {
            refreshCatalog();
            engineCall<{ deepfilternet3: { installed: boolean } }>("models_status").then((m) => setModelInstalled(m.deepfilternet3.installed)).catch(() => undefined);
          }}
        />
      )}

      {modelInstalled === false && (
        <div className="banner" role="note">
          <p>{es.modelMissing}</p>
          <button type="button" onClick={installModel} disabled={working}>
            {busy === "model" ? es.modelInstalling : es.modelInstall}
          </button>
        </div>
      )}
      {error && (
        <div className="banner error" role="alert">
          <p>{error}</p>
          <button type="button" onClick={() => setError(null)}>{es.dismiss}</button>
        </div>
      )}
      {notice && <div className="banner" role="status"><p>{notice}</p></div>}

      <div hidden={showModels}>
      <section className="file">
        <button type="button" className="primary" onClick={chooseFile} disabled={working || !engineOk}>{es.openFile}</button>
        <span className="hint">{es.dropHint}</span>
        {busy === "loading" && <span className="hint">{es.loadingFile}</span>}
      </section>

      {!loaded && engineOk && busy === null && (
        <section className="how" aria-labelledby="how-title">
          <h2 id="how-title">{es.howTitle}</h2>
          <ol>
            {es.steps.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ol>
          <p className="help">{es.privacy}</p>
        </section>
      )}

      {loaded && region && (
        <div className="layout">
          <section className="main-col">
            <h2>{fileName(loaded.path)}</h2>
            <p className="help">
              {es.duration}: {formatTime(loaded.peaks.duration_s)}
              {loaded.probe.audio_streams.length > 1 && " · " + es.trackLabel(loaded.audioIndex, loaded.probe.audio_streams[loaded.audioIndex].channels, loaded.probe.audio_streams[loaded.audioIndex].codec)}
            </p>
            <Waveform peaks={loaded.peaks} region={region} onRegionChange={updateRegion} playhead={playhead !== null ? region[0] + playhead : null} ariaLabel={es.selection} />

            <h3>{es.selection}</h3>
            <p className="help">{es.selectionHelp}</p>
            <div className="row">
              <label>{es.selectionStart}
                <input type="number" min={0} max={loaded.peaks.duration_s} step={0.5} value={Number(region[0].toFixed(2))}
                       onChange={(e) => updateRegion(Number(e.target.value), region[1])} />
              </label>
              <label>{es.selectionEnd}
                <input type="number" min={0} max={loaded.peaks.duration_s} step={0.5} value={Number(region[1].toFixed(2))}
                       onChange={(e) => updateRegion(region[0], Number(e.target.value))} />
              </label>
              <span className="hint">{Math.min(MAX_PREVIEW_S, region[1] - region[0]).toFixed(1)} s</span>
              <button type="button" className="primary" onClick={runPreview} disabled={working}>
                {busy === "preview" ? es.previewRunning : es.previewButton}
              </button>
            </div>

            {preview ? (
              <>
                <ABPlayer {...preview} onTime={setPlayhead} />
                {settings.normalize && <p className="help">{es.previewLoudnessNote}</p>}
              </>
            ) : (
              <p className="help">{es.previewFirstHint}</p>
            )}

            <h3>{es.fullJob}</h3>
            <p className="help">{es.fullJobHelp}</p>
            <div className="row">
              <button type="button" className="primary" onClick={() => processAll(false)} disabled={working}>{es.processAll}</button>
              {loaded.probe.has_video && (
                <button type="button" onClick={() => processAll(true)} disabled={working} title={es.processVideoHelp}>{es.processVideo}</button>
              )}
            </div>
            {loaded.probe.has_video && <p className="help">{es.processVideoHelp}</p>}

            {progress && (
              <div className="progress-row">
                <progress value={progress.value} max={1} aria-label={es.stages[progress.stage] ?? progress.stage} />
                <span>{es.stages[progress.stage] ?? progress.stage} {Math.round(progress.value * 100)} %</span>
                <button type="button" onClick={cancel}>{es.cancel}</button>
              </div>
            )}
            {result && (
              <div className="banner ok" role="status">
                <p><strong>{es.jobDone}</strong> {result.output}</p>
                <p>{es.jobResult(fmtLufs(result.input_lufs), fmtLufs(result.output_lufs))}</p>
                {result.resumed_blocks > 0 && <p>{es.resumed(result.resumed_blocks)}</p>}
                {result.warnings.map((w) => <p key={w} className="warn">{w}</p>)}
              </div>
            )}
          </section>

          <aside className="side-col">
            <SettingsPanel
              settings={settings}
              onChange={setSettings}
              disabled={working}
              customPresets={customPresets}
              onSavePreset={(name) => { const next = upsertPreset(customPresets, name, settings); setCustomPresets(next); saveCustomPresets(next); }}
              models={catalog}
              onDeletePreset={(name) => { const next = customPresets.filter((p) => p.name !== name); setCustomPresets(next); saveCustomPresets(next); }}
            />
          </aside>
        </div>
      )}

      {engineOk && cacheBytes !== null && cacheBytes > 0 && (
        <footer className="cache">
          <span className="hint">{es.cacheLabel(cacheBytes)}</span>
          <button type="button" onClick={clearCache} disabled={working} title={es.clearCacheHelp}>{es.clearCache}</button>
        </footer>
      )}
      </div>
    </main>
  );
}
