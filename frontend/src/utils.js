export function formatBytes(bytes = 0) {
  if (!bytes) return "0 KB";
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** i).toFixed(i ? 1 : 0)} ${units[i]}`;
}

export function relativeTime(value) {
  if (!value) return "";
  const date = new Date(value.endsWith?.("Z") || /[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`);
  const diff = (Date.now() - date.getTime()) / 1000;
  if (Number.isNaN(diff)) return "";
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} h ago`;
  return date.toLocaleDateString([], { month: "short", day: "numeric" });
}

const STAGES = {
  queued: "Waiting to start",
  starting: "Starting",
  extracting: "Reading text",
  indexing: "Splitting into sections",
  rag_indexing: "Building search index",
  summarizing: "Writing summary",
};

export function stageLabel(stage) {
  return STAGES[stage] || "Processing";
}

export function seconds(ms) {
  if (ms == null) return "";
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

export function uid(prefix = "id") {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
}
