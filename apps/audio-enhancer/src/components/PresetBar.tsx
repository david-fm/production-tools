import { useState } from "react";
import { es } from "../i18n/es";
import { BUILTIN_PRESETS, type CustomPreset } from "../presets";
import type { Settings } from "../settings";

interface Props {
  settings: Settings;
  onApply: (next: Settings) => void;
  customPresets: CustomPreset[];
  onSavePreset: (name: string) => void;
  onDeletePreset: (name: string) => void;
  disabled?: boolean;
}

/** Preajustes = cadena completa + volumen y salida. Aplicar uno reemplaza la cadena actual. */
export function PresetBar({ settings: _settings, onApply, customPresets, onSavePreset, onDeletePreset, disabled }: Props) {
  const [value, setValue] = useState("builtin:default");
  const [newName, setNewName] = useState("");

  const apply = (v: string) => {
    setValue(v);
    if (v.startsWith("builtin:")) onApply(BUILTIN_PRESETS.find((p) => `builtin:${p.id}` === v)!.build());
    else {
      const c = customPresets.find((p) => `custom:${p.name}` === v);
      if (c) onApply(structuredClone(c.settings));
    }
  };
  const builtinId = value.startsWith("builtin:") ? value.slice(8) : null;

  return (
    <fieldset className="presets" disabled={disabled}>
      <legend>{es.preset}</legend>
      <div className="row">
        <label>
          <span className="sr-only">{es.preset}</span>
          <select value={value} onChange={(e) => apply(e.target.value)}>
            <optgroup label={es.builtinPresets}>
              {BUILTIN_PRESETS.map((p) => <option key={p.id} value={`builtin:${p.id}`}>{es.presets[p.id]?.name ?? p.id}</option>)}
            </optgroup>
            {customPresets.length > 0 && (
              <optgroup label={es.customPresets}>
                {customPresets.map((p) => <option key={p.name} value={`custom:${p.name}`}>{p.name}</option>)}
              </optgroup>
            )}
          </select>
        </label>
        {value.startsWith("custom:") && (
          <button type="button" onClick={() => { onDeletePreset(value.slice(7)); setValue("builtin:default"); }}>{es.deletePreset}</button>
        )}
      </div>
      <p className="help">{builtinId ? es.presets[builtinId]?.description : es.presetHelp}</p>
      <div className="row">
        <input aria-label={es.presetNamePrompt} placeholder={es.presetNamePrompt} value={newName} maxLength={60} onChange={(e) => setNewName(e.target.value)} />
        <button type="button" disabled={!newName.trim()} onClick={() => { onSavePreset(newName); setNewName(""); }}>{es.savePreset}</button>
      </div>
    </fieldset>
  );
}
