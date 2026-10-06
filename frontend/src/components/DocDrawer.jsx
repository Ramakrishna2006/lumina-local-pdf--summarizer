import React, { useEffect, useRef, useState } from "react";
import Icon from "./Icons.jsx";
import Markdown from "./Markdown.jsx";
import { api, downloadUrl, streamSSE } from "../api.js";
import { formatBytes, seconds } from "../utils.js";

const TYPES = [
  { id: "standard", label: "Overview" },
  { id: "brief", label: "TL;DR" },
  { id: "detailed", label: "Section by section" },
  { id: "study", label: "Study notes" },
];

export default function DocDrawer({ doc, model, language, summaryTypes, onClose, onSummarySaved, notify }) {
  const types = summaryTypes?.length ? summaryTypes : TYPES;
  const [tab, setTab] = useState("summary");
  const [type, setType] = useState("standard");
  const [text, setText] = useState(doc?.summary || "");
  const [busy, setBusy] = useState(false);
  const [stats, setStats] = useState(null);
  const [preview, setPreview] = useState(null);
  const abortRef = useRef(null);

  useEffect(() => {
    setText(doc?.summary || "");
    setStats(null);
    setPreview(null);
    setTab("summary");
    setType("standard");
    return () => abortRef.current?.abort();
  }, [doc?.id]);

  useEffect(() => {
    if (tab === "text" && doc && !preview) {
      api(`/api/documents/${doc.id}/preview?limit=20000`).then(setPreview).catch((e) => notify(e.message, "error"));
    }
  }, [tab, doc, preview, notify]);

  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  if (!doc) return null;

  async function generate(regenerate = false) {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setBusy(true);
    setText("");
    setStats(null);
    let out = "";
    try {
      await streamSSE(
        `/api/documents/${doc.id}/summary/stream`,
        { summary_type: type, regenerate, model: model || undefined, language: language || undefined },
        {
          signal: controller.signal,
          onEvent: (e) => {
            if (e.type === "token") {
              out += e.content;
              setText(out);
            } else if (e.type === "done") setStats(e.stats || null);
          },
        }
      );
      if (type === "standard" && (!language || language === "auto")) onSummarySaved?.(doc.id, out);
    } catch (e) {
      if (e.name !== "AbortError") notify(e.message, "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="drawer-layer" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <aside className="drawer" role="dialog" aria-modal="true" aria-label={`${doc.filename} details`}>
        <header className="drawer-head">
          <div>
            <h2 title={doc.filename}>{doc.filename}</h2>
            <p>
              {doc.page_count ? `${doc.page_count} ${doc.page_count === 1 ? "page" : "pages"}, ` : ""}
              {formatBytes(doc.size)}, {doc.extracted_chars?.toLocaleString()} characters
              {doc.ocr_used ? ", read with OCR" : ""}
            </p>
          </div>
          <button type="button" className="ghost-icon" onClick={onClose} aria-label="Close">
            <Icon name="close" />
          </button>
        </header>

        <div className="tabs" role="tablist">
          <button role="tab" aria-selected={tab === "summary"} className={tab === "summary" ? "is-on" : ""} onClick={() => setTab("summary")}>Summary</button>
          <button role="tab" aria-selected={tab === "text"} className={tab === "text" ? "is-on" : ""} onClick={() => setTab("text")}>Extracted text</button>
        </div>

        {tab === "summary" ? (
          <>
            <div className="summary-controls">
              <div className="chips" role="radiogroup" aria-label="Summary type">
                {types.map((t) => (
                  <button key={t.id} type="button" role="radio" aria-checked={type === t.id} className={`chip ${type === t.id ? "is-on" : ""}`} onClick={() => setType(t.id)} disabled={busy}>
                    {t.label}
                  </button>
                ))}
              </div>
              <div className="summary-actions">
                {busy ? (
                  <button type="button" className="btn btn-quiet" onClick={() => abortRef.current?.abort()}>
                    <Icon name="stop" size={14} /> Stop
                  </button>
                ) : (
                  <button type="button" className="btn btn-primary" onClick={() => generate(Boolean(text))}>
                    <Icon name="sparkle" size={15} /> {text ? "Write again" : "Write summary"}
                  </button>
                )}
                {text && !busy && (
                  <button type="button" className="btn btn-quiet" onClick={() => { navigator.clipboard?.writeText(text); notify("Summary copied", "success"); }}>
                    <Icon name="copy" size={15} /> Copy
                  </button>
                )}
                {doc.has_summary && !busy && (
                  <a className="btn btn-quiet" href={downloadUrl(`/api/documents/${doc.id}/summary/download?format=md`)}>
                    <Icon name="download" size={15} /> .md
                  </a>
                )}
              </div>
            </div>
            <div className="drawer-body">
              {text ? (
                <>
                  <Markdown text={text} />
                  {busy && <span className="stream-dot" aria-hidden="true" />}
                  {stats?.total_ms != null && <p className="msg-stats">Finished in {seconds(stats.total_ms)}</p>}
                </>
              ) : busy ? (
                <div className="thinking" role="status"><span className="shimmer">Reading the document</span></div>
              ) : (
                <p className="empty-note">Pick a summary type and press Write summary. The text appears as it is written.</p>
              )}
            </div>
          </>
        ) : (
          <div className="drawer-body plain-text">
            {preview ? (
              <>
                <pre>{preview.text}</pre>
                {preview.truncated && <p className="empty-note">Showing the first {preview.text.length.toLocaleString()} of {preview.total_chars.toLocaleString()} characters.</p>}
              </>
            ) : (
              <p className="empty-note">Loading text</p>
            )}
          </div>
        )}
      </aside>
    </div>
  );
}
