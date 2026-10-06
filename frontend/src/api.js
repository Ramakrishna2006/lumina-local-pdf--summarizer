// Small API client for the Lumina backend.
// In development Vite proxies /api to the backend (see vite.config.js),
// so the default base URL is "" (same origin). Override with VITE_API_URL.

export const API = (import.meta.env?.VITE_API_URL || "").replace(/\/$/, "");

async function parse(response) {
  const text = await response.text();
  let data = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { detail: text };
  }
  if (!response.ok) {
    const detail = Array.isArray(data.detail)
      ? data.detail.map((d) => d.msg).join(", ")
      : data.detail || data.message;
    throw new Error(detail || `Request failed (${response.status})`);
  }
  return data;
}

export async function api(path, { method = "GET", body, signal } = {}) {
  const response = await fetch(`${API}${path}`, {
    method,
    signal,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  return parse(response);
}

/** Upload one file with progress (fetch cannot report upload progress). */
export function uploadFile(file, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API}/api/documents/upload`);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress?.(Math.round((e.loaded / e.total) * 100));
    };
    xhr.onload = () => {
      let data = {};
      try {
        data = JSON.parse(xhr.responseText || "{}");
      } catch {
        data = {};
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data);
      else reject(new Error(data.detail || `Upload failed (${xhr.status})`));
    };
    xhr.onerror = () => reject(new Error("Could not reach the backend. Is it running on port 5001?"));
    const form = new FormData();
    form.append("file", file);
    xhr.send(form);
  });
}

/**
 * POST a JSON body and read a Server-Sent-Events stream.
 * Calls onEvent(event) for every `data:` JSON payload.
 */
export async function streamSSE(path, body, { onEvent, signal } = {}) {
  const response = await fetch(`${API}${path}`, {
    method: "POST",
    signal,
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(body || {}),
  });
  if (!response.ok) await parse(response);
  if (!response.body) throw new Error("This browser does not support streaming.");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const handle = (block) => {
    for (const line of block.split("\n")) {
      if (!line.startsWith("data:")) continue;
      const json = line.slice(5).trim();
      if (!json) continue;
      let event;
      try {
        event = JSON.parse(json);
      } catch {
        continue;
      }
      if (event.type === "error") throw new Error(event.message || "Generation failed.");
      onEvent?.(event);
    }
  };

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() || "";
    blocks.forEach(handle);
  }
  if (buffer.trim()) handle(buffer);
}

export function downloadUrl(path) {
  return `${API}${path}`;
}
