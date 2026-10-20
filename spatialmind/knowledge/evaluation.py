"""Offline retrieval evaluation. Never uses an LLM to manufacture gold truth."""

import hashlib
import json
import time


def evaluate(store, benchmark):
    if "template" in benchmark.get("review_status", ""):
        raise ValueError("Complete and review the benchmark template before evaluation.")
    cases = benchmark.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Benchmark must contain nonempty cases.")
    results, recalls, reciprocal, abstentions, timings = [], [], [], [], []
    ids = set()
    for case in cases:
        if not case.get("id") or case["id"] in ids or not isinstance(case.get("expected_source_ids"), list):
            raise ValueError("Each case needs a unique ID and explicit expected_source_ids (empty for unanswerable).")
        ids.add(case["id"])
        expected = set(case["expected_source_ids"])
        if "answerable" in case and (not isinstance(case["answerable"], bool) or case["answerable"] != bool(expected)):
            raise ValueError("Answerability must agree with the reviewed expected-source set.")
        started = time.perf_counter()
        hits = store.search(case["question"], limit=5, scope=case.get("scope", "general"))
        elapsed = time.perf_counter() - started
        observed = list(dict.fromkeys(h["source_id"] for h in hits))
        if expected:
            recalls.append(len(expected & set(observed)) / len(expected))
            reciprocal.append(next((1 / (i + 1) for i, s in enumerate(observed) if s in expected), 0))
        else:
            abstentions.append(not hits)
        timings.append(elapsed)
        results.append({"id": case["id"], "retrieved_source_ids": observed, "expected_source_ids": sorted(expected), "seconds": elapsed})
    corpus = [{k: s[k] for k in ("id", "sha256", "version", "status", "enabled", "scope")} for s in store.list_sources()]
    return {"benchmark_sha256": hashlib.sha256(json.dumps(benchmark, sort_keys=True).encode()).hexdigest(),
            "corpus_sha256": hashlib.sha256(json.dumps(corpus, sort_keys=True).encode()).hexdigest(),
            "review_status": benchmark.get("review_status", "unreviewed"), "reviewer": benchmark.get("reviewer", ""),
            "cases": len(cases), "answerable_cases": len(recalls), "unanswerable_cases": len(abstentions),
            "source_recall_at_5_passages": sum(recalls) / len(recalls) if recalls else None,
            "source_mrr_at_5_passages": sum(reciprocal) / len(reciprocal) if reciprocal else None,
            "unanswerable_retrieval_abstention": sum(abstentions) / len(abstentions) if abstentions else None,
            "p95_retrieval_seconds": sorted(timings)[max(0, (95 * len(timings) + 99) // 100 - 1)],
            "semantic_support_precision": None, "biological_accuracy": None,
            "limitations": ["Retrieval benchmark only; not answer-quality or biological validation.",
                            "Reviewer fields are local attribution, not authenticated proof of expertise.",
                            "A relevant passage does not necessarily answer the question; lexical abstention is a limited measure."],
            "results": results}
