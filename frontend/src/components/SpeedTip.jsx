import React, { useState } from "react";
import Icon from "./Icons.jsx";

// Smaller chat models that answer 2-4x faster on a CPU-only computer, best first.
const FAST_MODELS = ["llama3.2:1b", "qwen2.5:1.5b", "gemma3:1b", "qwen2.5:0.5b", "llama3.2:1b-instruct-q4_K_M"];

function sizeB(m) {
  const n = parseFloat(String(m?.parameter_size || "").replace(/[^0-9.]/g, ""));
  if (!n) return null;
  return /m/i.test(m.parameter_size) ? n / 1000 : n;
}

function load(key) {
  try { return JSON.parse(localStorage.getItem(key) || "null"); } catch { return null; }
}

/**
 * Shown above the question box when this computer runs the current model too
 * slowly for full answers: suggests (or switches to) a smaller, faster model.
 */
export default function SpeedTip({ health, models, model, onUseModel }) {
  const current = model || health?.default_model || "";
  const info = health?.speed?.models?.[current];
  const [hidden, setHidden] = useState(() => load("lm.speedTipHidden") === current);
  if (!info || !info.slow || hidden) return null;

  const currentSize = sizeB(models.find((m) => m.name === current)) || 3;
  const installed = models
    .filter((m) => m.name !== current && (sizeB(m) ?? 99) < currentSize * 0.7)
    .sort((a, b) => {
      const ia = FAST_MODELS.indexOf(a.name);
      const ib = FAST_MODELS.indexOf(b.name);
      return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib) || (sizeB(b) || 0) - (sizeB(a) || 0);
    });
  const best = installed[0];

  return (
    <div className="speed-tip" role="status">
      <span className="speed-icon"><Icon name="bolt" size={15} /></span>
      <span className="speed-text">
        <b>{current}</b> writes about <b>{info.words_per_second} words/s</b> on this computer, so a full answer takes
        about {info.answer_seconds} s.{" "}
        {best ? (
          <>A smaller model writes 2–3× faster.</>
        ) : (
          <>For 2–3× faster answers run <code>ollama pull llama3.2:1b</code> and pick it in the model menu.</>
        )}
      </span>
      {best && (
        <button type="button" className="speed-btn" onClick={() => onUseModel(best.name)}>
          Use {best.name}
        </button>
      )}
      <button
        type="button"
        className="ghost-icon"
        aria-label="Hide tip"
        onClick={() => {
          setHidden(true);
          try { localStorage.setItem("lm.speedTipHidden", JSON.stringify(current)); } catch { /* ignore */ }
        }}
      >
        <Icon name="close" size={14} />
      </button>
    </div>
  );
}
