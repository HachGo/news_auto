"""预测评估的公开汇总工具。"""

from __future__ import annotations


def summarize_evaluations(evaluations: list[dict]) -> dict:
    resolved = [item for item in evaluations if item.get("status") in {"correct", "incorrect"}]
    correct = sum(item.get("status") == "correct" for item in resolved)
    return {
        "sample_count": len(resolved),
        "correct_count": correct,
        "accuracy": round(correct / len(resolved), 4) if resolved else None,
        "unresolved_count": sum(item.get("status") == "unresolved" for item in evaluations),
    }
