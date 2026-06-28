from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError


class SearchDirective(BaseModel):
    strategy: str
    query: str = ""
    reason: str = ""
    limit: int = 8
    metadata: dict[str, Any] = Field(default_factory=dict)


class JudgeVerdict(BaseModel):
    status: str
    coverage_score: float
    grounding_score: float
    source_diversity_score: float
    conflict_score: float
    structure_score: float
    overall_score: float
    missing: list[str] = Field(default_factory=list)
    directives: list[SearchDirective] = Field(default_factory=list)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check whether the configured Deep Search judge model is usable.")
    parser.add_argument("--api-base", default="", help="Override DEEP_SEARCH_JUDGE_API_BASE/LLM_API_BASE.")
    parser.add_argument("--api-key", default="", help="Override DEEP_SEARCH_JUDGE_API_KEY/LLM_API_KEY.")
    parser.add_argument("--model", default="", help="Override DEEP_SEARCH_JUDGE_MODEL.")
    parser.add_argument("--timeout", type=float, default=60.0, help="OpenAI-compatible request timeout in seconds.")
    parser.add_argument("--save-response", default="", help="Optional path to save the raw model response.")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[3]
    load_dotenv(repo_root / ".env")

    model = args.model or os.getenv("DEEP_SEARCH_JUDGE_MODEL", "")
    api_base = args.api_base or os.getenv("DEEP_SEARCH_JUDGE_API_BASE", "") or os.getenv("LLM_API_BASE", "")
    api_key = args.api_key or os.getenv("DEEP_SEARCH_JUDGE_API_KEY", "") or os.getenv("LLM_API_KEY", "")

    missing = []
    if not model:
        missing.append("DEEP_SEARCH_JUDGE_MODEL or --model")
    if not api_base:
        missing.append("DEEP_SEARCH_JUDGE_API_BASE/LLM_API_BASE or --api-base")
    if not api_key:
        missing.append("DEEP_SEARCH_JUDGE_API_KEY/LLM_API_KEY or --api-key")
    if missing:
        print("[FAIL] Missing required config:")
        for item in missing:
            print(f"  - {item}")
        return 2

    print("[INFO] Judge model check")
    print(f"  repo_root: {repo_root}")
    print(f"  api_base: {api_base}")
    print(f"  model: {model}")
    print(f"  api_key: {_mask(api_key)}")

    client = OpenAI(base_url=api_base, api_key=api_key, timeout=args.timeout)
    try:
        response = client.chat.completions.create(
            model=model,
            messages=_messages(),
            temperature=0,
        )
    except Exception as exc:
        print("[FAIL] Request failed.")
        print(f"  {type(exc).__name__}: {exc}")
        return 1

    content = response.choices[0].message.content or ""
    print("[INFO] Raw response:")
    print(content)

    if args.save_response:
        output_path = Path(args.save_response)
        if not output_path.is_absolute():
            output_path = repo_root / output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")
        print(f"[INFO] Saved raw response: {output_path}")

    try:
        verdict = JudgeVerdict(**json.loads(_extract_json_object(content)))
    except json.JSONDecodeError as exc:
        print("[FAIL] Model returned non-JSON content.")
        print(f"  {exc}")
        return 1
    except ValidationError as exc:
        print("[FAIL] JSON did not match JudgeVerdict schema.")
        print(exc)
        return 1

    score_errors = _validate_scores(verdict)
    if score_errors:
        print("[FAIL] Score fields must be in [0, 1].")
        for error in score_errors:
            print(f"  - {error}")
        return 1

    if verdict.status not in {"complete", "incomplete"}:
        print("[FAIL] status must be complete or incomplete.")
        print(f"  status: {verdict.status}")
        return 1

    print("[PASS] Judge model is reachable and returns valid JudgeVerdict JSON.")
    print(f"  status: {verdict.status}")
    print(f"  overall_score: {verdict.overall_score}")
    print(f"  directives: {len(verdict.directives)}")
    return 0


def _messages() -> list[dict[str, str]]:
    payload = {
        "question": "Should the answer explain why scope-first retrieval avoids full chunk search?",
        "iteration": 1,
        "total_evidence_count": 2,
        "evidence": [
            {
                "evidence_id": "e1",
                "strategy": "source_backtrack",
                "source_kind": "document_chunk",
                "source_id": "chunk-1",
                "pku_id": "pku-1",
                "ckp_id": "ckp-1",
                "statement": "Scope Finder should narrow candidates through CKP, PKU, topic, and metadata before chunk search.",
                "snippet": "Use CKP/PKU/topic metadata first, then descend to source-backed chunks only inside the candidate scope.",
                "relation_type": "supports",
                "final_score": 0.88,
            },
            {
                "evidence_id": "e2",
                "strategy": "pku_requery",
                "source_kind": "personal_asset_unit",
                "source_id": "unit-2",
                "pku_id": "pku-2",
                "ckp_id": "ckp-1",
                "statement": "Judge can request PKU re-query or graph expansion when evidence is incomplete.",
                "snippet": "If evidence is insufficient, Judge returns directives for the Searcher.",
                "relation_type": "supports",
                "final_score": 0.74,
            },
        ],
        "required_json_schema": {
            "status": "complete|incomplete",
            "coverage_score": "float 0..1",
            "grounding_score": "float 0..1",
            "source_diversity_score": "float 0..1",
            "conflict_score": "float 0..1",
            "structure_score": "float 0..1",
            "overall_score": "float 0..1",
            "missing": ["short unmet requirement"],
            "directives": [{"strategy": "strategy name", "query": "query text", "reason": "why", "limit": 8}],
        },
    }
    return [
        {
            "role": "system",
            "content": (
                "You are the Deep Knowledge Search judge. Decide whether the retrieved evidence is "
                "sufficient to answer the user question. Return JSON only. Do not include markdown, "
                "analysis, chain-of-thought, or extra text."
            ),
        },
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def _extract_json_object(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    return text


def _validate_scores(verdict: JudgeVerdict) -> list[str]:
    errors: list[str] = []
    for field_name in [
        "coverage_score",
        "grounding_score",
        "source_diversity_score",
        "conflict_score",
        "structure_score",
        "overall_score",
    ]:
        value = getattr(verdict, field_name)
        if value < 0 or value > 1:
            errors.append(f"{field_name}={value}")
    return errors


def _mask(secret: str) -> str:
    if len(secret) <= 8:
        return "*" * len(secret)
    return f"{secret[:4]}...{secret[-4:]}"


if __name__ == "__main__":
    sys.exit(main())
