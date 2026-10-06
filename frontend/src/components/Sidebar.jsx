import React, { useMemo, useState } from "react";
import Icon from "./Icons.jsx";
import Mark from "./Mark.jsx";
import { formatBytes, relativeTime, stageLabel } from "../utils.js";

function DocRow({ doc, index = 0, selected, onToggle, onDelete, onRetry, onOpen }) {
  const ready = doc.status === "completed";
  const busy = doc.status === "queued" || doc.status === "processing";
  const ext = (doc.file_type || doc.filename.split(".").pop() || "").slice(0, 4);

  return (
    <li className={`doc-row ${selected ? "is-selected" : ""} status-${doc.status}`} style={{ "--i": Math.min(index, 12) }}>
      <label className="doc-main">
        <input type="checkbox" checked={selected} disabled={!ready} onChange={() => onToggle(doc.id)} />
        <span className="doc-ext" aria-hidden="true">{ext}</span>
        <span className="doc-text">
          <span className="doc-name" title={doc.filename}>{doc.filename}</span>
          <span className="doc-meta">
            {busy
              ? stageLabel(doc.stage)
              : doc.status === "failed"
                ? "Could not read this file"
                : `${doc.page_count ? `${doc.page_count} ${doc.page_count === 1 ? "page" : "pages"}, ` : ""}${formatBytes(doc.size)}${doc.ocr_used ? ", OCR" : ""}`}
          </span>
          {ready && doc.search === "building" && (
            <span className="doc-badge" title="Ready to use now. Smart (meaning-based) search is being added in the background.">
              Adding smart search…
            </span>
          )}
        </span>
      </label>
      <span className="doc-actions">
        {ready && (
          <button type="button" className="ghost-icon" title="Summary and text" onClick={() => onOpen(doc)}>
            <Icon name="eye" size={16} />
          </button>
        )}
        {doc.status === "failed" && (
          <button type="button" className="ghost-icon" title={doc.error || "Try again"} onClick={() => onRetry(doc)}>
            <Icon name="refresh" size={16} />
          </button>
        )}
        <button type="button" className="ghost-icon danger" title={`Delete ${doc.filename}`} onClick={() => onDelete(doc)}>
          <Icon name="trash" size={16} />
        </button>
      </span>
      {busy && (
        <span className="doc-progress" aria-hidden="true">
          <span style={{ width: `${doc.progress || 10}%` }} />
        </span>
      )}
    </li>
  );
}

export default function Sidebar({
  open,
  documents,
  selectedIds,
  chats,
  activeChatId,
  health,
  uploads,
  onToggleDoc,
  onSelectAll,
  onClearSelection,
  onDeleteDoc,
  onRetryDoc,
  onOpenDoc,
  onUploadClick,
  onNewChat,
  onOpenChat,
  onDeleteChat,
  onRenameChat,
  onClose,
  onCollapse,
}) {
  const [query, setQuery] = useState("");
  const [editing, setEditing] = useState(null);

  const filteredChats = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? chats.filter((c) => (c.title || "").toLowerCase().includes(q)) : chats;
  }, [chats, query]);

  const readyCount = documents.filter((d) => d.status === "completed").length;

  return (
    <aside className={`sidebar ${open ? "is-open" : ""}`} aria-label="Library and chats">
      <div className="brand">
        <Mark size={24} />
        <span className="brand-name">Lumina</span>
        <button type="button" className="ghost-icon collapse-btn" onClick={onCollapse} aria-label="Hide sidebar" title="Hide sidebar">
          <Icon name="panel" size={18} />
        </button>
        <button type="button" className="ghost-icon only-mobile" onClick={onClose} aria-label="Close menu">
          <Icon name="close" />
        </button>
      </div>

      <button type="button" className="new-chat" onClick={onNewChat}>
        <span className="new-chat-icon"><Icon name="plus" size={15} /></span>
        New chat
        <kbd>Ctrl K</kbd>
      </button>

      <section className="side-section library">
        <header className="side-head">
          <h2 className="label">Library</h2>
          <span className="side-count">{selectedIds.length} of {readyCount} in use</span>
        </header>

        <div className="lib-tools">
          <button type="button" className="link-btn" onClick={onSelectAll} disabled={!readyCount}>Use all</button>
          <button type="button" className="link-btn" onClick={onClearSelection} disabled={!selectedIds.length}>Clear</button>
          <button type="button" className="mini-btn" onClick={onUploadClick}>
            <Icon name="plus" size={14} /> Add files
          </button>
        </div>

        <ul className="doc-list">
          {uploads.map((u) => (
            <li key={u.id} className="doc-row is-uploading">
              <span className="doc-main">
                <span className="doc-ext">{u.name.split(".").pop().slice(0, 4)}</span>
                <span className="doc-text">
                  <span className="doc-name">{u.name}</span>
                  <span className="doc-meta">Uploading {u.progress}%</span>
                </span>
              </span>
              <span className="doc-progress"><span style={{ width: `${u.progress}%` }} /></span>
            </li>
          ))}
          {documents.map((doc, i) => (
            <DocRow
              index={i}
              key={doc.id}
              doc={doc}
              selected={selectedIds.includes(doc.id)}
              onToggle={onToggleDoc}
              onDelete={onDeleteDoc}
              onRetry={onRetryDoc}
              onOpen={onOpenDoc}
            />
          ))}
          {!documents.length && !uploads.length && (
            <li className="empty-note">
              Drop a PDF, Word, PowerPoint, Excel, text or image file anywhere on this window to add it.
            </li>
          )}
        </ul>
      </section>

      <section className="side-section chats">
        <header className="side-head">
          <h2 className="label">Recents</h2>
        </header>
        <div className="search">
          <Icon name="search" size={15} />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search chats..." aria-label="Search chats" />
        </div>
        <ul className="chat-list">
          {filteredChats.map((chat, i) => (
            <li key={chat.id} className={`chat-row ${activeChatId === chat.id ? "is-active" : ""}`} style={{ "--i": Math.min(i, 10) }}>
              {editing === chat.id ? (
                <input
                  className="rename-input"
                  defaultValue={chat.title}
                  autoFocus
                  onBlur={(e) => {
                    setEditing(null);
                    if (e.target.value.trim() && e.target.value !== chat.title) onRenameChat(chat, e.target.value.trim());
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") e.currentTarget.blur();
                    if (e.key === "Escape") setEditing(null);
                  }}
                />
              ) : (
                <button type="button" className="chat-open" onClick={() => onOpenChat(chat)} onDoubleClick={() => setEditing(chat.id)}>
                  <span className="chat-text">
                    <span className="chat-title">{chat.title || "New chat"}</span>
                    <span className="chat-time">{relativeTime(chat.updated_at)}</span>
                  </span>
                </button>
              )}
              <span className="chat-actions">
                <button type="button" className="ghost-icon" title="Rename" onClick={() => setEditing(chat.id)}>
                  <Icon name="edit" size={14} />
                </button>
                <button type="button" className="ghost-icon danger" title="Delete chat" onClick={() => onDeleteChat(chat)}>
                  <Icon name="trash" size={14} />
                </button>
              </span>
            </li>
          ))}
          {!filteredChats.length && <li className="empty-note">{query ? "No chats match that search." : "Your conversations will appear here."}</li>}
        </ul>
      </section>

      <footer className={`status ${health?.ollama_reachable ? "is-online" : "is-offline"}`}>
        <span className="dot" aria-hidden="true" />
        <span className="status-text">
          <strong>
            {!health
              ? "Connecting…"
              : health.backend_down
                ? "Backend is not running"
                : health.ollama_reachable
                  ? "Local AI · Live"
                  : `${health.llm_provider === "openai" ? "LLM server" : "Ollama"} is not reachable`}
          </strong>
          <span>
            {health?.backend_down
              ? "Start it on port 5001, then refresh"
              : health?.ollama_reachable
                ? `${health.llm_provider === "openai" ? "LLM server" : "Ollama"} · ${health.default_model || health.ollama_model || "local model"} · Private`
                : "Start it, then refresh this page"}
          </span>
        </span>
      </footer>
    </aside>
  );
}
