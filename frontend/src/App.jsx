import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, downloadUrl, streamSSE, uploadFile } from "./api.js";
import Composer from "./components/Composer.jsx";
import DocDrawer from "./components/DocDrawer.jsx";
import Icon from "./components/Icons.jsx";
import Message from "./components/Message.jsx";
import SpeedTip from "./components/SpeedTip.jsx";
import Sidebar from "./components/Sidebar.jsx";
import ThemePanel from "./components/ThemePanel.jsx";
import Toasts from "./components/Toasts.jsx";
import Welcome from "./components/Welcome.jsx";
import { uid } from "./utils.js";
import { applyTheme, normalizeTheme, resolvedMode } from "./theme.js";

function clientOs() {
  const p = (navigator.userAgentData?.platform || navigator.platform || "").toLowerCase();
  if (p.includes("mac")) return "macos";
  if (p.includes("linux") || p.includes("android")) return "linux";
  return "windows";
}

function initialTheme() {
  const stored = load("lm.theme2", null);
  if (stored) return normalizeTheme(stored);
  const old = load("lm.theme", null); // older versions stored just "light" / "dark"
  return normalizeTheme({ mode: old === "dark" ? "dark" : "light" });
}

const DEFAULT_STYLES = [
  { id: "balanced", label: "Balanced" },
  { id: "concise", label: "Concise" },
  { id: "detailed", label: "Detailed" },
  { id: "bullets", label: "Bullet points" },
  { id: "simple", label: "Explain simply" },
  { id: "study", label: "Study notes" },
];

const ACCEPT = [
  ".pdf", ".docx", ".pptx", ".xlsx", ".xls", ".csv", ".txt", ".md", ".markdown", ".rst", ".log", ".tex",
  ".json", ".xml", ".yaml", ".yml", ".ini", ".toml", ".html", ".htm",
  ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".h", ".cpp", ".cs", ".go", ".rs", ".php", ".rb", ".sql", ".sh", ".css",
  ".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp",
].join(",");

function load(key, fallback) {
  try {
    const v = localStorage.getItem(key);
    return v == null ? fallback : JSON.parse(v);
  } catch {
    return fallback;
  }
}
function save(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* storage unavailable */
  }
}

export default function App() {
  const [documents, setDocuments] = useState([]);
  const [selectedIds, setSelectedIds] = useState(() => load("lm.selected", []));
  const [chats, setChats] = useState([]);
  const [activeChat, setActiveChat] = useState(null);
  const [messages, setMessages] = useState([]);
  const [question, setQuestion] = useState("");
  const [mode, setMode] = useState("ai");
  const [imageEnabled, setImageEnabled] = useState(true);
  const [imageHosted, setImageHosted] = useState(false);
  useEffect(() => {
    api("/api/images/status")
      .then((st) => {
        setImageEnabled(st.enabled !== false);
        setImageHosted(Boolean(st.hosted));
        if (st.enabled === false) setMode((m) => (m === "image" ? "ai" : m));
      })
      .catch(() => {});
  }, []);
  const [style, setStyle] = useState(() => load("lm.style", "balanced"));
  const [language, setLanguage] = useState(() => load("lm.language", "auto"));
  const [languages, setLanguages] = useState([{ id: "auto", label: "Same as the question" }]);
  const [summaryTypes, setSummaryTypes] = useState(null);
  const [motion, setMotion] = useState(() => load("lm.motion", true));
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [suggestions, setSuggestions] = useState(null);
  const [model, setModel] = useState(() => load("lm.model", ""));
  const [models, setModels] = useState([]);
  const [styles, setStyles] = useState(DEFAULT_STYLES);
  const [health, setHealth] = useState(null);
  const [sending, setSending] = useState(false);
  const [uploads, setUploads] = useState([]);
  const [toasts, setToasts] = useState([]);
  const [drawerDocId, setDrawerDocId] = useState(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(() => load("lm.collapsed", false));
  const [dragging, setDragging] = useState(false);
  const [theme, setTheme] = useState(initialTheme);
  const [themeOpen, setThemeOpen] = useState(false);
  const [themeWarnings, setThemeWarnings] = useState([]);

  const fileInput = useRef(null);
  const inputRef = useRef(null);
  const scrollRef = useRef(null);
  const abortRef = useRef(null);
  const stickToBottom = useRef(true);

  // ---------------------------------------------------------------- helpers
  const notify = useCallback((text, kind = "info") => {
    const id = uid("t");
    setToasts((t) => [...t.slice(-3), { id, text, kind }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), kind === "error" ? 7000 : 3500);
  }, []);

  const docsById = useMemo(() => Object.fromEntries(documents.map((d) => [d.id, d])), [documents]);
  const selectedDocs = selectedIds.map((id) => docsById[id]).filter(Boolean);
  const readySelected = selectedDocs.filter((d) => d.status === "completed");
  const drawerDoc = drawerDocId ? docsById[drawerDocId] : null;

  useEffect(() => save("lm.selected", selectedIds), [selectedIds]);
  useEffect(() => save("lm.style", style), [style]);
  useEffect(() => save("lm.model", model), [model]);
  useEffect(() => save("lm.language", language), [language]);
  useEffect(() => save("lm.motion", motion), [motion]);
  useEffect(() => save("lm.collapsed", collapsed), [collapsed]);
  useEffect(() => {
    // Colours: accent, gradient, custom backgrounds – applied as CSS variables.
    setThemeWarnings(applyTheme(theme));
    save("lm.theme2", theme);
    if (theme.mode !== "system" || !window.matchMedia) return undefined;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => setThemeWarnings(applyTheme(theme));
    mq.addEventListener?.("change", onChange);
    return () => mq.removeEventListener?.("change", onChange);
  }, [theme]);

  // ---------------------------------------------------------------- loading
  const loadDocuments = useCallback(async () => {
    try {
      const list = await api("/api/documents");
      setDocuments(list);
      setSelectedIds((current) => {
        // Keep selections for documents that still exist and did not fail.
        const usable = new Set(list.filter((d) => d.status !== "failed").map((d) => d.id));
        const kept = current.filter((id) => usable.has(id));
        if (kept.length === 0 && current.length === 0) {
          const first = list.find((d) => d.status === "completed");
          return first ? [first.id] : current;
        }
        return kept.length === current.length ? current : kept;
      });
      return list;
    } catch (e) {
      notify(`Could not load documents. ${e.message}`, "error");
      return [];
    }
  }, [notify]);

  const loadChats = useCallback(async () => {
    try {
      setChats(await api("/api/chats"));
    } catch {
      /* shown by health indicator */
    }
  }, []);

  useEffect(() => {
    loadDocuments();
    loadChats();
    api("/api/config")
      .then((c) => {
        if (c.answer_styles?.length) setStyles(c.answer_styles);
        if (c.languages?.length) setLanguages(c.languages);
        if (c.summary_types?.length) setSummaryTypes(c.summary_types);
      })
      .catch(() => {});
    api("/api/models")
      .then((m) => setModels((m.models || []).filter((x) => !x.is_embedding)))
      .catch(() => {});
    const checkHealth = () => api("/api/health").then(setHealth).catch(() => setHealth({ ollama_reachable: false, backend_down: true }));
    checkHealth();
    const timer = setInterval(checkHealth, 20000);
    return () => clearInterval(timer);
  }, [loadDocuments, loadChats]);

  // Poll while any document is still being processed (fast) or while its
  // smart-search index is being built in the background (slower).
  const anyBusy = documents.some((d) => d.status === "queued" || d.status === "processing");
  const anyBuilding = documents.some((d) => d.search === "building");
  useEffect(() => {
    if (!anyBusy && anyBuilding) {
      const slow = setInterval(loadDocuments, 4000);
      return () => clearInterval(slow);
    }
    if (!anyBusy) return undefined;
    const timer = setInterval(async () => {
      const before = new Set(documents.filter((d) => d.status !== "completed").map((d) => d.id));
      const list = await loadDocuments();
      list
        .filter((d) => before.has(d.id) && d.status === "completed")
        .forEach((d) => {
          notify(`${d.filename} is ready`, "success");
        });
      list
        .filter((d) => before.has(d.id) && d.status === "failed")
        .forEach((d) => notify(`${d.filename}: ${d.error || "could not be read"}`, "error"));
    }, 1200);
    return () => clearInterval(timer);
  }, [anyBusy, anyBuilding, documents, loadDocuments, notify]);

  // ------------------------------------------------- suggested questions
  const readyKey = readySelected.map((d) => d.id).sort().join(",");
  useEffect(() => {
    if (!readyKey) {
      setSuggestions(null);
      return undefined;
    }
    let alive = true;
    setSuggestions(null);
    const timer = setTimeout(() => {
      api("/api/suggestions", { method: "POST", body: { document_ids: readyKey.split(","), model: model || null } })
        .then((r) => alive && setSuggestions(r.suggestions))
        .catch(() => alive && setSuggestions([]));
    }, 350);
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [readyKey, model]);

  // ---------------------------------------------------------------- scroll
  useEffect(() => {
    const el = scrollRef.current;
    if (el && stickToBottom.current) el.scrollTop = el.scrollHeight;
  }, [messages]);

  const onScroll = () => {
    const el = scrollRef.current;
    if (el) stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
  };

  // ---------------------------------------------------------------- uploads
  const handleFiles = useCallback(
    async (fileList) => {
      const files = Array.from(fileList || []);
      if (!files.length) return;
      const accepted = ACCEPT.split(",");
      for (const file of files) {
        const ext = `.${file.name.split(".").pop().toLowerCase()}`;
        if (!accepted.includes(ext)) {
          notify(`${file.name} is not a supported file type.`, "error");
          continue;
        }
        const id = uid("up");
        setUploads((u) => [...u, { id, name: file.name, progress: 0 }]);
        try {
          const created = await uploadFile(file, (p) => setUploads((u) => u.map((x) => (x.id === id ? { ...x, progress: p } : x))));
          if (created?.id) setSelectedIds((ids) => (ids.includes(created.id) ? ids : [...ids, created.id]));
          await loadDocuments();
        } catch (e) {
          notify(`${file.name}: ${e.message}`, "error");
        } finally {
          setUploads((u) => u.filter((x) => x.id !== id));
        }
      }
    },
    [loadDocuments, notify]
  );

  useEffect(() => {
    let depth = 0;
    const hasFiles = (e) => Array.from(e.dataTransfer?.types || []).includes("Files");
    const enter = (e) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      depth += 1;
      setDragging(true);
    };
    const over = (e) => hasFiles(e) && e.preventDefault();
    const leave = (e) => {
      if (!hasFiles(e)) return;
      depth = Math.max(0, depth - 1);
      if (!depth) setDragging(false);
    };
    const drop = (e) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      depth = 0;
      setDragging(false);
      handleFiles(e.dataTransfer.files);
    };
    window.addEventListener("dragenter", enter);
    window.addEventListener("dragover", over);
    window.addEventListener("dragleave", leave);
    window.addEventListener("drop", drop);
    return () => {
      window.removeEventListener("dragenter", enter);
      window.removeEventListener("dragover", over);
      window.removeEventListener("dragleave", leave);
      window.removeEventListener("drop", drop);
    };
  }, [handleFiles]);

  // ---------------------------------------------------------------- chats
  const newChat = useCallback(() => {
    abortRef.current?.abort();
    setActiveChat(null);
    setMessages([]);
    setQuestion("");
    setSidebarOpen(false);
    setTimeout(() => inputRef.current?.focus(), 30);
  }, []);

  async function openChat(chat) {
    abortRef.current?.abort();
    try {
      const full = await api(`/api/chats/${chat.id}`);
      setActiveChat(full);
      setMessages(full.messages || []);
      const ids = (full.document_ids || []).filter((id) => docsById[id]);
      if (ids.length) setSelectedIds(ids);
      setMode("ai");
      setSidebarOpen(false);
      stickToBottom.current = true;
    } catch (e) {
      notify(e.message, "error");
    }
  }

  async function deleteChat(chat) {
    if (!window.confirm(`Delete the chat "${chat.title}"?`)) return;
    try {
      await api(`/api/chats/${chat.id}`, { method: "DELETE" });
      if (activeChat?.id === chat.id) newChat();
      loadChats();
    } catch (e) {
      notify(e.message, "error");
    }
  }

  async function renameChat(chat, title) {
    try {
      const updated = await api(`/api/chats/${chat.id}`, { method: "PATCH", body: { title } });
      setChats((list) => list.map((c) => (c.id === chat.id ? { ...c, title: updated.title } : c)));
      if (activeChat?.id === chat.id) setActiveChat((c) => ({ ...c, title: updated.title }));
    } catch (e) {
      notify(e.message, "error");
    }
  }

  // ---------------------------------------------------------------- documents
  function toggleDoc(id) {
    setSelectedIds((ids) => (ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id]));
  }

  async function deleteDoc(doc) {
    if (!window.confirm(`Delete "${doc.filename}"?\n\nThe file, its search index and any chat that only uses it will be removed.`)) return;
    try {
      await api(`/api/documents/${doc.id}`, { method: "DELETE" });
      setSelectedIds((ids) => ids.filter((x) => x !== doc.id));
      if (drawerDocId === doc.id) setDrawerDocId(null);
      if (activeChat?.document_ids?.includes(doc.id)) newChat();
      await loadDocuments();
      loadChats();
      notify(`Deleted ${doc.filename}`, "success");
    } catch (e) {
      notify(e.message, "error");
    }
  }

  async function retryDoc(doc) {
    try {
      await api(`/api/documents/${doc.id}/retry`, { method: "POST" });
      loadDocuments();
    } catch (e) {
      notify(e.message, "error");
    }
  }

  // ---------------------------------------------------------------- streaming
  async function runStream({ path, body, assistantId }) {
    const controller = new AbortController();
    abortRef.current = controller;
    setSending(true);
    stickToBottom.current = true;

    let buffer = "";
    let frame = 0;
    const flush = () => {
      frame = 0;
      const content = buffer;
      setMessages((list) => list.map((m) => (m.id === assistantId ? { ...m, content, phase: "writing" } : m)));
    };
    const patch = (fields) => setMessages((list) => list.map((m) => (m.id === assistantId ? { ...m, ...fields } : m)));

    try {
      await streamSSE(path, body, {
        signal: controller.signal,
        onEvent: (e) => {
          if (e.type === "sources") patch({ sources: e.sources, phase: "writing", estimate: e.estimate_s, firstWord: e.first_word_s, startedAt: Date.now() });
          else if (e.type === "token") {
            buffer += e.content;
            if (!frame) frame = requestAnimationFrame(flush);
          } else if (e.type === "done") {
            if (frame) cancelAnimationFrame(frame);
            patch({ content: buffer, streaming: false, stats: e.stats });
          }
        },
      });
      patch({ content: buffer, streaming: false });
    } catch (e) {
      if (frame) cancelAnimationFrame(frame);
      if (e.name === "AbortError") patch({ content: buffer || "_Stopped._", streaming: false });
      else patch({ streaming: false, content: buffer, error: buffer ? null : e.message });
      if (e.name !== "AbortError") notify(e.message, "error");
    } finally {
      setSending(false);
      abortRef.current = null;
      loadChats();
      setTimeout(() => inputRef.current?.focus(), 30);
    }
  }

  async function runImage(prompt, assistantId) {
    const controller = new AbortController();
    abortRef.current = controller;
    setSending(true);
    stickToBottom.current = true;
    const patch = (fields) => setMessages((list) => list.map((m) => (m.id === assistantId ? { ...m, ...fields } : m)));
    patch({ phase: "painting", startedAt: Date.now(), hosted: imageHosted });
    try {
      const image = await api("/api/images/generate", { method: "POST", body: { prompt }, signal: controller.signal });
      patch({ streaming: false, image, content: "" });
    } catch (e) {
      if (e.name === "AbortError") patch({ streaming: false, content: "_Stopped._" });
      else {
        patch({ streaming: false, error: e.message });
        notify("Could not make the image", "error");
      }
    } finally {
      setSending(false);
      abortRef.current = null;
      setTimeout(() => inputRef.current?.focus(), 30);
    }
  }

  async function ensureChat(text) {
    const ids = readySelected.map((d) => d.id);
    const same =
      activeChat &&
      activeChat.document_ids?.length === ids.length &&
      ids.every((id) => activeChat.document_ids.includes(id));
    if (same) return activeChat;
    const chat = await api("/api/chats", { method: "POST", body: { document_ids: ids, title: text.slice(0, 60) } });
    setActiveChat(chat);
    if (activeChat) setMessages([]);
    return chat;
  }

  async function send(textArg) {
    const text = (textArg ?? question).trim();
    if (!text || sending) return;
    if (mode === "ai" && !readySelected.length) {
      notify("Select at least one ready document in the library first.", "error");
      return;
    }

    setQuestion("");
    const assistantId = uid("a");
    try {
      let chat = activeChat;
      if (mode === "ai") chat = await ensureChat(text);
      setMessages((list) => [
        ...list,
        { id: uid("u"), role: "user", content: text, mode },
        { id: assistantId, role: "assistant", content: "", sources: [], streaming: true, phase: "searching", mode },
      ]);

      if (mode === "image") {
        await runImage(text, assistantId);
      } else if (mode === "code") {
        const history = messages
          .filter((m) => m.mode === "code" && !m.error && (m.content || "").trim())
          .slice(-8)
          .map((m) => ({ role: m.role, content: m.content.slice(0, 8000) }));
        await runStream({
          path: "/api/code/stream",
          body: { question: text, history, model: model || null, language, client_os: clientOs() },
          assistantId,
        });
      } else if (mode === "web") {
        await runStream({
          path: "/api/research/stream",
          body: { question: text, document_ids: readySelected.map((d) => d.id), chat_id: chat?.id || null, model: model || null, language },
          assistantId,
        });
      } else {
        await runStream({
          path: `/api/chats/${chat.id}/messages/stream`,
          body: { question: text, style, model: model || null, language },
          assistantId,
        });
      }
    } catch (e) {
      notify(e.message, "error");
      setQuestion(text);
    }
  }

  async function regenerate() {
    if (!activeChat || sending) return;
    const assistantId = uid("a");
    setMessages((list) => {
      const copy = [...list];
      if (copy.length && copy[copy.length - 1].role === "assistant") copy.pop();
      return [...copy, { id: assistantId, role: "assistant", content: "", sources: [], streaming: true, phase: "searching" }];
    });
    await runStream({
      path: `/api/chats/${activeChat.id}/messages/stream`,
      body: { regenerate: true, style, model: model || null, language },
      assistantId,
    });
  }

  // ---------------------------------------------------------------- shortcuts
  useEffect(() => {
    const onKey = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        newChat();
      } else if (e.key === "/" && !["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName)) {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [newChat]);

  // ---------------------------------------------------------------- render
  const disabledReason =
    mode === "ai" && !readySelected.length
      ? documents.length
        ? "Select a document in the library to ask about it"
        : "Add a document to start"
      : "";

  const isDark = resolvedMode(theme) === "dark";
  const composer = (centered) => (
    <Composer
      centered={centered}
      value={question}
      onChange={setQuestion}
      onSend={() => send()}
      onStop={() => abortRef.current?.abort()}
      onAttach={() => fileInput.current?.click()}
      sending={sending}
      mode={mode}
      onModeChange={setMode}
      style={style}
      styles={styles}
      onStyleChange={setStyle}
      disabledReason={mode === "ai" && !readySelected.length ? disabledReason : ""}
      selectedCount={readySelected.length}
      inputRef={inputRef}
      imageEnabled={imageEnabled}
      imageHosted={imageHosted}
    />
  );
  const speedTip = (
    <SpeedTip health={health} models={models} model={model} onUseModel={(name) => { setModel(name); notify(`Now using ${name}`, "success"); }} />
  );
  const readyCount = documents.filter((d) => d.status === "completed").length;
  const defaultModel = health?.default_model || health?.ollama_model || "";
  const lastAssistant = messages.length ? messages[messages.length - 1] : null;
  const showFollowUps = mode === "ai" && !sending && lastAssistant?.role === "assistant" && lastAssistant.mode !== "image" && !lastAssistant.error && suggestions?.length > 0;

  return (
    <div className={`app ${collapsed ? "side-collapsed" : ""}`} data-motion={motion ? "on" : "off"}>
      <Sidebar
        open={sidebarOpen}
        documents={documents}
        selectedIds={selectedIds}
        chats={chats}
        activeChatId={activeChat?.id}
        health={health}
        uploads={uploads}
        onToggleDoc={toggleDoc}
        onSelectAll={() => setSelectedIds(documents.filter((d) => d.status === "completed").map((d) => d.id))}
        onClearSelection={() => setSelectedIds([])}
        onDeleteDoc={deleteDoc}
        onRetryDoc={retryDoc}
        onOpenDoc={(d) => setDrawerDocId(d.id)}
        onUploadClick={() => fileInput.current?.click()}
        onNewChat={newChat}
        onOpenChat={openChat}
        onDeleteChat={deleteChat}
        onRenameChat={renameChat}
        onClose={() => setSidebarOpen(false)}
        onCollapse={() => setCollapsed(true)}
      />
      {sidebarOpen && <div className="scrim" onClick={() => setSidebarOpen(false)} />}

      <main className="main">
        <header className="topbar">
          <button type="button" className="ghost-icon only-mobile" onClick={() => setSidebarOpen(true)} aria-label="Open menu">
            <Icon name="menu" />
          </button>
          {collapsed && (
            <button type="button" className="ghost-icon hide-mobile" onClick={() => setCollapsed(false)} aria-label="Show sidebar" title="Show sidebar">
              <Icon name="panel" />
            </button>
          )}
          <span className="top-title" key={activeChat?.id || "new"}>{messages.length ? activeChat?.title || "New chat" : ""}</span>
          <span className="spacer" />

          <button
            type="button"
            className="pill"
            onClick={() => readySelected[0] && setDrawerDocId(readySelected[0].id)}
            title={readySelected.length ? readySelected.map((d) => d.filename).join("\n") + "\n\nClick for summaries" : "Tick documents in the library"}
          >
            <Icon name={mode === "web" ? "globe" : mode === "image" ? "image" : mode === "code" ? "code" : "doc"} size={14} />
            <span className="pill-text">
              {mode === "web"
                ? "Web search"
                : mode === "code"
                  ? "Code"
                : mode === "image"
                  ? "Image"
                : readySelected.length === 1
                  ? readySelected[0].filename
                  : readySelected.length
                    ? `${readySelected.length} documents`
                    : "No document"}
            </span>
          </button>
          {models.length > 0 && (
            <label className="pill model-pill" title="AI model">
              <Icon name="sparkle" size={14} />
              <select value={model} onChange={(e) => setModel(e.target.value)} aria-label="AI model">
                <option value="">{defaultModel || "Default model"}</option>
                {models
                  .filter((m) => m.name !== defaultModel)
                  .map((m) => (
                    <option key={m.name} value={m.name}>
                      {m.name}{m.parameter_size ? ` (${m.parameter_size})` : ""}
                    </option>
                  ))}
              </select>
              <Icon name="chevron" size={13} />
            </label>
          )}
          <button type="button" className="ghost-icon theme-btn" onClick={() => setTheme((t) => ({ ...t, mode: isDark ? "light" : "dark" }))} aria-label="Toggle light and dark theme" title="Theme">
            <Icon name={isDark ? "sun" : "moon"} />
          </button>
          <div className="settings-wrap">
            <button
              type="button"
              className={`ghost-icon ${settingsOpen ? "is-on" : ""}`}
              onClick={() => setSettingsOpen((o) => !o)}
              aria-label="Settings"
              aria-expanded={settingsOpen}
              title="Settings"
            >
              <Icon name="settings" />
            </button>
            {settingsOpen && (
              <>
                <div className="popover-scrim" onClick={() => setSettingsOpen(false)} />
                <div className="popover" role="dialog" aria-label="Settings">
                  <h3>Preferences</h3>
                  <label className="field">
                    <span>Answer language</span>
                    <select value={language} onChange={(e) => setLanguage(e.target.value)}>
                      {languages.map((l) => (
                        <option key={l.id} value={l.id}>{l.label}</option>
                      ))}
                    </select>
                  </label>
                  <label className="field">
                    <span>Answer style</span>
                    <select value={style} onChange={(e) => setStyle(e.target.value)}>
                      {styles.map((s) => (
                        <option key={s.id} value={s.id}>{s.label}</option>
                      ))}
                    </select>
                  </label>
                  <label className="switch">
                    <input type="checkbox" checked={motion} onChange={(e) => setMotion(e.target.checked)} />
                    <span className="switch-track"><span /></span>
                    <span>Animations</span>
                  </label>
                  <label className="switch">
                    <input type="checkbox" checked={!isDark} onChange={(e) => setTheme((t) => ({ ...t, mode: e.target.checked ? "light" : "dark" }))} />
                    <span className="switch-track"><span /></span>
                    <span>Light theme</span>
                  </label>
                  <button type="button" className="mini-btn" onClick={() => { setSettingsOpen(false); setThemeOpen(true); }}>
                    <Icon name="palette" size={14} /> Change colours…
                  </button>
                  <p className="popover-note">
                    Engine: <strong>{health?.llm_provider === "openai" ? "OpenAI-compatible server" : "Ollama"}</strong>
                    {defaultModel ? ` · ${defaultModel}` : ""}
                    {health?.answer_cache ? ` · ${health.answer_cache.hits} instant answers` : ""}
                  </p>
                </div>
              </>
            )}
          </div>
        </header>

        {messages.length === 0 ? (
          <section className="conversation is-empty" ref={scrollRef}>
            <Welcome
              documents={documents}
              uploads={uploads}
              onOpenDoc={(d) => setDrawerDocId(d.id)}
              selectedDocs={readySelected}
              suggestions={suggestions}
              mode={mode}
              onPick={(p) => send(p)}
              onUpload={() => fileInput.current?.click()}
            >
              {speedTip}
              {composer(true)}
            </Welcome>
          </section>
        ) : (
          <>
            <section className="conversation" ref={scrollRef} onScroll={onScroll}>
              <div className="inner">
                {messages.map((m, i) => (
                  <Message
                    key={m.id || i}
                    message={m}
                    isLast={i === messages.length - 1}
                    canRegenerate={Boolean(activeChat) && m.mode !== "web" && m.mode !== "image" && m.mode !== "code" && !sending}
                    onRegenerate={regenerate}
                    onFollowUp={(p) => send(p)}
                    exportHref={activeChat ? downloadUrl(`/api/chats/${activeChat.id}/export`) : null}
                  />
                ))}
                {showFollowUps && (
                  <div className="suggest follow">
                    {suggestions.slice(0, 4).map((p, i) => (
                      <button key={p} type="button" className="sg" style={{ "--i": i }} onClick={() => send(p)}>
                        <span>{p}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </section>
            <div className="dock">
              {speedTip}
              {composer(false)}
            </div>
          </>
        )}
      </main>

      {drawerDoc && (
        <DocDrawer
          doc={drawerDoc}
          model={model}
          language={language}
          summaryTypes={summaryTypes}
          notify={notify}
          onClose={() => setDrawerDocId(null)}
          onSummarySaved={(id, summary) =>
            setDocuments((list) => list.map((d) => (d.id === id ? { ...d, summary, has_summary: true } : d)))
          }
        />
      )}

      {dragging && (
        <div className="dropzone" aria-hidden="true">
          <div className="dropzone-card">
            <Icon name="upload" size={28} />
            <strong>Drop to add to your library</strong>
            <span>PDF, Word, PowerPoint, Excel, CSV, text, HTML and images</span>
          </div>
        </div>
      )}

      <input ref={fileInput} type="file" hidden multiple accept={ACCEPT} onChange={(e) => { handleFiles(e.target.files); e.target.value = ""; }} />
      {themeOpen && <ThemePanel theme={theme} onChange={setTheme} onClose={() => setThemeOpen(false)} warnings={themeWarnings} />}
      <Toasts toasts={toasts} onDismiss={(id) => setToasts((t) => t.filter((x) => x.id !== id))} />
    </div>
  );
}
