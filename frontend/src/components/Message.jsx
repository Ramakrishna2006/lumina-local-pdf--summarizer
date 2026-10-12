import React, { useEffect, useRef, useState } from "react";
import Icon from "./Icons.jsx";
import Mark from "./Mark.jsx";
import Markdown from "./Markdown.jsx";
import { seconds } from "../utils.js";
import { downloadUrl } from "../api.js";

function Sources({ sources }) {
  const [show, setShow] = useState(false);
  const [open, setOpen] = useState(null);
  if (!sources?.length) return null;
  const web = sources.some((s) => s.url);
  const files = [...new Set(sources.map((s) => s.filename || s.source).filter(Boolean))];

  return (
    <div className={`sources ${show ? "is-open" : ""}`}>
      <button type="button" className="sources-toggle" onClick={() => setShow((v) => !v)} aria-expanded={show}>
        <Icon name={web ? "globe" : "doc"} size={14} />
        {sources.length} {web ? "web sources" : sources.length === 1 ? "passage" : "passages"}
        <span className="sources-files">· {files.slice(0, 2).join(", ")}{files.length > 2 ? ` +${files.length - 2}` : ""}</span>
        <Icon name="chevron" size={14} className="chev" />
      </button>
      {show && (
        <div className="source-chips">
          {sources.map((s, i) => {
            const n = s.rank || i + 1;
            if (s.url) {
              return (
                <a key={i} className="source-chip" href={s.url} target="_blank" rel="noreferrer" title={s.snippet || s.url} style={{ "--i": i }}>
                  <span className="cite">{n}</span>
                  <span className="source-name">{s.title || s.source}</span>
                  <span className="source-where">{s.source}</span>
                </a>
              );
            }
            return (
              <button
                key={i}
                type="button"
                className={`source-chip ${open === i ? "is-open" : ""}`}
                onClick={() => setOpen(open === i ? null : i)}
                aria-expanded={open === i}
                style={{ "--i": i }}
              >
                <span className="cite">{n}</span>
                <span className="source-name">{s.filename}</span>
                <span className="source-where">part {(s.chunk_index ?? 0) + 1}</span>
              </button>
            );
          })}
        </div>
      )}
      {show && open != null && sources[open]?.preview && (
        <blockquote className="source-preview" key={open}>
          {sources[open].preview}…
        </blockquote>
      )}
    </div>
  );
}

const QUIZ_PROMPT = "Make a short 5-question multiple-choice quiz on this topic, with the answers at the end.";

function Meta({ message }) {
  const st = message.stats;
  if (!st) return null;
  if (st.cached) return <span className="meta-line"><Icon name="bolt" size={12} /> Instant – answered from memory</span>;
  if (st.total_ms == null) return null;
  return (
    <span className="meta-line" title="Time until the first word · total time">
      First words {seconds(st.first_token_ms)} · done in {seconds(st.total_ms)}
    </span>
  );
}

/**
 * Smooth streaming: words arrive from the model in bursts; we reveal them at
 * an even pace (catching up quickly, never lagging behind), so the answer
 * flows onto the screen instead of jumping.
 */
function useSmoothText(target, active) {
  const [shown, setShown] = useState(active ? 0 : target.length);
  const pos = useRef(shown);
  useEffect(() => {
    if (!active) {
      pos.current = target.length;
      setShown(target.length);
      return undefined;
    }
    let raf = 0;
    const tick = () => {
      const goal = target.length;
      if (pos.current < goal) {
        pos.current = Math.min(goal, pos.current + Math.max(1, Math.ceil((goal - pos.current) / 6)));
        setShown(pos.current);
        raf = requestAnimationFrame(tick);
      }
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, active]);
  return target.slice(0, shown);
}

/** "about 40 s left" while a slow PC prepares the answer. */
function Eta({ estimate, startedAt }) {
  const [, tick] = useState(0);
  useEffect(() => {
    const t = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, []);
  if (!estimate || !startedAt) return null;
  const left = Math.max(0, Math.round(estimate - (Date.now() - startedAt) / 1000));
  return <span className="eta">{left > 0 ? `first words in about ${left} s` : "almost there"}</span>;
}

/** Seconds since the image started, so a slow PC still shows progress. */
function Elapsed({ startedAt }) {
  const [, tick] = useState(0);
  useEffect(() => {
    const t = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, []);
  if (!startedAt) return null;
  const s = Math.round((Date.now() - startedAt) / 1000);
  return <span className="eta">{s} s · the first image also loads the model</span>;
}

function GeneratedImage({ image }) {
  const src = downloadUrl(image.url);
  return (
    <figure className="gen-image">
      <a href={src} target="_blank" rel="noreferrer" title="Open full size">
        <img src={src} alt={image.prompt} width={image.width} height={image.height} />
      </a>
      <figcaption>
        {image.width}×{image.height} · {seconds(Math.round(image.seconds * 1000))} · {image.model}
      </figcaption>
    </figure>
  );
}

export default function Message({ message, isLast, onRegenerate, canRegenerate, exportHref, onFollowUp }) {
  const [copied, setCopied] = useState(false);
  const isUser = message.role === "user";
  const text = useSmoothText(message.content || "", Boolean(message.streaming) && !isUser);

  if (isUser) {
    return (
      <div className="msg user">
        <div className="bubble">{message.content}</div>
      </div>
    );
  }

  const thinking = message.streaming && !message.content;
  const working = Boolean(message.streaming);

  return (
    <div className={`msg ai ${working ? "is-streaming" : ""} ${message.error ? "is-error" : ""}`}>
      <Mark size={26} active={working} className="msg-mark" />
      <div className="ai-body">
        {thinking ? (
          <div className="thinking" role="status">
            <span className="shimmer">
              {message.mode === "image"
                ? "Painting your image"
                : message.phase === "searching"
                ? message.mode === "web" ? "Searching the web" : "Finding the right passages"
                : `Reading ${message.sources?.length || ""} ${message.sources?.length === 1 ? "passage" : "passages"}`.replace("  ", " ")}
            </span>
            {message.mode === "image" && <Elapsed startedAt={message.startedAt} />}
            {message.phase !== "searching" && message.mode !== "image" && <Eta estimate={message.firstWord || message.estimate} startedAt={message.startedAt} />}
          </div>
        ) : message.error ? (
          <p className="msg-error"><Icon name="alert" size={16} /> {message.error}</p>
        ) : message.image ? (
          <GeneratedImage image={message.image} />
        ) : (
          <div className="answer">
            <Markdown text={text} />
            {working && <span className="stream-dot" aria-hidden="true" />}
          </div>
        )}

        <Sources sources={message.sources} />

        {!message.streaming && !message.error && (
          <div className="actions">
            {message.image && (
              <a className="act" href={downloadUrl(message.image.url)} download={`lumina-${message.image.id.slice(0, 8)}.png`}>
                <Icon name="download" size={14} /> Download
              </a>
            )}
            {message.image && isLast && onFollowUp && (
              <button type="button" className="act" onClick={() => onFollowUp(message.image.prompt)}>
                <Icon name="refresh" size={14} /> Another version
              </button>
            )}
            <button
              type="button"
              className="act icon-only"
              title={copied ? "Copied" : message.image ? "Copy prompt" : "Copy"}
              aria-label="Copy answer"
              onClick={() => {
                navigator.clipboard?.writeText(message.image ? message.image.prompt : message.content || "");
                setCopied(true);
                setTimeout(() => setCopied(false), 1500);
              }}
            >
              <Icon name={copied ? "check" : "copy"} size={15} />
            </button>
            {isLast && canRegenerate && (
              <button type="button" className="act icon-only" onClick={onRegenerate} title="Regenerate" aria-label="Regenerate answer">
                <Icon name="refresh" size={15} />
              </button>
            )}
            {exportHref && !message.image && (
              <a className="act icon-only" href={exportHref} title="Export chat as Markdown" aria-label="Export chat">
                <Icon name="download" size={15} />
              </a>
            )}
            {isLast && canRegenerate && onFollowUp && (
              <button type="button" className="act" onClick={() => onFollowUp(QUIZ_PROMPT)}>
                <Icon name="quiz" size={14} /> Quiz me
              </button>
            )}
            <Meta message={message} />
          </div>
        )}
      </div>
    </div>
  );
}
