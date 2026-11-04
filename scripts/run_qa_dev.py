"""Opt-in paid DEV-only answer generation + human-review CSV. Never accesses TEST gold."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from marine_evidence.answer import answer_question, render, AnswerError
from marine_evidence.bm25 import BM25Index, read_chunks


def load_dev_questions(path: Path) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    selected = [r for r in rows if r.get("split") == "dev"]
    if not selected:
        raise ValueError("No DEV questions found")
    return selected


def main() -> None:
    p = argparse.ArgumentParser(description="Run grounded-answer DEV review (API calls opt-in)")
    p.add_argument("--chunks", type=Path, default=Path("data/chunks/word_safe/chunks.jsonl"))
    p.add_argument("--benchmark", type=Path, default=Path("evaluation/benchmark_v1.jsonl"))
    p.add_argument("--out-dir", type=Path, default=Path("data/evaluation/qa_dev"))
    p.add_argument("--model", default="gpt-5-mini")
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--limit", type=int, default=3, help="Max DEV questions to call (default 3)")
    p.add_argument("--execute", action="store_true", help="Actually make paid LLM API calls")
    args = p.parse_args()
    if args.limit < 1 or args.top_k < 1:
        p.error("--limit and --top-k must be positive")
    try:
        items = load_dev_questions(args.benchmark)[:args.limit]
        if not args.execute:
            print(f"DRY RUN: would call {args.model} for {len(items)} DEV questions (max {args.limit}), no API used")
            for row in items:
                print(f"  {row['id']}: {row['question']}")
            print("Add --execute to run real API calls and write manual review files")
            return
        index = BM25Index(read_chunks(args.chunks))
        args.out_dir.mkdir(parents=True, exist_ok=True)
        results_path = args.out_dir / "answers_dev.jsonl"
        grading_path = args.out_dir / "manual_review_dev.csv"
        with results_path.open("w", encoding="utf-8") as results, grading_path.open("w", newline="", encoding="utf-8-sig") as grades:
            writer = csv.DictWriter(grades, fieldnames=[
                "id", "task_type", "question", "expected_answerability", "expected_gold_answer",
                "required_facts", "forbidden_claims", "model_status", "model_response", "model_citations",
                "manual_fact_coverage_0_to_1", "manual_citation_correct_0_or_1",
                "manual_unsupported_claim_0_or_1", "manual_abstention_correct_0_or_1", "review_notes"])
            writer.writeheader()
            for item in items:
                prediction = answer_question(item["question"], index, top_k=args.top_k, model=args.model)
                results.write(json.dumps({"id": item["id"], **prediction}, ensure_ascii=False) + "\n")
                results.flush()
                writer.writerow({
                    "id": item["id"], "task_type": item["task_type"],
                    "question": item["question"], "expected_answerability": item["answerability"],
                    "expected_gold_answer": item["gold_answer"],
                    "required_facts": json.dumps(item["required_facts"], ensure_ascii=False),
                    "forbidden_claims": json.dumps(item["forbidden_claims"], ensure_ascii=False),
                    "model_status": prediction["status"], "model_response": render(prediction),
                    "model_citations": json.dumps(prediction["citations"], ensure_ascii=False),
                    "manual_fact_coverage_0_to_1": "", "manual_citation_correct_0_or_1": "",
                    "manual_unsupported_claim_0_or_1": "", "manual_abstention_correct_0_or_1": "",
                    "review_notes": "",
                })
                grades.flush()
                print(f"{item['id']}: {prediction['status']} | cited {len(prediction['citations'])} chunks")
        print(f"Results: {results_path}\nHuman grading: {grading_path}")
    except (OSError, ValueError, KeyError, json.JSONDecodeError, AnswerError) as exc:
        p.exit(1, f"ERROR: {exc}\n")


if __name__ == "__main__":
    main()
