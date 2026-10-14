import React from "react";
import Icon from "./Icons.jsx";
import { ACCENTS, DEFAULT_THEME, GRADIENTS, resolvedMode, themeVars } from "../theme.js";

const MODES = [
  { id: "light", label: "Light", icon: "sun" },
  { id: "dark", label: "Dark", icon: "moon" },
  { id: "system", label: "System", icon: "laptop" },
];
const CUSTOM_FIELDS = [
  { key: "bg", label: "Background" },
  { key: "side", label: "Sidebar" },
  { key: "userBubble", label: "Your messages" },
  { key: "aiBubble", label: "AI messages" },
  { key: "line", label: "Borders" },
];

function ColorField({ label, value, fallback, onChange, onClear }) {
  return (
    <label className="color-field">
      <input type="color" value={value || fallback} onChange={(e) => onChange(e.target.value)} aria-label={label} />
      <span>{label}</span>
      {value ? (
        <button type="button" className="link-btn" onClick={onClear} title="Back to default">Reset</button>
      ) : (
        <span className="muted small">default</span>
      )}
    </label>
  );
}

/** Appearance: mode, accent palette, gradients, custom colours, density. */
export default function ThemePanel({ theme, onChange, onClose, warnings }) {
  const mode = resolvedMode(theme);
  const custom = theme.custom?.[mode] || {};
  const { vars } = themeVars(theme);
  const set = (patch) => onChange({ ...theme, ...patch });
  const setCustom = (key, value) => {
    const next = { ...custom };
    if (value) next[key] = value;
    else delete next[key];
    onChange({ ...theme, custom: { ...theme.custom, [mode]: next } });
  };

  return (
    <div className="modal-scrim" role="dialog" aria-modal="true" aria-label="Appearance" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal theme-modal">
        <header className="theme-head">
          <Icon name="palette" size={18} />
          <h3>Appearance</h3>
          <span className="spacer" />
          <button type="button" className="ghost-icon" onClick={onClose} aria-label="Close"><Icon name="close" /></button>
        </header>

        <section>
          <h4>Mode</h4>
          <div className="seg wide" role="radiogroup" aria-label="Colour mode">
            {MODES.map((m) => (
              <button key={m.id} type="button" role="radio" aria-checked={theme.mode === m.id} className={theme.mode === m.id ? "on" : ""} onClick={() => set({ mode: m.id })}>
                <Icon name={m.icon} size={14} /> {m.label}
              </button>
            ))}
          </div>
        </section>

        <section>
          <h4>Accent colour</h4>
          <div className="swatches" role="radiogroup" aria-label="Accent colour">
            {ACCENTS.map((a) => (
              <button
                key={a.id}
                type="button"
                role="radio"
                aria-checked={theme.accent === a.id}
                className={`swatch ${theme.accent === a.id ? "on" : ""}`}
                style={{ "--sw": a[mode] }}
                onClick={() => set({ accent: a.id })}
                title={a.label}
              >
                <span className="sr-only">{a.label}</span>
              </button>
            ))}
            <label className={`swatch custom ${theme.accent === "custom" ? "on" : ""}`} title="Custom colour" style={{ "--sw": theme.customAccent }}>
              <input type="color" value={theme.customAccent} onChange={(e) => set({ accent: "custom", customAccent: e.target.value })} aria-label="Custom accent colour" />
              <Icon name="plus" size={14} />
            </label>
          </div>
          <div className="color-row">
            <ColorField label="Secondary accent" value={theme.secondary} fallback={vars["--acc-2"]} onChange={(v) => set({ secondary: v })} onClear={() => set({ secondary: "" })} />
          </div>
        </section>

        <section>
          <h4>Gradient</h4>
          <div className="grad-row" role="radiogroup" aria-label="Gradient">
            {GRADIENTS.map((g) => (
              <button
                key={g.id}
                type="button"
                role="radio"
                aria-checked={theme.gradient === g.id}
                className={`grad ${theme.gradient === g.id ? "on" : ""}`}
                style={{ "--g": g.stops ? `linear-gradient(135deg, ${g.stops[0]}, ${g.stops[1]})` : "var(--surface-2)" }}
                onClick={() => set({ gradient: g.id })}
              >
                <span>{g.label}</span>
              </button>
            ))}
          </div>
        </section>

        <section>
          <h4>Colours for {mode} mode</h4>
          <div className="color-grid">
            {CUSTOM_FIELDS.map((f) => (
              <ColorField
                key={f.key}
                label={f.label}
                value={custom[f.key]}
                fallback={f.key === "aiBubble" ? vars["--bg"] : vars[{ bg: "--bg", side: "--side", userBubble: "--user-bubble", line: "--line" }[f.key]] || "#888888"}
                onChange={(v) => setCustom(f.key, v)}
                onClear={() => setCustom(f.key, "")}
              />
            ))}
          </div>
        </section>

        <section>
          <h4>Chat spacing</h4>
          <div className="seg wide" role="radiogroup" aria-label="Chat spacing">
            {["comfortable", "compact"].map((d) => (
              <button key={d} type="button" role="radio" aria-checked={theme.density === d} className={theme.density === d ? "on" : ""} onClick={() => set({ density: d })}>
                {d === "compact" ? "Compact" : "Comfortable"}
              </button>
            ))}
          </div>
        </section>

        {warnings?.length > 0 && (
          <ul className="contrast-notes" aria-live="polite">
            {warnings.map((w) => <li key={w}><Icon name="check" size={13} /> {w}</li>)}
          </ul>
        )}

        <footer className="modal-actions">
          <span className="muted small">Saved on this device and in Lumina – no restart needed.</span>
          <span className="spacer" />
          <button type="button" className="mini-btn" onClick={() => onChange({ ...DEFAULT_THEME, custom: { light: {}, dark: {} } })}>Reset all</button>
          <button type="button" className="mini-btn primary" onClick={onClose}>Done</button>
        </footer>
      </div>
    </div>
  );
}
