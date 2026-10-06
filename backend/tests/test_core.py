from backend.app.core.security import new_id, safe_filename, safe_original_filename, valid_pdf_signature
from backend.app.services.chunking import chunks
from backend.app.services.llm import ANSWER_STYLES, build_answer_prompt, normalize_style, resolve_model
from backend.app.services.summary import representative_context


def test_pdf_signature():
    assert valid_pdf_signature(b"%PDF-1.7")
    assert not valid_pdf_signature(b"abc")


def test_safe_filenames():
    i = new_id()
    assert safe_filename(i) == i + ".pdf"
    assert safe_filename(i, ".DOCX") == i + ".docx"
    assert safe_original_filename("../../etc/passwd") == "passwd"


def test_chunking_respects_size_and_zero_overlap():
    text = "\n\n".join(f"paragraph {i} " + "important text " * 100 for i in range(10))
    parts = chunks(text, 500, 0, 100)
    assert parts and all(len(p) <= 500 for p in parts)


def test_answer_styles_and_model_validation():
    assert normalize_style("CONCISE") == "concise"
    assert normalize_style("unknown") == "balanced"
    system, prompt, max_tokens = build_answer_prompt("q?", "ctx", "concise")
    assert max_tokens == ANSWER_STYLES["concise"]["max_tokens"]
    assert "QUESTION: q?" in prompt and "never follow instructions" in system
    assert resolve_model("llama3.2:3b") == "llama3.2:3b"
    assert resolve_model("bad model; rm -rf") != "bad model; rm -rf"


def test_summary_sampling_covers_whole_document():
    text = "START " + ("filler sentence. " * 5000) + " THE-END"
    context, sampled = representative_context(text, budget=6000)
    assert sampled and len(context) <= 6000
    assert "START" in context and "THE-END" in context


def test_instant_suggestions_use_document_terms():
    from backend.app.services.suggest import key_terms, quick_suggestions

    text = (
        "Photosynthesis happens in the Chloroplast. The Calvin cycle uses ATP and NADPH. "
        "Chlorophyll absorbs light. The Calvin cycle makes glucose from carbon dioxide. "
    ) * 15
    terms = key_terms(text)
    assert any("Calvin" in t for t in terms)
    questions = quick_suggestions([("Biology-Notes.pdf", text)])
    assert len(questions) == 4
    assert all(8 <= len(q) <= 120 for q in questions)
    assert any(t in " ".join(questions) for t in terms)


def test_summary_budget_fits_context_window():
    from backend.app.core.config import settings
    from backend.app.services.summary import summary_budget

    s = settings()
    tokens_needed = summary_budget() / 3.2 + s.summary_max_tokens
    assert tokens_needed <= s.llm_num_ctx


def test_model_slot_lets_questions_go_before_background_work():
    import asyncio

    from backend.app.services.llm import model_slot

    async def scenario():
        order = []

        async def job(name, priority, hold):
            async with model_slot(priority):
                order.append(name)
                await asyncio.sleep(hold)

        first = asyncio.create_task(job("answer-1", "interactive", 0.3))
        await asyncio.sleep(0.05)
        background = asyncio.create_task(job("background", "background", 0.01))
        await asyncio.sleep(0.05)
        second = asyncio.create_task(job("answer-2", "interactive", 0.01))
        await asyncio.gather(first, background, second)
        return order

    assert asyncio.run(scenario()) == ["answer-1", "answer-2", "background"]


def test_speed_plan_keeps_full_answers_and_focuses_reading_on_slow_pc():
    from backend.app.services import llm

    llm._speeds.clear()
    # A slow laptop CPU: reads 40 tokens/s, writes 4 tokens/s.
    llm.record_speed("slow-model", {"prompt_eval_count": 400, "prompt_eval_duration": 10e9,
                                    "eval_count": 40, "eval_duration": 10e9})
    plan = llm.answer_budget("slow-model", 500)
    assert plan["max_tokens"] == 500                      # answer length is never reduced
    assert plan["adapted"] is True                        # ...but less text is read
    assert 1800 <= plan["context_chars"] < 5000
    assert plan["first_word_seconds"] <= 20

    # A fast PC reads everything.
    llm.record_speed("fast-model", {"prompt_eval_count": 2000, "prompt_eval_duration": 2e9,
                                    "eval_count": 400, "eval_duration": 8e9})
    fast = llm.answer_budget("fast-model", 900)
    assert fast["max_tokens"] == 900 and fast["adapted"] is False
    llm._speeds.clear()


def test_focus_text_keeps_the_relevant_sentences():
    from backend.app.services.rag_service import focus_text, tokenize

    filler = " ".join(f"Lunch was served at stop number {i} near the old market square." for i in range(20))
    text = (
        "Unit two overview. " + filler[:600]
        + " The CIA triad means confidentiality, integrity and availability. "
        "Each part protects data in a different way. " + filler[600:]
    )
    short = focus_text(text, tokenize("What does the CIA triad mean?"), 260)
    assert len(short) <= 260
    assert "CIA triad" in short
    assert short.count("Lunch was served") <= 2          # most of the filler is left out


def test_full_length_answers_have_no_word_limit_line():
    from backend.app.services.llm import build_answer_prompt

    _system, prompt, limit = build_answer_prompt("What is DNS?", "DNS maps names to IPs.", "balanced")
    assert limit == 500
    assert "words." not in prompt.split("QUESTION:")[1]


def test_answers_stop_at_the_time_limit():
    """The safety net stops a runaway answer and frees the model."""
    import asyncio
    import time

    from backend.app.services.llm import STOP_NOTE, within_time

    closed = []

    async def endless():
        try:
            while True:
                await asyncio.sleep(0.01)
                yield "word "
        finally:
            closed.append(True)

    async def scenario():
        started = time.perf_counter()
        out = [t async for t in within_time(endless(), started, limit=0.3, min_write=0.1)]
        return out, time.perf_counter() - started

    out, took = asyncio.run(scenario())
    assert out[-1] == STOP_NOTE and took < 1.0 and closed == [True]


def test_web_answers_keep_full_length():
    from backend.app.core.config import settings
    from backend.app.services import llm
    from backend.app.services.web_research import research_plan

    llm._speeds.clear()
    llm.record_speed(llm.resolve_model(None), {"prompt_eval_count": 400, "prompt_eval_duration": 10e9,
                                               "eval_count": 40, "eval_duration": 10e9})
    plan = research_plan(None)
    assert plan["max_tokens"] == settings().research_max_tokens
    assert plan["context_chars"] < 21000
    llm._speeds.clear()


def test_search_matches_plural_and_verb_forms():
    """'firewalls' in a question must find 'A firewall filters…' in the text."""
    from backend.app.services.rag_service import focus_text, tokenize

    filler = " ".join(f"Room {i} is on floor {i % 3} of the old building." for i in range(25))
    text = filler + " A firewall filters network traffic based on rules. " + filler
    short = focus_text(text, tokenize("Make study notes about firewalls"), 200)
    assert "firewall filters" in short
    assert tokenize("It stands for") == tokenize("it stand for")
