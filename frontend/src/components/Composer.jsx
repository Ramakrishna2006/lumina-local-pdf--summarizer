import React, { useEffect, useRef } from "react";
import Icon from "./Icons.jsx";

export default function Composer({
  value,
  onChange,
  onSend,
  onStop,
  onAttach,
  sending,
  mode,
  onModeChange,
  style,
  styles,
  onStyleChange,
  disabledReason,
  selectedCount,
  inputRef,
  centered = false,
}) {
  const localRef = useRef(null);
  const ref = inputRef || localRef;

  // Grow the text box with its content (up to 220 px).
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 220)}px`;
  }, [value, ref]);

  const disabled = Boolean(disabledReason);
  const placeholder =
    mode === "web"
      ? "Ask anything – Lumina will search the web"
      : mode === "image"
        ? "Describe the image you want – e.g. a watercolor lighthouse at sunset"
        : disabledReason || (selectedCount > 1 ? `Ask anything about these ${selectedCount} documents` : "How can I help with your document?");

  return (
    <div className={`composer-wrap ${centered ? "is-centered" : ""}`}>
      <div className={`composer ${sending ? "is-sending" : ""}`}>
        <textarea
          ref={ref}
          rows={centered ? 2 : 1}
          value={value}
          placeholder={placeholder}
          disabled={disabled && !sending}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              if (!sending) onSend();
            }
          }}
          aria-label="Your question"
        />
        <div className="composer-bar">
          <button type="button" className="tool round" onClick={onAttach} title="Add files" aria-label="Add files">
            <Icon name="plus" size={17} />
          </button>
          <div className="seg" role="radiogroup" aria-label="Answer source">
            <button type="button" role="radio" aria-checked={mode === "ai"} className={mode === "ai" ? "on" : ""} onClick={() => onModeChange("ai")}>
              <Icon name="doc" size={14} /> <span>Documents</span>
            </button>
            <button type="button" role="radio" aria-checked={mode === "web"} className={mode === "web" ? "on" : ""} onClick={() => onModeChange("web")}>
              <Icon name="globe" size={14} /> <span>Web</span>
            </button>
            <button type="button" role="radio" aria-checked={mode === "image"} className={mode === "image" ? "on" : ""} onClick={() => onModeChange("image")}>
              <Icon name="image" size={14} /> <span>Image</span>
            </button>
          </div>
          <span className="spacer" />
          {mode === "ai" && (
            <label className="style-select" title="Answer style">
              <span className="sr-only">Answer style</span>
              <select value={style} onChange={(e) => onStyleChange(e.target.value)}>
                {styles.map((s) => (
                  <option key={s.id} value={s.id}>{s.label}</option>
                ))}
              </select>
              <Icon name="chevron" size={14} />
            </label>
          )}
          {sending ? (
            <button type="button" className="send is-stop" onClick={onStop} aria-label="Stop generating" title="Stop">
              <Icon name="stop" size={14} />
            </button>
          ) : (
            <button type="button" className="send" onClick={onSend} disabled={disabled || !value.trim()} aria-label="Send">
              <Icon name="send" size={17} />
            </button>
          )}
        </div>
      </div>
      {!centered && (
        <p className="foot">
          {mode === "web"
            ? "Web mode sends your question to public search sites · your files stay on this computer"
            : mode === "image"
              ? "Images are painted on your computer · nothing is sent online"
              : "Lumina runs on your computer · your documents never leave it"}
        </p>
      )}
    </div>
  );
}
