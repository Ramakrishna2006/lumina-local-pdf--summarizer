// Theme engine – turns a few user choices into CSS custom properties.
// Text colours are checked against WCAG contrast (4.5 : 1 for normal text)
// and adjusted automatically, so every colour combination stays readable.

export const ACCENTS = [
  { id: "indigo", label: "Indigo", light: "#4f46e5", dark: "#8b87ff" },
  { id: "blue", label: "Blue", light: "#2563eb", dark: "#60a5fa" },
  { id: "purple", label: "Purple", light: "#7c3aed", dark: "#a78bfa" },
  { id: "green", label: "Green", light: "#16a34a", dark: "#4ade80" },
  { id: "teal", label: "Teal", light: "#0d9488", dark: "#2dd4bf" },
  { id: "orange", label: "Orange", light: "#ea580c", dark: "#fb923c" },
  { id: "red", label: "Red", light: "#dc2626", dark: "#f87171" },
  { id: "pink", label: "Pink", light: "#db2777", dark: "#f472b6" },
  { id: "yellow", label: "Yellow", light: "#ca8a04", dark: "#facc15" },
];

export const GRADIENTS = [
  { id: "none", label: "None", stops: null },
  { id: "aurora", label: "Aurora", stops: ["#6366f1", "#06b6d4"] },
  { id: "sunset", label: "Sunset", stops: ["#f97316", "#db2777"] },
  { id: "ocean", label: "Ocean", stops: ["#2563eb", "#14b8a6"] },
  { id: "forest", label: "Forest", stops: ["#16a34a", "#ca8a04"] },
  { id: "berry", label: "Berry", stops: ["#7c3aed", "#ec4899"] },
];

export const DEFAULT_THEME = {
  mode: "system",          // light | dark | system
  accent: "indigo",        // palette id or "custom"
  customAccent: "#4f46e5",
  secondary: "",           // optional second accent (hex) – used in gradients and highlights
  gradient: "none",
  density: "comfortable",  // comfortable | compact
  custom: { light: {}, dark: {} }, // optional overrides: bg, side, userBubble, aiBubble, line
};

// ------------------------------------------------------------------ colour maths
export function hexToRgb(hex) {
  const m = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(String(hex || "").trim());
  if (!m) return null;
  let h = m[1];
  if (h.length === 3) h = h.split("").map((c) => c + c).join("");
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}

export function rgbToHex([r, g, b]) {
  return "#" + [r, g, b].map((v) => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, "0")).join("");
}

function luminance(hex) {
  const rgb = hexToRgb(hex);
  if (!rgb) return 0;
  const [r, g, b] = rgb.map((v) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function contrast(a, b) {
  const [l1, l2] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (l1 + 0.05) / (l2 + 0.05);
}

export function mix(a, b, amount) {
  const x = hexToRgb(a);
  const y = hexToRgb(b);
  if (!x || !y) return a;
  return rgbToHex(x.map((v, i) => v + (y[i] - v) * amount));
}

function rgba(hex, alpha) {
  const rgb = hexToRgb(hex) || [79, 70, 229];
  return `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, ${alpha})`;
}

/** Move `fg` towards black or white until it reaches `target` contrast on `bg`. */
export function ensureContrast(fg, bg, target = 4.5) {
  if (contrast(fg, bg) >= target) return fg;
  const towards = luminance(bg) > 0.4 ? "#000000" : "#ffffff";
  for (let i = 1; i <= 20; i++) {
    const c = mix(fg, towards, i / 20);
    if (contrast(c, bg) >= target) return c;
  }
  return towards;
}

// ------------------------------------------------------------------ resolve + apply
export function resolvedMode(theme) {
  if (theme.mode === "light" || theme.mode === "dark") return theme.mode;
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

const BASE = {
  light: { bg: "#ffffff", side: "#f7f7f8", tx: "#111113", userBubble: "#f1f1f3", line: "#e6e6e8", surface: "#ffffff" },
  dark: { bg: "#161618", side: "#0f0f11", tx: "#ededef", userBubble: "#26262b", line: "#2a2a2f", surface: "#1e1e21" },
};

export function accentColor(theme, mode) {
  if (theme.accent === "custom") return hexToRgb(theme.customAccent) ? theme.customAccent : "#4f46e5";
  const a = ACCENTS.find((x) => x.id === theme.accent) || ACCENTS[0];
  return a[mode];
}

/** CSS variables for a theme + a list of readability warnings. */
export function themeVars(theme) {
  const mode = resolvedMode(theme);
  const base = BASE[mode];
  const over = (theme.custom && theme.custom[mode]) || {};
  const bg = hexToRgb(over.bg) ? over.bg : base.bg;
  const side = hexToRgb(over.side) ? over.side : base.side;
  const userBubble = hexToRgb(over.userBubble) ? over.userBubble : base.userBubble;
  const aiBubble = hexToRgb(over.aiBubble) ? over.aiBubble : "";
  const line = hexToRgb(over.line) ? over.line : base.line;
  let acc = accentColor(theme, mode);
  const warnings = [];

  // Readable text on every custom surface.
  const tx = ensureContrast(base.tx, bg, 7);
  const accText = ensureContrast(acc, bg, 4.5);
  if (accText.toLowerCase() !== acc.toLowerCase()) warnings.push("Accent was darkened/lightened a little so links stay readable on your background.");
  const onAcc = contrast("#ffffff", acc) >= contrast("#0f0f11", acc) ? "#ffffff" : "#0f0f11";
  if (contrast(onAcc, acc) < 4.5) {
    acc = ensureContrast(acc, onAcc, 4.5);
    warnings.push("Button colour adjusted so the text on it stays readable.");
  }
  const bubbleText = ensureContrast(tx, userBubble, 4.5);
  if (bubbleText !== tx) warnings.push("Message bubble text colour adjusted for contrast.");
  if (contrast(tx, side) < 4.5) warnings.push("Sidebar colour is very close to the text colour.");

  const second = hexToRgb(theme.secondary) ? theme.secondary : null;
  const grad = GRADIENTS.find((g) => g.id === theme.gradient);
  const stops = grad?.stops || (second ? [acc, second] : null);

  // Text on gradient buttons must be readable on BOTH ends of the gradient.
  const onGrad = stops
    ? ["#ffffff", "#0f0f11"].sort((a, b) => Math.min(contrast(b, stops[0]), contrast(b, stops[1])) - Math.min(contrast(a, stops[0]), contrast(a, stops[1])))[0]
    : onAcc;

  const vars = {
    "--bg": bg,
    "--side": side,
    "--tx": tx,
    "--line": line,
    "--acc": acc,
    "--acc-hover": mix(acc, mode === "dark" ? "#ffffff" : "#000000", 0.14),
    "--acc-soft": rgba(acc, mode === "dark" ? 0.14 : 0.1),
    "--acc-line": rgba(acc, 0.32),
    "--acc-text": accText,
    "--on-acc": onAcc,
    "--acc-2": second || mix(acc, mode === "dark" ? "#ffffff" : "#000000", 0.25),
    "--user-bubble": userBubble,
    "--user-bubble-tx": bubbleText,
    "--ai-bubble": aiBubble || "transparent",
    "--ai-bubble-pad": aiBubble ? "12px 16px" : "0",
    "--grad": stops ? `linear-gradient(135deg, ${stops[0]}, ${stops[1]})` : acc,
    "--on-grad": onGrad,
  };
  if (over.bg) {
    vars["--surface"] = mix(bg, mode === "dark" ? "#ffffff" : "#000000", 0.04);
    vars["--surface-2"] = mix(bg, mode === "dark" ? "#ffffff" : "#000000", 0.06);
    vars["--surface-3"] = mix(bg, mode === "dark" ? "#ffffff" : "#000000", 0.1);
  }
  return { mode, vars, warnings, hasGradient: Boolean(stops) };
}

const APPLIED = new Set();

export function applyTheme(theme) {
  const root = document.documentElement;
  const { mode, vars, warnings, hasGradient } = themeVars(theme);
  root.dataset.theme = mode;
  root.dataset.density = theme.density === "compact" ? "compact" : "comfortable";
  root.dataset.gradient = hasGradient ? "on" : "off";
  for (const key of APPLIED) if (!(key in vars)) root.style.removeProperty(key);
  APPLIED.clear();
  for (const [key, value] of Object.entries(vars)) {
    root.style.setProperty(key, value);
    APPLIED.add(key);
  }
  return warnings;
}

export function normalizeTheme(raw) {
  const t = { ...DEFAULT_THEME, ...(raw && typeof raw === "object" ? raw : {}) };
  t.custom = { light: { ...(t.custom?.light || {}) }, dark: { ...(t.custom?.dark || {}) } };
  if (!["light", "dark", "system"].includes(t.mode)) t.mode = "system";
  return t;
}
