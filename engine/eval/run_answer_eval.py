# prism/engine/eval/run_answer_eval.py
"""Step 3: End-to-end answer evaluation with LLM-as-Judge.

Usage:
    python -m engine.eval.run_answer_eval --dataset results/<ts>/golden_dataset_v2.json
"""
import argparse
import csv
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from dotenv import load_dotenv
load_dotenv(_project_root / ".env")

from engine.app.config import settings
from engine.app.llm.client import chat
from backend.app.security.knowledge_scope import AuthorizedKnowledgeScope, sign_scope

ENGINE_URL = f"http://localhost:{settings.ENGINE_PORT}"
SCOPE_TTL_SECONDS = 600
RESULTS_DIR = Path(__file__).resolve().parent / "results"
JUDGE_FAITHFULNESS_WEIGHT = 0.4
JUDGE_RELEVANCE_WEIGHT = 0.3
JUDGE_COMPLETENESS_WEIGHT = 0.3


def build_judge_prompt(question: str, gold_chunks_text: str, answer: str) -> str:
    """Build the LLM-as-Judge evaluation prompt."""
    return f"""你是一个 RAG 问答质量评估器。请严格评估以下回答的质量。

## 问题
{question}

## 参考答案依据（来自知识库的相关片段）
{gold_chunks_text[:3000]}

## 模型回答
{answer[:3000]}

## 评估维度（1-5 分，整数）

1. **忠实度 (faithfulness)**：回答是否严格基于提供的知识库内容？
   - 5=完全基于知识库，无任何编造
   - 4=基本基于知识库，极少量合理推断
   - 3=基本基于知识库，有少量不准确或过度推断
   - 2=大量内容无法从知识库验证
   - 1=大量编造、幻觉，或与知识库矛盾

2. **相关性 (relevance)**：回答是否直接、精确地回应了问题？
   - 5=完全切题，直接回应
   - 4=基本切题，少量偏离
   - 3=部分相关，有偏题但大致方向对
   - 2=大部分内容与问题无关
   - 1=答非所问

3. **完整性 (completeness)**：回答是否覆盖了知识库中含有的关键要点？
   - 5=覆盖全部关键要点
   - 4=覆盖大部分要点，遗漏少量次要信息
   - 3=覆盖主要内容，遗漏部分相关信息
   - 2=遗漏大量关键信息
   - 1=几乎没有覆盖知识库要点

## 输出格式
只输出 JSON，不要解释：
{{"faithfulness": <1-5>, "relevance": <1-5>, "completeness": <1-5>, "rationale": "<一句话理由>"}}"""


def parse_judge_response(response_text: str) -> dict[str, Any]:
    """Parse the LLM judge's JSON response. Returns error sentinel (-1) on failure."""
    try:
        json_start = response_text.find("{")
        json_end = response_text.rfind("}") + 1
        if json_start >= 0 and json_end > json_start:
            data = json.loads(response_text[json_start:json_end])
            faithfulness = int(data.get("faithfulness", -1))
            relevance = int(data.get("relevance", -1))
            completeness = int(data.get("completeness", -1))

            # Clamp to 1-5
            faithfulness = max(1, min(5, faithfulness))
            relevance = max(1, min(5, relevance))
            completeness = max(1, min(5, completeness))

            overall = round(
                faithfulness * JUDGE_FAITHFULNESS_WEIGHT
                + relevance * JUDGE_RELEVANCE_WEIGHT
                + completeness * JUDGE_COMPLETENESS_WEIGHT,
                2,
            )
            return {
                "faithfulness": faithfulness,
                "relevance": relevance,
                "completeness": completeness,
                "overall": overall,
                "rationale": data.get("rationale", ""),
            }
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        print(f"  [!] Judge parse error: {e}", flush=True)

    return {
        "faithfulness": -1,
        "relevance": -1,
        "completeness": -1,
        "overall": -1,
        "rationale": "PARSE_ERROR",
    }


def parse_ndjson_events(lines: list[str]) -> dict[str, Any]:
    """Parse NDJSON chat stream events into structured data."""
    result: dict[str, Any] = {
        "answer": "",
        "sources": [],
        "token_count": 0,
        "tool_calls": 0,
        "status": "unknown",
    }

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        etype = event.get("type", "")
        data = event.get("data", {})

        if etype == "token":
            result["token_count"] += 1
            token_text = data.get("token", "")
            if isinstance(token_text, str):
                result["answer"] += token_text
        elif etype == "sources":
            sources = data.get("sources", [])
            if isinstance(sources, list):
                result["sources"] = sources
        elif etype == "tool_call":
            result["tool_calls"] += 1
        elif etype == "done":
            result["status"] = "done"
            if data.get("answer"):
                result["answer"] = data["answer"]
        elif etype == "error":
            result["status"] = "error"
            result["error"] = data.get("message", "unknown error")

    return result


def _gold_chunks_for_question(q: dict, db=None) -> str:
    """Build the gold chunk text block for the judge prompt.

    Uses the chunk_text from relevant_children directly (already populated
    during dataset generation). Falls back to DB load if texts are missing.
    """
    texts: list[str] = []
    for c in q.get("relevant_children", []):
        relevance = c.get("relevance", "context")
        chunk_text = c.get("chunk_text", "")
        if chunk_text:
            prefix = {"direct": "[★关键]", "partial": "[相关]", "context": "[背景]"}.get(relevance, "")
            texts.append(f"{prefix} {chunk_text[:500]}")

    if not texts:
        return "(无参考依据)"

    return "\n\n---\n".join(texts)


def _sign_scope(tenant_id: str, kb_uid: str) -> str:
    """Sign a knowledge scope token for Engine authorization."""
    now = int(time.time())
    scope = AuthorizedKnowledgeScope(
        actor_id="eval-runner",
        tenant_id=tenant_id,
        allowed_kb_uids=(kb_uid,),
        run_id=f"eval-{now}",
        expires_at=now + SCOPE_TTL_SECONDS,
    )
    return sign_scope(scope, settings.KNOWLEDGE_SCOPE_SECRET)


def _aggregate_judge_scores(results: list[dict]) -> dict[str, Any]:
    """Compute aggregate judge score statistics."""
    dims = ["faithfulness", "relevance", "completeness", "overall"]
    valid = [r for r in results if r.get("judge_faithfulness", -1) >= 0]

    agg: dict[str, Any] = {"evaluated": len(valid), "total": len(results)}
    for dim in dims:
        key = f"judge_{dim}"
        values = [r[key] for r in valid if key in r and r[key] is not None]
        if not values:
            continue
        n = len(values)
        mean = sum(values) / n
        sorted_vals = sorted(values)
        agg[dim] = {
            "mean": round(mean, 2),
            "median": sorted_vals[n // 2],
            "min": min(values),
            "max": max(values),
            "dist": {str(i): values.count(i) for i in range(1, 6)},
        }

    return agg


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Prism End-to-End Answer Evaluation")
    parser.add_argument("--dataset", required=True, help="Path to golden_dataset_v2.json")
    parser.add_argument("--tenant-id", default="default-tenant")
    parser.add_argument("--kb-uid", required=True)
    parser.add_argument("--engine-url", default=ENGINE_URL, help="Engine URL")
    parser.add_argument("--judge-model", default=None, help="LLM model for judging (default: same as LLM_MODEL)")
    parser.add_argument("--skip-llm-judge", action="store_true", help="Skip LLM judging (collect answers only)")
    parser.add_argument("--dry-run", action="store_true", help="Test first 3 queries only")
    args = parser.parse_args(argv)

    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        print(f"[!] Dataset not found: {dataset_path}")
        sys.exit(1)

    run_dir = dataset_path.parent
    print("=" * 60)
    print("Prism End-to-End Answer Evaluation")
    print("=" * 60)
    print(f"Dataset: {dataset_path}")
    print(f"Engine: {args.engine_url}")
    print(f"Judge model: {args.judge_model or settings.LLM_MODEL}")
    print(f"Dry run: {args.dry_run}")

    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    queries = dataset["queries"]
    if args.dry_run:
        queries = queries[:3]

    # Get KB info (index_generation, graph_generation) for scope
    from sqlalchemy import create_engine as _ce, text
    from sqlalchemy.orm import sessionmaker as _sm

    db_engine = _ce(settings.DATABASE_URL, pool_pre_ping=True)
    db = _sm(bind=db_engine)()
    topic = db.execute(
        text("SELECT active_index_generation, active_graph_generation FROM knowledge_topic WHERE kb_uid = :kb"),
        {"kb": args.kb_uid},
    ).fetchone()
    db.close()

    if topic is None:
        print(f"[!] KB not found: {args.kb_uid}")
        sys.exit(1)

    # Sign scope
    scope_token = _sign_scope(args.tenant_id, args.kb_uid)

    print(f"\n[1/3] Running answer evaluation ({len(queries)} queries)...")
    results: list[dict] = []
    failures: list[dict] = []
    client = httpx.Client(timeout=120.0)

    for i, q in enumerate(queries):
        qid = q["id"]
        question = q["question"]
        print(f"  [{i + 1}/{len(queries)}] {qid} | {question[:60]}...", flush=True)

        try:
            t0 = time.perf_counter()
            response = client.stream(
                "POST",
                f"{args.engine_url}/chat/answer",
                json={
                    "query": question,
                    "history": [],
                    "deep_search_enabled": q.get("question_type") == "cross_paper",
                    "deep_search_depth": "standard",
                    "rag_max_iterations": 5,
                },
                headers={"x-prism-knowledge-scope": scope_token},
            )
            ttfb_ms = round((time.perf_counter() - t0) * 1000)

            lines = []
            first_line = True
            for line in response.iter_lines():
                if first_line:
                    ttfb_ms = round((time.perf_counter() - t0) * 1000)
                    first_line = False
                lines.append(line + "\n")

            total_latency_ms = round((time.perf_counter() - t0) * 1000)
            events = parse_ndjson_events(lines)

        except Exception as e:
            print(f"    [!] HTTP error: {e}", flush=True)
            failures.append({"query_id": qid, "question": question, "error": str(e)})
            continue

        # LLM Judge
        judge_scores: dict[str, Any] = {}
        if not args.skip_llm_judge and events["answer"]:
            try:
                gold_text = _gold_chunks_for_question(q)
                prompt = build_judge_prompt(question, gold_text, events["answer"])
                judge_response = chat(
                    [{"role": "user", "content": prompt}],
                    model=args.judge_model,
                )
                judge_scores = parse_judge_response(judge_response)
            except Exception as e:
                print(f"    [!] Judge error: {e}", flush=True)
                judge_scores = {"faithfulness": -1, "relevance": -1, "completeness": -1,
                               "overall": -1, "rationale": str(e)}

        result = {
            "query_id": qid,
            "question": question,
            "question_type": q.get("question_type", "?"),
            "paper_title": q.get("paper_titles", [q.get("item_title", "?")])[0],
            "answer": events.get("answer", "")[:2000],
            "source_count": len(events.get("sources", [])),
            "source_chunk_uids": ",".join(s.get("chunk_uid", "") for s in events.get("sources", [])),
            "ttfb_ms": ttfb_ms,
            "total_latency_ms": total_latency_ms,
            "tool_calls": events.get("tool_calls", 0),
            "status": events.get("status", "unknown"),
            "judge_faithfulness": judge_scores.get("faithfulness", -1),
            "judge_relevance": judge_scores.get("relevance", -1),
            "judge_completeness": judge_scores.get("completeness", -1),
            "judge_overall": judge_scores.get("overall", -1),
            "judge_rationale": judge_scores.get("rationale", ""),
        }
        results.append(result)

        score_str = f"F={judge_scores.get('faithfulness','?')} R={judge_scores.get('relevance','?')} C={judge_scores.get('completeness','?')}"
        print(f"    {score_str} | TTFB={ttfb_ms}ms Total={total_latency_ms}ms", flush=True)

    client.close()

    # Write outputs
    print(f"\n[2/3] Writing results...")

    # answer_detailed.csv
    csv_path = run_dir / "answer_detailed.csv"
    csv_fields = [
        "query_id", "question", "question_type", "paper_title",
        "answer", "source_count", "source_chunk_uids",
        "ttfb_ms", "total_latency_ms", "tool_calls", "status",
        "judge_faithfulness", "judge_relevance", "judge_completeness",
        "judge_overall", "judge_rationale",
    ]
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=csv_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)
    print(f"  CSV: {csv_path}")

    # answer_summary.json
    summary = {
        "meta": {
            "dataset": str(dataset_path),
            "run_at": datetime.now(timezone.utc).isoformat(),
            "total_queries": len(queries),
            "evaluated": len(results),
            "failed": len(failures),
            "judge_model": args.judge_model or settings.LLM_MODEL,
        },
        "judge_aggregates": _aggregate_judge_scores(results),
        "by_type": {},
        "by_paper": {},
        "latency": {
            "ttfb_p50": None, "ttfb_p95": None,
            "total_p50": None, "total_p95": None,
        },
        "failures": failures,
    }

    # Per-type aggregates
    type_groups: dict[str, list] = {}
    for r in results:
        type_groups.setdefault(r.get("question_type", "?"), []).append(r["judge_overall"])
    for t, scores in type_groups.items():
        valid = [s for s in scores if s is not None and s >= 0]
        if valid:
            summary["by_type"][t] = {"mean": round(sum(valid) / len(valid), 2), "count": len(valid)}

    # Per-paper aggregates
    paper_groups: dict[str, list] = {}
    for r in results:
        paper_groups.setdefault(r.get("paper_title", "?"), []).append(r["judge_overall"])
    for p, scores in paper_groups.items():
        valid = [s for s in scores if s is not None and s >= 0]
        if valid:
            summary["by_paper"][p] = {"mean": round(sum(valid) / len(valid), 2), "count": len(valid)}

    # Latency
    ttfb_vals = sorted([r["ttfb_ms"] for r in results if r.get("ttfb_ms")])
    total_vals = sorted([r["total_latency_ms"] for r in results if r.get("total_latency_ms")])
    if ttfb_vals:
        summary["latency"]["ttfb_p50"] = ttfb_vals[len(ttfb_vals) // 2]
        summary["latency"]["ttfb_p95"] = ttfb_vals[int(len(ttfb_vals) * 0.95)]
    if total_vals:
        summary["latency"]["total_p50"] = total_vals[len(total_vals) // 2]
        summary["latency"]["total_p95"] = total_vals[int(len(total_vals) * 0.95)]

    summary_path = run_dir / "answer_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  JSON: {summary_path}")

    # Low scores
    print(f"\n[3/3] Flagging bad cases...")
    bad_cases_dir = run_dir / "bad_cases"
    bad_cases_dir.mkdir(exist_ok=True)

    low_scores = []
    for r in results:
        faith = r.get("judge_faithfulness", -1)
        rel = r.get("judge_relevance", -1)
        if (faith >= 0 and faith < 3) or (rel >= 0 and rel < 3):
            low_scores.append(r)
            # Write bad case markdown
            case_md = f"""# Bad Case: {r['query_id']}

**Question:** {r['question']}
**Paper:** {r['paper_title']}
**Type:** {r.get('question_type', '?')}

## Answer
{r.get('answer', 'N/A')[:2000]}

## Judge Scores
- Faithfulness: {r.get('judge_faithfulness', '?')}
- Relevance: {r.get('judge_relevance', '?')}
- Completeness: {r.get('judge_completeness', '?')}
- Overall: {r.get('judge_overall', '?')}
- Rationale: {r.get('judge_rationale', '')}

## Sources Cited
{r.get('source_chunk_uids', 'None')}

## Metadata
- TTFB: {r.get('ttfb_ms', '?')}ms
- Total latency: {r.get('total_latency_ms', '?')}ms
- Tool calls: {r.get('tool_calls', '?')}
"""
            (bad_cases_dir / f"{r['query_id']}_bad_case.md").write_text(case_md, encoding="utf-8")

    if low_scores:
        low_csv_path = run_dir / "answer_low_scores.csv"
        with open(low_csv_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=csv_fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(low_scores)
        print(f"  Low scores: {len(low_scores)} queries flagged, see {low_csv_path}")
    else:
        print(f"  No low-score queries found.")

    # Terminal summary
    ja = summary["judge_aggregates"]
    print(f"\n{'=' * 60}")
    print("Answer Evaluation Summary")
    print(f"{'=' * 60}")
    print(f"Evaluated: {len(results)}/{len(queries)} (failed: {len(failures)})")
    for dim in ["faithfulness", "relevance", "completeness", "overall"]:
        if dim in ja:
            d = ja[dim]
            print(f"Judge {dim}: mean={d['mean']:.1f} median={d['median']} range=[{d['min']},{d['max']}]")
    print(f"Low scores flagged: {len(low_scores)}")
    print(f"Bad cases: {bad_cases_dir}")


if __name__ == "__main__":
    main()
