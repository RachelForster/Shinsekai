"""Fixed synopsis evaluation harness for the AI story compiler."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from config.feature_flags import FeatureFlag, FeatureFlagConfigManager

from .generation import StoryGenerationService


@dataclass(frozen=True, slots=True)
class StoryGenerationEvalCase:
    id: str
    synopsis: str
    required_endings: int = 2


FIXED_STORY_GENERATION_EVAL_SET = (
    StoryGenerationEvalCase(
        "campus-mystery",
        "转学生与同伴调查废弃校舍。玩家对同伴的理解与取舍应导向真相、离开等不同结局。",
    ),
    StoryGenerationEvalCase(
        "space-rescue",
        "受损空间站只剩有限氧气。玩家要协调工程师和医生，在救援、证据和自保之间抉择。",
    ),
    StoryGenerationEvalCase(
        "court-intrigue",
        "年轻使者在两国和谈前发现密信，需要在盟友、职责与战争风险之间做出多路线决定。",
    ),
)


class StoryGenerationEvaluator:
    def __init__(
        self,
        flags: FeatureFlagConfigManager,
        service: StoryGenerationService,
    ) -> None:
        flags.require(FeatureFlag.STORY_SYSTEM)
        self.flags = flags
        self.service = service

    def evaluate(
        self,
        cases: tuple[StoryGenerationEvalCase, ...] = FIXED_STORY_GENERATION_EVAL_SET,
    ) -> dict[str, Any]:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        rows: list[dict[str, Any]] = []
        total_tokens = 0
        total_requests = 0
        for case in cases:
            task: dict[str, Any] | None = None
            try:
                task = self.service.create(
                    case.synopsis,
                    options={
                        "evalCaseId": case.id,
                        "minimumEndings": case.required_endings,
                    },
                )
                result = self.service.run(str(task["id"]))
                validation = result.get("validation") or {}
                cost = result.get("cost") or {}
                passed = (
                    bool(validation.get("valid"))
                    and len(validation.get("reachableEndingIds") or [])
                    >= case.required_endings
                )
                row = {
                    "id": case.id,
                    "passed": passed,
                    "status": result.get("status"),
                    "endingCoverage": float(validation.get("endingCoverage") or 0),
                    "reachableEndings": len(validation.get("reachableEndingIds") or []),
                    "requests": int(cost.get("requests") or 0),
                    "estimatedTokens": int(cost.get("estimatedTokens") or 0),
                    "error": result.get("error"),
                }
            except Exception as error:
                cost: dict[str, Any] = {}
                status = "failed"
                if task is not None:
                    try:
                        persisted = self.service.get(str(task["id"]))
                        cost = persisted.get("cost") or {}
                        status = str(persisted.get("status") or "failed")
                    except Exception:
                        pass
                row = {
                    "id": case.id,
                    "passed": False,
                    "status": status,
                    "endingCoverage": 0.0,
                    "reachableEndings": 0,
                    "requests": int(cost.get("requests") or 0),
                    "estimatedTokens": int(cost.get("estimatedTokens") or 0),
                    "error": str(error),
                }
            total_tokens += int(row["estimatedTokens"])
            total_requests += int(row["requests"])
            rows.append(row)
        passed_count = sum(1 for row in rows if row["passed"])
        return {
            "cases": rows,
            "caseCount": len(rows),
            "passedCount": passed_count,
            "structuralPassRate": passed_count / len(rows) if rows else 0.0,
            "meanEndingCoverage": (
                sum(float(row["endingCoverage"]) for row in rows) / len(rows)
                if rows
                else 0.0
            ),
            "generationCost": {
                "requests": total_requests,
                "estimatedTokens": total_tokens,
            },
        }
