import React from "react";
import Icon from "./Icons.jsx";
import Mark from "./Mark.jsx";
import { formatBytes, stageLabel } from "../utils.js";

const FALLBACK = {
  ai: [
    "Summarize the main ideas in five bullet points",
    "What are the key definitions I should know?",
    "List every important date, number and name",
    "Make three exam questions from this material",
  ],
  image: [
    "A watercolor lighthouse on a cliff at sunset",
    "A cozy study desk with books and a warm lamp, digital art",
    "A labelled diagram-style illustration of a plant cell",
    "A futuristic city skyline at night, neon lights",
  ],
  web: [
    "What are the best small local LLMs for laptops?",
    "Compare FAISS and Chroma for local vector search",
    "How does retrieval-augmented generation work?",
    "Latest research on document question answering",
  ],
};

function greeting() {
  const h = new Date().getHours();
  if (h < 5) return "Working late";
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  return "Good evening";
}

function extOf(name = "") {
  return (name.split(".").pop() || "doc").slice(0, 4).toUpperCase();
}

/** A compact file chip – shows upload / reading progress, then "Ready". */
function FileCard({ name, meta, progress, ready, onOpen, index }) {
  return (
    <button type="button" className={`file-card ${ready ? "is-ready" : ""}`} style={{ "--i": index }} onClick={onOpen} disabled={!ready} title={ready ? "Open summary" : meta}>
      <span className="file-ext">{extOf(name)}</span>
      <span className="file-text">
        <b>{name}</b>
        <small>{meta}</small>
      </span>
      {ready ? <Icon name="check" size={14} className="file-ok" /> : <span className="file-pct">{Math.round(progress || 0)}%</span>}
      {!ready && <span className="file-bar"><i style={{ width: `${Math.max(6, progress || 0)}%` }} /></span>}
    </button>
  );
}

export default function Welcome({ documents, uploads, selectedDocs, suggestions, mode, onPick, onUpload, onOpenDoc, children }) {
  const hasDocs = documents.length > 0;
  const names = selectedDocs.map((d) => d.filename);
  const list = mode === "web" ? FALLBACK.web : mode === "image" ? FALLBACK.image : suggestions === null ? null : suggestions?.length ? suggestions : FALLBACK.ai;

  // Files being uploaded or read, then the ready documents you have selected.
  const busy = documents.filter((d) => d.status === "queued" || d.status === "processing");
  const cards = [
    ...uploads.map((u) => ({ key: u.id, name: u.name, meta: `Uploading · ${u.progress}%`, progress: u.progress })),
    ...busy.map((d) => ({ key: d.id, name: d.filename, meta: `${formatBytes(d.size)} · ${stageLabel(d.stage)}`, progress: d.progress || 8 })),
    ...selectedDocs.slice(0, 3).map((d) => ({
      key: d.id,
      name: d.filename,
      ready: true,
      doc: d,
      meta: `${formatBytes(d.size)}${d.page_count ? ` · ${d.page_count} ${d.page_count === 1 ? "page" : "pages"}` : ""}${d.search === "building" ? " · adding smart search…" : ""}`,
    })),
  ].slice(0, 4);

  return (
    <div className="welcome">
      <div className="hero">
        <Mark size={40} />
        <h1>{greeting()}</h1>
      </div>
      <p className="hero-sub">
        {mode === "web"
          ? "Ask anything – Lumina searches public sources and writes a cited answer with your local model."
          : mode === "image"
            ? "Describe a picture and Lumina paints it on this computer."
          : hasDocs
            ? names.length
              ? `Ready to answer from ${names.length === 1 ? names[0] : `${names.length} documents`}.`
              : "Tick a document in your library to start."
            : "Add a PDF, Word file, slides or a photo of a page. Everything stays on this computer."}
      </p>

      {children}

      {!hasDocs && !uploads.length && mode === "ai" ? (
        <button type="button" className="add-first" onClick={onUpload}>
          <Icon name="upload" size={16} /> Add your first document
          <small>or drop files anywhere</small>
        </button>
      ) : (
        mode === "ai" &&
        cards.length > 0 && (
          <div className="file-cards">
            {cards.map((c, i) => (
              <FileCard key={c.key} index={i} {...c} onOpen={() => c.doc && onOpenDoc(c.doc)} />
            ))}
          </div>
        )
      )}

      {(mode === "web" || mode === "image" || names.length > 0) && (
        <div className="suggest">
          {list === null
            ? Array.from({ length: 4 }).map((_, i) => <span key={i} className="sg skeleton" style={{ "--i": i }} />)
            : list.map((p, i) => (
                <button key={p} type="button" className="sg" style={{ "--i": i }} onClick={() => onPick(p)}>
                  <span>{p}</span>
                </button>
              ))}
        </div>
      )}
    </div>
  );
}
