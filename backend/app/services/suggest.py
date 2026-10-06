"""Instant suggested questions – no AI model call.

Writing suggestions with the LLM can take a minute on a CPU-only PC and would
block real questions in Ollama's queue. Instead we pick the document's key
terms (repeated capitalised phrases, acronyms and frequent long words) and
fill them into question templates. This takes a few milliseconds.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

_SKIP = {
    "the", "this", "that", "these", "those", "there", "their", "they", "then", "than", "when", "where",
    "what", "which", "while", "with", "within", "without", "from", "into", "onto", "about", "above",
    "after", "before", "between", "during", "for", "and", "but", "not", "are", "was", "were", "has",
    "have", "had", "can", "could", "should", "would", "will", "may", "might", "must", "also", "such",
    "each", "every", "other", "some", "many", "more", "most", "very", "only", "just", "both", "all",
    "any", "how", "why", "who", "its", "our", "your", "you", "use", "used", "using", "example",
    "examples", "figure", "table", "page", "pages", "slide", "slides", "unit", "module", "chapter",
    "section", "introduction", "conclusion", "summary", "contents", "lecture", "notes", "note",
    "part", "however", "therefore", "because", "following", "different", "important", "include",
    "includes", "including", "based", "called", "known", "first", "second", "third", "one", "two",
    "three", "new", "type", "types", "way", "ways", "data", "information", "system", "systems",
    "process", "processes", "fig", "ref", "etc", "e.g", "i.e", "http", "https", "www", "com",
    # common general words that make poor topics
    "contain", "contains", "convert", "converts", "provide", "provides", "produce", "produces",
    "require", "requires", "involve", "involves", "describe", "describes", "consider", "increase",
    "decrease", "through", "around", "another", "several", "general", "specific",
    "possible", "usually", "although", "whether", "results", "result", "number", "numbers",
    "various", "levels", "level", "common", "simple", "similar", "certain", "present", "allows",
    "allow", "makes", "make", "made", "given", "gives", "shown", "shows", "takes", "taken",
    "become", "becomes", "remain", "remains", "towards", "toward", "across", "against",
    "behind", "beyond", "people", "things", "thing", "something", "anything", "everything",
    "students", "student", "question", "questions", "answer", "answers", "topic", "topics",
}

_PHRASE = re.compile(r"\b(?:[A-Z][a-zA-Z0-9\-]{1,}[ \t]+){0,2}[A-Z][a-zA-Z0-9\-]{1,}\b")  # one line only
_ACRONYM = re.compile(r"\b[A-Z][A-Za-z]*[A-Z][A-Za-z]*\b")  # DNA, DDoS, HTTPS
_WORD = re.compile(r"\b[a-z][a-z\-]{5,}\b")
# Verbs/adjectives/adverbs make poor topics ("floated", "showing", "faster").
_WEAK_ENDINGS = ("ed", "ing", "ly", "er", "est", "ous", "ful", "ive", "able", "ible")


def _sentence_start(text: str, index: int) -> bool:
    before = text[max(0, index - 3):index].rstrip(" \t*#>-")
    return not before or before[-1] in ".!?:\n"


def _clean_phrase(phrase: str) -> str:
    words = phrase.split()
    while words and words[0].lower() in _SKIP:
        words.pop(0)
    while words and words[-1].lower() in _SKIP:
        words.pop()
    return " ".join(words)


def key_terms(text: str, limit: int = 6) -> list[str]:
    """Most characteristic terms of a text, best first."""
    sample = (text or "")[:40000]
    scores: Counter = Counter()
    surface: dict[str, Counter] = {}

    def add(term: str, weight: float) -> None:
        term = term.strip(" -")
        key = term.lower()
        if len(key) < 3 or key in _SKIP or key.isdigit() or any(ch.isdigit() for ch in key[:1]):
            return
        scores[key] += weight
        surface.setdefault(key, Counter())[term] += 1

    for match in _PHRASE.finditer(sample):
        phrase = _clean_phrase(match.group(0))
        if not phrase:
            continue
        words = len(phrase.split())
        start = match.start() + max(0, match.group(0).find(phrase))   # after a dropped "The"
        # A single capitalised word at the start of a sentence is usually just grammar.
        if words == 1 and _sentence_start(sample, start) and not _ACRONYM.fullmatch(phrase):
            continue
        if words == 1 and not _ACRONYM.fullmatch(phrase):
            # "Calvin cycle", "Newton's law": keep the noun that follows a name.
            follow = re.match(r"[ \t]+([a-z]{4,})\b", sample[match.end():match.end() + 30])
            if follow and follow.group(1) not in _SKIP and not follow.group(1).endswith(_WEAK_ENDINGS):
                phrase, words = f"{phrase} {follow.group(1)}", 2
        add(phrase, 1.0 + 0.6 * (words - 1))
    for match in _ACRONYM.finditer(sample):
        if 2 <= len(match.group(0)) <= 8:
            add(match.group(0), 1.2)
    for word, count in Counter(_WORD.findall(sample)).items():
        verb_like = word.endswith("s") and not word.endswith(("ss", "is", "us", "sis"))
        if count >= 3 and len(word) >= 7 and not word.endswith(_WEAK_ENDINGS) and not verb_like:
            # Longer words are more likely to be technical terms.
            add(word, 0.12 * count * (len(word) - 4))

    ranked: list[str] = []
    for key, score in scores.most_common(60):
        if score < 2:
            break
        # Skip a term that is just part of a phrase we already picked (or vice versa).
        if any(key in r.lower() or r.lower() in key for r in ranked):
            continue
        ranked.append(surface[key].most_common(1)[0][0])
        if len(ranked) >= limit:
            break
    return ranked


def quick_suggestions(documents: list[tuple[str, str]]) -> list[str]:
    """documents: [(filename, text)] -> 4 specific questions."""
    terms: list[str] = []
    for _name, text in documents:
        for term in key_terms(text, 3):
            if term.lower() not in {t.lower() for t in terms}:
                terms.append(term)

    out: list[str] = []
    if len(documents) > 1:
        out.append("Compare the main ideas of the selected documents")
    if terms:
        out.append(f"What is {terms[0]} and why does it matter?")
    if len(terms) > 1:
        out.append(f"Explain {terms[1]} in simple words")
    name = Path(documents[0][0]).stem.replace("_", " ").replace("-", " ").strip() if documents else ""
    if name and len(documents) == 1:
        out.append(f"Summarize the key points of {name[:50]}")
    else:
        out.append("Summarize the key points in 5 bullets")
    out.append("Make 5 exam questions from this material")
    if len(terms) > 2:
        out.append(f"Explain {terms[2]} in simple words")
    for filler in ("List the key definitions I should know", "What are the most important facts and numbers?"):
        if len(out) >= 4:
            break
        out.append(filler)
    return out[:4]
