import { useState } from "react";
import { es } from "../i18n/es";
import { BUILTIN_PRESETS, type CustomPreset } from "../presets";
import type { Settings } from "../settings";
import type { ModelInfo } from "./ModelsPanel";

interface Props {
  settings: Settings;
  onChange: (next: Settings) => void;
  customPresets: CustomPreset[];
  onSavePreset: (name: string) => void;
  onDeletePreset: (name: string) => void;
  disabled?: boolean;
  /** Catálogo de modelos (opcional): habilita la etapa de aislar voz con los modelos instalados. */
  models?: ModelInfo[];
}

const TARGETS = [
  { value: -16, label: es.targetWeb },
  { value: -23, label: es.targetTv },
];

export function SettingsPanel({ settings, onChange, customPresets, onSavePreset, onDeletePreset, disabled, models = [] }: Props) {
  const [presetValue, setPresetValue] = useState("builtin:default");
  const [newName, setNewName] = useState("");
  const set = <K extends keyof Settings>(key: K, value: Settings[K]) => onChange({ ...settings, [key]: value });

  const applyPreset = (value: string) => {
    setPresetValue(value);
    if (value.startsWith("builtin:")) {
      const preset = BUILTIN_PRESETS.find((p) => `builtin:${p.id}` === value);
      if (preset) onChange(preset.settings);
    } else {
      const custom = customPresets.find((p) => `custom:${p.name}` === value);
      if (custom) onChange(custom.settings);
    }
  };
  const builtinId = presetValue.startsWith("builtin:") ? presetValue.slice(8) : null;
  const isPresetTarget = TARGETS.some((t) => t.value === settings.target_lufs);

  return (
    <fieldset className="settings" disabled={disabled}>
      <legend>{es.settings}</legend>

      <div className="field">
        <label htmlFor="preset">{es.preset}</label>
        <select id="preset" value={presetValue} onChange={(e) => applyPreset(e.target.value)}>
          <optgroup label={es.builtinPresets}>
            {BUILTIN_PRESETS.map((p) => (
              <option key={p.id} value={`builtin:${p.id}`}>
                {es.presets[p.id]?.name ?? p.id}
              </option>
            ))}
          </optgroup>
          {customPresets.length > 0 && (
            <optgroup label={es.customPresets}>
              {customPresets.map((p) => (
                <option key={p.name} value={`custom:${p.name}`}>
                  {p.name}
                </option>
              ))}
            </optgroup>
          )}
        </select>
        <p className="help">{builtinId ? es.presets[builtinId]?.description : es.presetHelp}</p>
        <div className="row">
          <input
            aria-label={es.presetNamePrompt}
            placeholder={es.presetNamePrompt}
            value={newName}
            maxLength={60}
            onChange={(e) => setNewName(e.target.value)}
          />
          <button type="button" disabled={!newName.trim()} onClick={() => { onSavePreset(newName); setNewName(""); }}>
            {es.savePreset}
          </button>
          {presetValue.startsWith("custom:") && (
            <button type="button" onClick={() => { onDeletePreset(presetValue.slice(7)); setPresetValue("builtin:default"); }}>
              {es.deletePreset}
            </button>
          )}
        </div>
      </div>

      {models.some((m) => m.task === "separate" || m.task === "unknown") && (
        <div className="field">
          <label htmlFor="separate">{es.separateStage}</label>
          <select
            id="separate"
            value={settings.separate_model ?? ""}
            onChange={(e) => set("separate_model", e.target.value === "" ? null : e.target.value)}
          >
            <option value="">{es.separateNone}</option>
            {models
              .filter((m) => (m.task === "separate" || m.task === "unknown") && (m.status === "installed" || m.id === settings.separate_model))
              .map((m) => (
                <option key={m.id} value={m.id}>{m.name}</option>
              ))}
          </select>
          <p className="help">{es.separateHelp}</p>
          {!models.some((m) => (m.task === "separate" || m.task === "unknown") && m.status === "installed") && (
            <p className="help">{es.separateNeedsInstall}</p>
          )}
          {settings.separate_model && models.find((m) => m.id === settings.separate_model)?.status !== "installed" && (
            <p className="warn">{es.separateMissingNote}</p>
          )}
          {settings.separate_model && (
            <>
              <label htmlFor="separate-strength">
                {es.separateStrength}: {Math.round(settings.separate_strength * 100)} %
              </label>
              <input
                id="separate-strength"
                type="range"
                min={0}
                max={100}
                step={5}
                value={Math.round(settings.separate_strength * 100)}
                onChange={(e) => set("separate_strength", Number(e.target.value) / 100)}
              />
            </>
          )}
        </div>
      )}

      <div className="field">
        <label className="check">
          <input type="checkbox" checked={settings.denoise} onChange={(e) => set("denoise", e.target.checked)} />
          {es.denoise}
        </label>
        <p className="help">{es.denoiseHelp}</p>
        {settings.denoise && (
          <>
            <label htmlFor="strength">
              {es.denoiseStrength}: {Math.round(settings.denoise_strength * 100)} %
            </label>
            <input
              id="strength"
              type="range"
              min={0}
              max={100}
              step={5}
              value={Math.round(settings.denoise_strength * 100)}
              onChange={(e) => set("denoise_strength", Number(e.target.value) / 100)}
            />
            <p className="help">{es.denoiseStrengthHelp}</p>
          </>
        )}
      </div>

      <div className="field">
        <label htmlFor="highpass">{es.highpass}</label>
        <select
          id="highpass"
          value={settings.highpass_hz === null ? "off" : String(settings.highpass_hz)}
          onChange={(e) => set("highpass_hz", e.target.value === "off" ? null : Number(e.target.value))}
        >
          <option value="off">{es.off}</option>
          {[60, 80, 100, 120, 150].map((hz) => (
            <option key={hz} value={hz}>{`${hz} ${es.hz}`}</option>
          ))}
          {settings.highpass_hz !== null && ![60, 80, 100, 120, 150].includes(settings.highpass_hz) && (
            <option value={settings.highpass_hz}>{`${settings.highpass_hz} ${es.hz}`}</option>
          )}
        </select>
        <p className="help">{es.highpassHelp}</p>
      </div>

      <div className="field">
        <label htmlFor="notch">{es.notch}</label>
        <select
          id="notch"
          value={settings.notch_hz === null ? "off" : String(settings.notch_hz)}
          onChange={(e) => set("notch_hz", e.target.value === "off" ? null : (Number(e.target.value) as 50 | 60))}
        >
          <option value="off">{es.off}</option>
          <option value="50">50 Hz</option>
          <option value="60">60 Hz</option>
        </select>
        <p className="help">{es.notchHelp}</p>
      </div>

      <div className="field">
        <label className="check">
          <input type="checkbox" checked={settings.normalize} onChange={(e) => set("normalize", e.target.checked)} />
          {es.normalize}
        </label>
        <p className="help">{es.normalizeHelp}</p>
        {settings.normalize && (
          <>
            <label htmlFor="target">{es.target}</label>
            <select
              id="target"
              value={isPresetTarget ? String(settings.target_lufs) : "custom"}
              onChange={(e) => e.target.value !== "custom" && set("target_lufs", Number(e.target.value))}
            >
              {TARGETS.map((t) => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
              {!isPresetTarget && <option value="custom">{`${es.targetCustom}: ${settings.target_lufs} LUFS`}</option>}
            </select>
            <label htmlFor="peak">{es.truePeak}: {settings.max_true_peak_db} dB</label>
            <input id="peak" type="range" min={-6} max={0} step={0.5} value={settings.max_true_peak_db}
                   onChange={(e) => set("max_true_peak_db", Number(e.target.value))} />
            <p className="help">{es.truePeakHelp}</p>
          </>
        )}
      </div>

      <div className="field">
        <label htmlFor="channels">{es.channels}</label>
        <select id="channels" value={settings.channels} onChange={(e) => set("channels", e.target.value as Settings["channels"])}>
          <option value="each">{es.channelsEach}</option>
          <option value="mix">{es.channelsMix}</option>
        </select>
        <p className="help">{es.channelsHelp}</p>
        <label htmlFor="format">{es.format}</label>
        <select id="format" value={settings.output_format} onChange={(e) => set("output_format", e.target.value as Settings["output_format"])}>
          <option value="wav24">{es.formatWav}</option>
          <option value="flac24">{es.formatFlac}</option>
        </select>
      </div>
    </fieldset>
  );
}
