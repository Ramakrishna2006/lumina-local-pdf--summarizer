import React from "react";

/**
 * Lumina's mark: four soft petals around a centre.
 * `active` = Lumina is thinking or writing – the petals slowly turn and
 * breathe (see .mark.is-active in styles.css).
 */
export default function Mark({ size = 28, active = false, className = "" }) {
  return (
    <span className={`mark ${active ? "is-active" : ""} ${className}`} style={{ width: size, height: size }} aria-hidden="true">
      <svg viewBox="0 0 32 32" width={size} height={size}>
        <g className="mark-petals">
          <path d="M16 2.5c2.2 0 3.4 4.6 3.4 8.1 0 2.4-1.5 4-3.4 4s-3.4-1.6-3.4-4c0-3.5 1.2-8.1 3.4-8.1Z" />
          <path d="M29.5 16c0 2.2-4.6 3.4-8.1 3.4-2.4 0-4-1.5-4-3.4s1.6-3.4 4-3.4c3.5 0 8.1 1.2 8.1 3.4Z" />
          <path d="M16 29.5c-2.2 0-3.4-4.6-3.4-8.1 0-2.4 1.5-4 3.4-4s3.4 1.6 3.4 4c0 3.5-1.2 8.1-3.4 8.1Z" />
          <path d="M2.5 16c0-2.2 4.6-3.4 8.1-3.4 2.4 0 4 1.5 4 3.4s-1.6 3.4-4 3.4c-3.5 0-8.1-1.2-8.1-3.4Z" />
        </g>
        <circle className="mark-core" cx="16" cy="16" r="2.6" />
      </svg>
    </span>
  );
}
