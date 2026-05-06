"""LLM context assembly for plan archive retrieval results."""

from __future__ import annotations

from typing import Any


class PlanArchiveContextService:
    """Convert retrieval hits into bounded evidence context."""

    def assemble(self, retrieval_result: dict[str, Any], token_budget: int = 3000, include_raw: bool = False) -> dict:
        budget = max(200, token_budget)
        used = 0
        evidence = []
        for result in retrieval_result.get("results", []):
            plan = result.get("plan")
            plan_id = getattr(plan, "id", None) if plan is not None else None
            for chunk in result.get("chunks", []):
                text = chunk.get("snippet") or chunk.get("text") or ""
                estimate = max(1, len(text.split()))
                if used + estimate > budget:
                    break
                used += estimate
                evidence.append(
                    {
                        "record_id": plan_id,
                        "chunk_id": chunk.get("id"),
                        "section_type": chunk.get("section_type"),
                        "heading": chunk.get("heading"),
                        "text": text,
                    }
                )
            for ref in result.get("file_refs", [])[:5]:
                evidence.append(
                    {
                        "record_id": plan_id,
                        "file_ref_id": ref.get("id"),
                        "path": ref.get("path"),
                        "source_type": ref.get("source_type"),
                        "module": ref.get("module"),
                    }
                )
        return {
            "metrics": {
                "total_candidates": retrieval_result.get("total", 0),
                "returned_candidates": len(retrieval_result.get("results", [])),
                "token_budget": budget,
                "token_estimate": used,
            },
            "evidence": evidence,
            "include_raw": include_raw,
        }
