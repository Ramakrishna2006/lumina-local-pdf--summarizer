import React, { useMemo, useState } from "react";
import { extensionFor, fileNameFromLine, tokenize } from "../highlight.js";

// A small, dependency-free Markdown renderer.
// It builds React elements (never innerHTML), so text produced by the model
// or found inside a document can never inject scripts into the page.

function safeHref(url) {
  return /^(https?:|mailto:)/i.test(url) ? url : null;
}

function inline(text, keyPrefix = "i") {
  const out = [];
  const pattern =
    /(`[^`]+`)|(\*\*[^*]+\*\*)|(__[^_]+__)|(\*[^*\s][^*]*\*)|(_[^_\s][^_]*_)|(\[[^\]]+\]\([^)\s]+\))|(\[Source \d+\])/g;
  let last = 0;
  let match;
  let n = 0;
  while ((match = pattern.exec(text))) {
    if (match.index > last) out.push(text.slice(last, match.index));
    const token = match[0];
    const key = `${keyPrefix}-${n++}`;
    if (match[1]) out.push(<code key={key}>{token.slice(1, -1)}</code>);
    else if (match[2] || match[3]) out.push(<strong key={key}>{inline(token.slice(2, -2), key)}</strong>);
    else if (match[4] || match[5]) out.push(<em key={key}>{inline(token.slice(1, -1), key)}</em>);
    else if (match[6]) {
      const [, label, url] = token.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
      const href = safeHref(url);
      out.push(href ? <a key={key} href={href} target="_blank" rel="noreferrer">{label}</a> : label);
    } else if (match[7]) out.push(<span key={key} className="cite">{token.slice(1, -1).replace("Source ", "")}</span>);
    last = match.index + token.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

function downloadText(name, text) {
  const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function CodeBlock({ code, lang, filename }) {
  const [copied, setCopied] = useState(false);
  const [wrap, setWrap] = useState(false);
  const tokens = useMemo(() => tokenize(code, lang), [code, lang]);
  const name = filename || `snippet.${extensionFor(lang)}`;
  const lines = code.split("\n").length;
  return (
    <div className={`md-code ${wrap ? "is-wrapped" : ""}`}>
      <div className="md-code-bar">
        <span className="md-code-name" title={filename || lang}>{filename || lang || "code"}</span>
        <span className="md-code-tools">
          {lines > 12 && (
            <button type="button" onClick={() => setWrap((w) => !w)} aria-pressed={wrap} title="Wrap long lines">
              {wrap ? "No wrap" : "Wrap"}
            </button>
          )}
          <button type="button" onClick={() => downloadText(name.split("/").pop(), code + "\n")} title={`Download ${name}`}>
            Download
          </button>
          <button
            type="button"
            onClick={() => {
              navigator.clipboard?.writeText(code);
              setCopied(true);
              setTimeout(() => setCopied(false), 1400);
            }}
          >
            {copied ? "Copied" : "Copy"}
          </button>
        </span>
      </div>
      <pre><code>{tokens.map(([cls, text], i) => (cls ? <span key={i} className={`tk-${cls}`}>{text}</span> : text))}</code></pre>
    </div>
  );
}

function parseTable(lines) {
  const rows = lines.map((l) => l.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim()));
  const [head, , ...body] = rows;
  return { head, body };
}

export default function Markdown({ text = "" }) {
  const lines = String(text).replace(/\r\n/g, "\n").split("\n");
  const blocks = [];
  let i = 0;
  let key = 0;
  let pendingFile = null;

  while (i < lines.length) {
    const line = lines[i];

    if (/^```/.test(line)) {
      const info = line.slice(3).trim();
      const [lang, ...restInfo] = info.split(/[\s:]+/);
      const titled = restInfo.join(" ").replace(/^title=/, "").replace(/["']/g, "");
      const code = [];
      i++;
      while (i < lines.length && !/^```/.test(lines[i])) code.push(lines[i++]);
      i++;
      const filename = (/\.[\w]+$/.test(titled) ? titled : null) || pendingFile;
      pendingFile = null;
      blocks.push(<CodeBlock key={key++} code={code.join("\n")} lang={lang} filename={filename} />);
      continue;
    }
    if (line.trim()) pendingFile = fileNameFromLine(line);

    const heading = line.match(/^(#{1,4})\s+(.*)$/);
    if (heading) {
      const level = Math.min(heading[1].length + 1, 5);
      const Tag = `h${level}`;
      blocks.push(<Tag key={key++}>{inline(heading[2], `h${key}`)}</Tag>);
      i++;
      continue;
    }

    if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
      blocks.push(<hr key={key++} />);
      i++;
      continue;
    }

    if (/^\s*\|.*\|\s*$/.test(line) && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1])) {
      const tableLines = [];
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) tableLines.push(lines[i++]);
      const { head, body } = parseTable(tableLines);
      blocks.push(
        <div className="md-table" key={key++}>
          <table>
            <thead><tr>{head.map((c, j) => <th key={j}>{inline(c, `th${j}`)}</th>)}</tr></thead>
            <tbody>
              {body.map((r, ri) => (
                <tr key={ri}>{r.map((c, j) => <td key={j}>{inline(c, `td${ri}${j}`)}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      );
      continue;
    }

    if (/^\s*>/.test(line)) {
      const quote = [];
      while (i < lines.length && /^\s*>/.test(lines[i])) quote.push(lines[i++].replace(/^\s*>\s?/, ""));
      blocks.push(<blockquote key={key++}>{inline(quote.join(" "), `q${key}`)}</blockquote>);
      continue;
    }

    const listMatch = line.match(/^(\s*)([-*+]|\d+[.)])\s+(.*)$/);
    if (listMatch) {
      const ordered = /\d/.test(listMatch[2]);
      const items = [];
      while (i < lines.length) {
        const m = lines[i].match(/^(\s*)([-*+]|\d+[.)])\s+(.*)$/);
        if (m) {
          items.push({ depth: m[1].length >= 2 ? 1 : 0, text: m[3] });
          i++;
        } else if (lines[i].trim() && /^\s{2,}/.test(lines[i]) && items.length) {
          items[items.length - 1].text += " " + lines[i].trim();
          i++;
        } else break;
      }
      const Tag = ordered ? "ol" : "ul";
      blocks.push(
        <Tag key={key++}>
          {items.map((it, j) => (
            <li key={j} className={it.depth ? "nested" : undefined}>{inline(it.text, `li${key}-${j}`)}</li>
          ))}
        </Tag>
      );
      continue;
    }

    if (!line.trim()) {
      i++;
      continue;
    }

    const para = [];
    while (
      i < lines.length &&
      lines[i].trim() &&
      !/^(#{1,4}\s|```|\s*>|\s*([-*+]|\d+[.)])\s+|\s*\|)/.test(lines[i])
    ) {
      para.push(lines[i++]);
    }
    if (para.length === 0) {
      para.push(lines[i++]);
    }
    pendingFile = fileNameFromLine(para[para.length - 1]);
    blocks.push(<p key={key++}>{inline(para.join(" "), `p${key}`)}</p>);
  }

  return <div className="md">{blocks}</div>;
}
