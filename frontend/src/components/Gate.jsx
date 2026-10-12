import React, { useEffect, useState } from "react";
import { API } from "../api.js";
import Mark from "./Mark.jsx";

/**
 * Password screen. Shown only when the backend has ACCESS_PASSWORD set
 * (e.g. when Lumina is shared on the internet). Local use is unchanged.
 */
export default function Gate({ children }) {
  const [state, setState] = useState("checking"); // checking | locked | open
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const check = () =>
    fetch(`${API}/api/auth/status`)
      .then((r) => r.json())
      .then((d) => setState(!d.required || d.ok ? "open" : "locked"))
      .catch(() => setState("open")); // backend down: let the app show its own error

  useEffect(() => {
    check();
    const lock = () => setState("locked");
    window.addEventListener("lumina:locked", lock);
    return () => window.removeEventListener("lumina:locked", lock);
  }, []);

  const submit = async (e) => {
    e.preventDefault();
    if (!password || busy) return;
    setBusy(true);
    setError("");
    try {
      const r = await fetch(`${API}/api/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
      });
      if (!r.ok) throw new Error("Wrong password. Try again.");
      setPassword("");
      setState("open");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  if (state === "checking") return null;
  if (state === "open") return children;

  return (
    <div className="gate">
      <form className="gate-card" onSubmit={submit}>
        <Mark size={44} />
        <h1>Lumina</h1>
        <p>This Lumina is private. Enter the access password to continue.</p>
        <input
          type="password"
          autoFocus
          autoComplete="current-password"
          placeholder="Access password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          aria-label="Access password"
        />
        {error && <div className="gate-error" role="alert">{error}</div>}
        <button type="submit" disabled={busy || !password}>{busy ? "Checking…" : "Unlock"}</button>
      </form>
    </div>
  );
}
