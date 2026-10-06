"""Measure how well Lumina works on YOUR computer with YOUR model.

Start the backend first (python -m uvicorn backend.app.main:app --port 5001),
then run:

    python scripts/evaluate.py                 # all tests (about 10-25 min on a CPU)
    python scripts/evaluate.py --quick         # 6 core tests (about 5-10 min on a CPU)
    python scripts/evaluate.py --url http://127.0.0.1:5001

It uploads a small test document with known facts, asks questions whose
correct answers are known, and checks:

  * accuracy       – does the answer contain the right facts?
  * honesty        – does it admit when the document does not say something?
  * completeness   – does the answer end properly (not cut off)?
  * citations      – does it show the source passages?
  * whole-document – does "summarize" use the beginning AND the end?
  * memory         – does a follow-up question ("why is it important?") work?
  * cache          – is the same question answered instantly the second time?
  * speed          – time to the first word and total time for every style

Results are printed as a table and saved to evaluation-results.md.
The test document is deleted again at the end.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    import httpx
except ImportError:  # pragma: no cover
    sys.exit("Activate the virtual environment first:  .\\.venv\\Scripts\\Activate.ps1")

# --------------------------------------------------------------------------
# A small document with facts we can check. The beginning and the end contain
# unique facts so we can see whether summaries cover the whole file.
# --------------------------------------------------------------------------
DOCUMENT = """Lumina Test Document – Fundamentals of Network Security

Chapter 1. Introduction
This handbook was prepared for the Year 2 networking course. The opening chapter
explains that the course has exactly 12 lab sessions and that the final exam is
held in the Orion Hall.

Chapter 2. The CIA triad
The CIA triad is the base of every security policy. It stands for Confidentiality,
Integrity and Availability. Confidentiality means only authorised people can read
the data. Integrity means the data cannot be changed without detection. Availability
means systems and data are ready when users need them.

Chapter 3. Cryptography
Symmetric encryption uses one shared secret key for both encryption and decryption;
AES is the most common example. Asymmetric encryption uses a pair of keys – a public
key to encrypt and a private key to decrypt; RSA is the classic example. Asymmetric
encryption solves the key-sharing problem but is slower, so HTTPS combines both:
it uses asymmetric encryption to exchange a symmetric session key.
A hash function such as SHA-256 turns any input into a fixed-length digest.

Chapter 4. Common attacks
Phishing tricks users into revealing passwords through fake emails or websites.
A Denial of Service (DoS) attack floods a server with traffic so real users cannot
reach it; when many computers are used it is called a DDoS attack.
SQL injection inserts malicious SQL code into an input field to read or change a database.
A man-in-the-middle attack secretly intercepts communication between two parties.

Chapter 5. Ports and protocols
HTTPS uses port 443, HTTP uses port 80 and SSH uses port 22.
A firewall filters network traffic based on rules, and an Intrusion Detection
System (IDS) monitors traffic and raises alerts about suspicious activity.

Chapter 6. Conclusion
The closing chapter reminds students that the security mascot of the course is a
blue owl named Hootsworth, and that lab reports must be submitted every Friday.
"""

NOT_IN_DOC = ["not mention", "not contain", "does not", "doesn't", "no information", "not provided",
              "not specified", "not stated", "cannot find", "can't find", "not found", "isn't", "is not"]


def has_all(text: str, words: list[str]) -> bool:
    low = text.lower()
    return all(w.lower() in low for w in words)


def has_any(text: str, words: list[str]) -> bool:
    low = text.lower()
    return any(w.lower() in low for w in words)


def ends_properly(text: str) -> bool:
    t = text.strip().rstrip("*_` ")
    return bool(t) and (t[-1] in ".!?)]|:\"'”’" or t.endswith("```"))


class Lumina:
    def __init__(self, url: str) -> None:
        self.c = httpx.Client(base_url=url.rstrip("/"), timeout=httpx.Timeout(900, connect=10))

    def health(self) -> dict:
        return self.c.get("/api/health").json()

    def upload(self) -> str:
        r = self.c.post("/api/documents/upload",
                        files={"file": ("lumina-test-network-security.txt", DOCUMENT.encode(), "text/plain")})
        r.raise_for_status()
        doc_id = r.json()["id"]
        for _ in range(600):
            d = self.c.get(f"/api/documents/{doc_id}").json()
            if d["status"] == "completed":
                return doc_id
            if d["status"] == "failed":
                raise RuntimeError(f"Upload failed: {d.get('error')}")
            time.sleep(0.5)
        raise RuntimeError("The document was not ready after 5 minutes.")

    def new_chat(self, doc_id: str) -> str:
        return self.c.post("/api/chats", json={"document_ids": [doc_id], "title": "Lumina evaluation"}).json()["id"]

    def ask(self, chat_id: str, question: str, style: str = "balanced", regenerate: bool = False) -> dict:
        body = {"question": question, "style": style}
        if regenerate:
            body = {"regenerate": True, "style": style}
        t0 = time.perf_counter()
        first = None
        answer, sources, stats, error = "", [], {}, None
        with self.c.stream("POST", f"/api/chats/{chat_id}/messages/stream", json=body) as r:
            for line in r.iter_lines():
                if not line.startswith("data:"):
                    continue
                e = json.loads(line[5:])
                if e["type"] == "sources":
                    sources = e.get("sources", [])
                elif e["type"] == "token":
                    first = first or time.perf_counter() - t0
                    answer += e["content"]
                elif e["type"] == "done":
                    stats = e.get("stats", {})
                elif e["type"] == "error":
                    error = e.get("message")
        return {
            "answer": answer, "sources": sources, "stats": stats, "error": error,
            "first": first or 0.0, "total": time.perf_counter() - t0, "words": len(answer.split()),
        }

    def delete(self, doc_id: str) -> None:
        self.c.delete(f"/api/documents/{doc_id}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Evaluate Lumina on this computer.")
    ap.add_argument("--url", default="http://127.0.0.1:5001")
    ap.add_argument("--quick", action="store_true", help="only the 6 core tests")
    args = ap.parse_args()

    app = Lumina(args.url)
    try:
        health = app.health()
    except httpx.HTTPError:
        sys.exit(f"Lumina is not running at {args.url}. Start the backend first.")
    if not health.get("ollama_reachable"):
        sys.exit("The AI model is not reachable. Start Ollama (ollama serve) and try again.")

    model = health.get("default_model") or health.get("ollama_model")
    print(f"\nLumina {health.get('version')} · model {model} · {platform.system()} {platform.machine()}")
    print("Uploading the test document…")
    t0 = time.perf_counter()
    doc = app.upload()
    upload_s = time.perf_counter() - t0
    results: list[dict] = []

    def record(tid: str, area: str, question: str, ok: bool, res: dict | None, note: str = "") -> None:
        row = {
            "id": tid, "area": area, "question": question, "pass": ok, "note": note,
            "first": round(res["first"], 1) if res else None,
            "total": round(res["total"], 1) if res else None,
            "words": res["words"] if res else None,
            "answer": (res["answer"] if res else "")[:400],
            "sources": len(res["sources"]) if res else 0,
        }
        results.append(row)
        mark = "PASS" if ok else "FAIL"
        timing = f"{row['first']:>5}s / {row['total']:>6}s" if res else ""
        print(f"  [{mark}] {tid:<5} {area:<16} {timing}  {note}")

    try:
        record("T01", "Upload", "Upload a text file", upload_s < 60, None, f"ready in {upload_s:.1f}s")

        chat = app.new_chat(doc)
        print("Asking questions (each answer is written by your local model)…")

        r = app.ask(chat, "What does the CIA triad stand for?")
        record("T02", "Accuracy", "What does the CIA triad stand for?",
               not r["error"] and has_all(r["answer"], ["confidentiality", "integrity", "availability"]), r)

        r = app.ask(chat, "Why is it important for a security policy?")
        record("T03", "Follow-up memory", "Why is it important for a security policy? (follow-up)",
               not r["error"] and has_any(r["answer"], ["confidential", "integrity", "availab", "base", "foundation"]), r)

        r = app.ask(chat, "Which port does HTTPS use, and which port does SSH use?")
        record("T04", "Accuracy (numbers)", "Which port does HTTPS use, and SSH?",
               not r["error"] and has_all(r["answer"], ["443", "22"]), r)

        r = app.ask(chat, "Who is the principal of the college and what is their phone number?")
        record("T05", "Honesty", "Who is the principal? (not in the document)",
               not r["error"] and has_any(r["answer"], NOT_IN_DOC), r, "should say the document does not say")

        r = app.ask(chat, "Give me a summary of this document.")
        covers = has_any(r["answer"], ["12 lab", "orion", "introduction", "course"]) and has_any(
            r["answer"], ["hootsworth", "owl", "friday", "conclusion", "port", "443", "firewall", "ids"])
        overview = bool(r["sources"]) and all(s.get("retrieval") == "overview" for s in r["sources"])
        record("T06", "Whole-document", "Give me a summary of this document.",
               not r["error"] and covers and overview, r,
               "uses beginning and end" if covers else "missed the beginning or the end")

        if not args.quick:
            r = app.ask(chat, "Compare symmetric and asymmetric encryption.", style="table")
            record("T07", "Table style", "Compare symmetric and asymmetric encryption (Table)",
                   not r["error"] and "|" in r["answer"] and has_all(r["answer"], ["aes", "rsa"]), r)

            r = app.ask(chat, "Explain a DoS attack.", style="simple")
            record("T08", "Explain simply", "Explain a DoS attack (Explain simply)",
                   not r["error"] and has_any(r["answer"], ["flood", "traffic", "overwhelm"]), r)

            r = app.ask(chat, "List the common attacks described.", style="bullets")
            found = sum(has_any(r["answer"], [w]) for w in ["phishing", "denial", "sql", "middle"])
            record("T09", "Bullet points", "List the common attacks (Bullet points)",
                   not r["error"] and found >= 3, r, f"{found}/4 attacks found")

            r = app.ask(chat, "Explain how HTTPS uses both kinds of encryption.", style="detailed")
            record("T10", "Detailed", "How does HTTPS use both kinds of encryption? (Detailed)",
                   not r["error"] and has_any(r["answer"], ["session key", "symmetric"]) and has_any(r["answer"], ["asymmetric", "public"]), r)

            r = app.ask(chat, "What is a hash function?", style="quotes")
            record("T11", "Exact quotes", "What is a hash function? (With exact quotes)",
                   not r["error"] and has_any(r["answer"], ["sha-256", "fixed-length", "digest"]), r)

            r = app.ask(chat, "Make study notes about firewalls and IDS.", style="study")
            record("T12", "Study notes", "Study notes about firewalls and IDS",
                   not r["error"] and has_all(r["answer"], ["firewall"]) and has_any(r["answer"], ["ids", "intrusion"]), r)

        # cache: repeat T02 in a fresh chat (same history) -> instant
        chat2 = app.new_chat(doc)
        app.ask(chat2, "What does the CIA triad stand for?")
        r = app.ask(app.new_chat(doc), "What does the CIA triad stand for?")
        record("T13", "Answer cache", "Same question again (should be instant)",
               not r["error"] and (r["stats"].get("cached") or r["total"] < 2), r)

        complete = [x for x in results if x["answer"] and x["id"] not in ("T13",)]
        cut = [x["id"] for x in complete if not ends_properly(x["answer"])]
        record("T14", "Completeness", "Every answer ends properly (not cut off)", not cut, None,
               "all complete" if not cut else f"possibly cut: {', '.join(cut)}")
        cited = [x for x in results if x["id"] in ("T02", "T04", "T06")]
        no_src = [x["id"] for x in cited if x["sources"] == 0]
        record("T15", "Citations", "Answers show their source passages", not no_src, None,
               "all answers cite passages" if not no_src else f"no sources: {', '.join(no_src)}")
    finally:
        app.delete(doc)

    # ---------------------------------------------------------------- report
    passed = sum(1 for x in results if x["pass"])
    timed = [x for x in results if x["first"] is not None and x["id"] != "T13"]
    avg_first = sum(x["first"] for x in timed) / max(1, len(timed))
    avg_total = sum(x["total"] for x in timed) / max(1, len(timed))
    speed = health.get("speed", {}).get("models", {}).get(model, {})
    print(f"\nScore: {passed}/{len(results)} passed · average first word {avg_first:.1f}s · average answer {avg_total:.1f}s")

    lines = [
        f"# Lumina evaluation – {datetime.now():%Y-%m-%d %H:%M}",
        "",
        f"- Lumina {health.get('version')}, model **{model}**, {platform.system()} {platform.machine()}",
        f"- Measured model speed: {speed.get('words_per_second', '?')} words/s writing" if speed else "- Model speed: not measured yet",
        f"- **Score: {passed}/{len(results)} tests passed**",
        f"- Average time to first word: **{avg_first:.1f} s** · average full answer: **{avg_total:.1f} s**",
        "",
        "| ID | Area | Test | Result | First word | Total | Words | Note |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for x in results:
        lines.append(
            f"| {x['id']} | {x['area']} | {x['question']} | {'✅ pass' if x['pass'] else '❌ fail'} | "
            f"{'' if x['first'] is None else str(x['first']) + ' s'} | {'' if x['total'] is None else str(x['total']) + ' s'} | "
            f"{x['words'] or ''} | {x['note']} |"
        )
    lines += ["", "## Answers", ""]
    for x in results:
        if x["answer"]:
            lines += [f"**{x['id']} – {x['question']}**", "", "> " + x["answer"].replace("\n", "\n> "), ""]
    out = Path("evaluation-results.md")
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"Saved the full report to {out.resolve()}")


if __name__ == "__main__":
    main()
