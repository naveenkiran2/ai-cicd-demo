"""Optional LLM narrative adapter.

The bot's decisions (root cause, proposed change, safety verdict) are always
made by the deterministic rule engine. An LLM may *only* add an advisory,
human-friendly narrative on top. Nothing here is required to run the demo.

Enable Claude (optional):
    pip install anthropic
    export AI_BOT_LLM=claude
    export ANTHROPIC_API_KEY=...          # never commit this; never put it in config files
    export AI_BOT_LLM_MODEL=claude-opus-5-5   # optional override

Any error (no key, no SDK, network, refusal) falls back silently to the
rule-based narrator, so the pipeline never depends on an external service.
"""
import json
import os
import re
from typing import Optional, Protocol

from pipeline.lint import SECRET_PATTERNS

SYSTEM_PROMPT = (
    "You are a CI/CD incident analyst writing for engineering leadership. You receive a structured, "
    "already-verified diagnosis produced by a deterministic rule engine. Explain it in at most 150 words: "
    "what happened, why it matters, and what the safe next step is. Do not invent facts, files, or fixes "
    "beyond the provided data, and do not contradict its decision."
)


class Narrator(Protocol):
    name: str

    def narrate(self, diagnosis: dict) -> Optional[dict]:
        ...


class RuleBasedNarrator:
    """Default: the deterministic report already contains the narrative."""
    name = "rule-based"

    def narrate(self, diagnosis: dict) -> Optional[dict]:
        return None


def _redact(text: str) -> str:
    for _, pattern in SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return re.sub(r"(?i)(sk-ant-[A-Za-z0-9_\-]+)", "[REDACTED]", text)


def _llm_payload(d: dict) -> str:
    """Send the minimum necessary: no workspace files, only the structured findings."""
    keys = ("run_id", "status", "outcome", "failed_stage", "title", "executive_summary", "root_cause",
            "impact", "recommendation", "confidence", "decision", "proposed_changes")
    return _redact(json.dumps({k: d.get(k) for k in keys}, indent=1, default=str))


class ClaudeNarrator:
    name = "claude"

    def __init__(self, model: str):
        import anthropic  # imported lazily so the SDK stays optional
        self.model = model
        self.client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment

    def narrate(self, diagnosis: dict) -> Optional[dict]:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=2000,
            system=SYSTEM_PROMPT,
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": "Diagnosis JSON:\n" + _llm_payload(diagnosis)}],
        )
        if response.stop_reason == "refusal":
            return None
        text = "".join(block.text for block in response.content if block.type == "text").strip()
        return {"provider": "anthropic", "model": self.model, "text": text, "advisory": True} if text else None


def get_narrator() -> Narrator:
    if os.environ.get("AI_BOT_LLM", "").lower() != "claude" or not os.environ.get("ANTHROPIC_API_KEY"):
        return RuleBasedNarrator()
    try:
        return ClaudeNarrator(os.environ.get("AI_BOT_LLM_MODEL", "claude-opus-5-5"))
    except Exception:  # SDK missing or misconfigured -> deterministic fallback
        return RuleBasedNarrator()


def enrich(diagnosis: dict) -> dict:
    narrator = get_narrator()
    try:
        narrative = narrator.narrate(diagnosis)
    except Exception as exc:  # network / API errors never break the pipeline
        diagnosis["llm_note"] = f"LLM narrative unavailable ({type(exc).__name__}); rule-based report only"
        return diagnosis
    diagnosis["narrator"] = narrator.name
    if narrative:
        diagnosis["llm_narrative"] = narrative
    return diagnosis
