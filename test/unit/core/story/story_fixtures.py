from __future__ import annotations

from typing import Any


def campus_mystery_source() -> dict[str, Any]:
    """Return an aggregate mapping for isolated core story unit tests."""

    return {
        "schemaVersion": 1,
        "id": "campus-mystery",
        "version": 1,
        "title": "旧校舍的雨声",
        "status": "published",
        "startNodeId": "transfer-day",
        "metadata": {
            "language": "zh-CN",
            "estimatedMinutes": 20,
            "generationMode": "manual",
        },
        "variables": {
            "trust.ling": {
                "type": "integer",
                "initial": 0,
                "min": 0,
                "max": 100,
                "visible": True,
                "allowSemanticInput": True,
            },
            "flags.arrived_old_school": {
                "type": "boolean",
                "initial": False,
            },
            "inventory": {
                "type": "string_set",
                "initial": ["old_school_key"],
            },
        },
        "semanticSignals": [
            {
                "id": "respect-boundary",
                "minimumConfidence": "medium",
                "allowedSpeechActs": ["endorsement", "action"],
                "repeatWindow": 20,
                "maxPerTurn": 1,
                "maxPerScene": 3,
                "maxPerChapter": 10,
                "effectsByStrength": {
                    "weak": [{"increment": ["trust.ling", 1]}],
                    "medium": [{"increment": ["trust.ling", 2]}],
                    "strong": [{"increment": ["trust.ling", 4]}],
                },
            }
        ],
        "cast": {
            "defaults": {"maxActive": 4, "preserveCurrentCast": True},
            "initialCast": ["ling"],
            "characters": [
                {
                    "id": "ling",
                    "source": {
                        "type": "local-library",
                        "characterId": "ling",
                        "revision": "sha256:test-ling",
                    },
                    "tags": ["student", "investigator"],
                    "roles": ["companion"],
                    "priority": 100,
                },
                {
                    "id": "detective-zhou",
                    "source": {
                        "type": "embedded",
                        "path": "characters/detective-zhou.yaml",
                    },
                    "tags": ["adult", "police", "investigator"],
                    "roles": ["authority", "clue-provider"],
                    "priority": 50,
                },
            ],
        },
        "narrativeGraph": {
            "startNodeId": "transfer-day",
            "nodes": [
                {
                    "id": "transfer-day",
                    "title": "转校日",
                    "commitment": "frozen",
                    "castPolicy": {
                        "mode": "fixed",
                        "required": ["ling"],
                        "constraints": {"minActive": 1, "maxActive": 2},
                    },
                    "choices": [
                        {
                            "id": "prepare-investigation",
                            "label": "和绫约定调查旧校舍",
                            "effects": [{"increment": ["trust.ling", 10]}],
                            "goto": "old-school-gate",
                        }
                    ],
                },
                {
                    "id": "old-school-gate",
                    "title": "旧校舍门前",
                    "commitment": "frozen",
                    "enterWhen": {"gte": ["trust.ling", 10]},
                    "castPolicy": {
                        "mode": "role-based",
                        "required": ["ling"],
                        "requiredRoles": [
                            {
                                "role": "authority",
                                "count": 1,
                                "prefer": ["detective-zhou"],
                            }
                        ],
                        "constraints": {"minActive": 2, "maxActive": 3},
                        "fallback": {
                            "onMissingRole": "error",
                            "onLoadFailure": "continue-without-optional",
                        },
                    },
                    "onEnter": [{"set": ["flags.arrived_old_school", True]}],
                    "choices": [
                        {
                            "id": "enter-with-key",
                            "label": "使用旧钥匙进入",
                            "when": {"contains": ["inventory", "old_school_key"]},
                            "effects": [{"removeSet": ["inventory", "old_school_key"]}],
                            "goto": "truth-ending",
                        }
                    ],
                    "freeformIntents": [
                        {
                            "id": "reassure-ling",
                            "examples": ["我会陪着你", "我们一起面对"],
                            "effects": [{"increment": ["trust.ling", 5]}],
                            "resultBeat": "绫的神情稍微放松下来。",
                        }
                    ],
                },
                {
                    "id": "truth-ending",
                    "title": "雨声之后",
                    "type": "ending",
                    "commitment": "frozen",
                    "castPolicy": {
                        "mode": "fixed",
                        "required": ["ling"],
                        "constraints": {"minActive": 1, "maxActive": 2},
                    },
                },
            ],
        },
        "logicGraph": {
            "version": 1,
            "nodes": [
                {
                    "id": "trust-metric",
                    "type": "metric-ref",
                    "config": {"variable": "trust.ling"},
                },
                {
                    "id": "trust-threshold",
                    "type": "condition.gte",
                    "config": {"value": 10},
                },
                {
                    "id": "unlock-old-school",
                    "type": "unlock",
                    "config": {"storyNodeId": "old-school-gate"},
                },
            ],
            "edges": [
                {
                    "from": {"nodeId": "trust-metric", "port": "value"},
                    "to": {"nodeId": "trust-threshold", "port": "input"},
                },
                {
                    "from": {"nodeId": "trust-threshold", "port": "result"},
                    "to": {"nodeId": "unlock-old-school", "port": "when"},
                },
            ],
        },
    }
