import { defaultParamsFor, formatParam, modelOf, stageName, stageSchema, type ParamSpec, type StageCatalog } from "../catalog";
import { es } from "../i18n/es";
import type { ParamValue, Settings, Stage } from "../settings";
import type { BoxId } from "./ChainEditor";

interface Props {
  selectedId: BoxId;
  settings: Settings;
  catalog: StageCatalog;
  fileLabel: string | null;
  onChange: (next: Settings) => void;
  onGoModels: () => void;
  disabled?: boolean;
}

const TARGETS = [
  { value: -16, label: es.targetWeb },
  { value: -23, label: es.targetTv },
];

function ParamControl({ id, spec, value, onChange }: { id: string; spec: ParamSpec; value: ParamValue; onChange: (v: ParamValue) => void }) {
  const fieldId = `${id}-${spec.id}`;
  const helpId = `${fieldId}-help`;
  if (spec.type === "choice") {
    return (
      <div className="field">
        <label htmlFor={fieldId}>{spec.label}</label>
        <select id={fieldId} aria-describedby={helpId} value={String(value)}
                onChange={(e) => onChange(spec.options?.find((o) => String(o.value) === e.target.value)?.value ?? spec.default)}>
          {spec.options?.map((o) => <option key={String(o.value)} value={String(o.value)}>{o.label}</option>)}
        </select>
        <p id={helpId} className="help">{spec.help}</p>
      </div>
    );
  }
  const scale = spec.unit === "%" ? 100 : 1;
  return (
    <div className="field">
      <label htmlFor={fieldId}>{spec.label}: {formatParam(spec, value)}</label>
      <input id={fieldId} aria-describedby={helpId} type="range" min={(spec.min ?? 0) * scale} max={(spec.max ?? 1) * scale}
             step={(spec.step ?? 1) * scale} value={Number(value) * scale}
             onChange={(e) => onChange(Number(e.target.value) / scale)} />
      <p id={helpId} className="help">{spec.help}</p>
    </div>
  );
}

/** Configuración de la caja seleccionada, generada desde su esquema de parámetros (con «Restablecer»). */
export function StageSettings({ selectedId, settings, catalog, fileLabel, onChange, onGoModels, disabled }: Props) {
  const set = <K extends keyof Settings>(key: K, value: Settings[K]) => onChange({ ...settings, [key]: value });
  const stage = settings.chain.find((s) => s.id === selectedId) ?? null;

  if (selectedId === "input") {
    return (
      <fieldset className="stage-settings" disabled={disabled}>
        <legend>{es.stageSettingsTitle(es.boxInput)}</legend>
        <p className="help">{es.inputInfo}</p>
        <p>{fileLabel ?? es.inputNone}</p>
      </fieldset>
    );
  }

  if (selectedId === "volume") {
    const isPresetTarget = TARGETS.some((t) => t.value === settings.target_lufs);
    return (
      <fieldset className="stage-settings" disabled={disabled}>
        <legend>{es.stageSettingsTitle(es.boxVolume)}</legend>
        <p className="help">{es.volumeInfo}</p>
        <div className="field">
          <label className="check">
            <input type="checkbox" checked={settings.normalize} onChange={(e) => set("normalize", e.target.checked)} />
            {es.normalize}
          </label>
          <p className="help">{es.normalizeHelp}</p>
        </div>
        {settings.normalize && (
          <>
            <div className="field">
              <label htmlFor="target">{es.target}</label>
              <select id="target" value={isPresetTarget ? String(settings.target_lufs) : "custom"}
                      onChange={(e) => e.target.value !== "custom" && set("target_lufs", Number(e.target.value))}>
                {TARGETS.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
                {!isPresetTarget && <option value="custom">{`${es.targetCustom}: ${settings.target_lufs} LUFS`}</option>}
              </select>
            </div>
            <div className="field">
              <label htmlFor="peak">{es.truePeak}: {settings.max_true_peak_db} dB</label>
              <input id="peak" type="range" min={-6} max={0} step={0.5} value={settings.max_true_peak_db}
                     onChange={(e) => set("max_true_peak_db", Number(e.target.value))} />
              <p className="help">{es.truePeakHelp}</p>
            </div>
          </>
        )}
      </fieldset>
    );
  }

  if (selectedId === "output") {
    return (
      <fieldset className="stage-settings" disabled={disabled}>
        <legend>{es.stageSettingsTitle(es.boxOutput)}</legend>
        <p className="help">{es.outputInfo}</p>
        <div className="field">
          <label htmlFor="channels">{es.channels}</label>
          <select id="channels" value={settings.channels} onChange={(e) => set("channels", e.target.value as Settings["channels"])}>
            <option value="each">{es.channelsEach}</option>
            <option value="mix">{es.channelsMix}</option>
          </select>
          <p className="help">{es.channelsHelp}</p>
        </div>
        <div className="field">
          <label htmlFor="format">{es.format}</label>
          <select id="format" value={settings.output_format} onChange={(e) => set("output_format", e.target.value as Settings["output_format"])}>
            <option value="wav24">{es.formatWav}</option>
            <option value="flac24">{es.formatFlac}</option>
          </select>
        </div>
      </fieldset>
    );
  }

  if (!stage) return null;
  const schema = stageSchema(stage, catalog);
  const model = modelOf(stage, catalog);
  const update = (patch: Partial<Stage>) => onChange({ ...settings, chain: settings.chain.map((s) => (s.id === stage.id ? { ...s, ...patch } : s)) });
  const name = stageName(stage, catalog);

  return (
    <fieldset className="stage-settings" disabled={disabled}>
      <legend>{es.stageSettingsTitle(name)}</legend>
      {model && <p className="help">{model.description}</p>}
      {model && !model.verified_license && <p className="warn">{es.modelUnverifiedWarning}</p>}
      {stage.kind === "model" && (!model || model.status !== "installed") && (
        <div className="banner warn" role="note">
          <p>{es.stageMissingModel}</p>
          <button type="button" onClick={onGoModels}>{es.goToModels}</button>
        </div>
      )}
      <label className="check">
        <input type="checkbox" checked={stage.enabled} onChange={(e) => update({ enabled: e.target.checked })} />
        {es.enableBox}
      </label>
      {schema.map((spec) => (
        <ParamControl key={spec.id} id={stage.id} spec={spec} value={stage.params[spec.id] ?? spec.default}
                      onChange={(v) => update({ params: { ...stage.params, [spec.id]: v } })} />
      ))}
      {stage.kind === "model" && schema.length === 1 && <p className="hint">{es.modelNoParams}</p>}
      <button type="button" onClick={() => update({ params: defaultParamsFor(schema) })}>{es.resetStage}</button>
    </fieldset>
  );
}
