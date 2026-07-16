"""Scenario and metric records for opt-in adapted-tools benchmarks."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class AdaptedToolsScenario:
    id: str
    prompt: str
    expected_tool: str | None
    expected_arguments: dict[str, Any] | None
    category: str
    live: bool = False


@dataclass(frozen=True)
class ScenarioResult:
    id: str
    schemas_rendered: bool
    call_detected: bool
    correct_name: bool
    arguments_valid: bool
    executed: bool
    observation: bool
    final_response: bool
    repeated: bool
    rounds: int
    latency_seconds: float
    status: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


ADAPTED_TOOLS_SCENARIOS = (
    AdaptedToolsScenario(
        "add", "Use add to calculate 2+3.", "add", {"a": 2, "b": 3}, "basic", True
    ),
    AdaptedToolsScenario("echo", "Use echo with hello.", "echo", {"text": "hello"}, "basic"),
    AdaptedToolsScenario(
        "optional", "Use annotate with text hello only.", "annotate", {"text": "hello"}, "basic"
    ),
    AdaptedToolsScenario(
        "boolean", "Use configure to enable the feature.", "configure", {"enabled": True}, "basic"
    ),
    AdaptedToolsScenario(
        "enum", "Use set_mode with safe mode.", "set_mode", {"mode": "safe"}, "basic"
    ),
    AdaptedToolsScenario(
        "selection", "Choose add and calculate 2+3.", "add", {"a": 2, "b": 3}, "selection"
    ),
    AdaptedToolsScenario("unknown_name", "Diagnostic unknown tool response.", None, None, "error"),
    AdaptedToolsScenario("invalid_json", "Diagnostic invalid JSON response.", None, None, "error"),
    AdaptedToolsScenario(
        "missing_argument", "Diagnostic incomplete arguments.", None, None, "error"
    ),
    AdaptedToolsScenario("wrong_type", "Diagnostic wrong argument type.", None, None, "error"),
    AdaptedToolsScenario("tool_error", "Exercise a safe tool error.", "fail_safely", {}, "error"),
    AdaptedToolsScenario(
        "observation_error", "Handle a tool error observation.", "fail_safely", {}, "error"
    ),
    AdaptedToolsScenario(
        "one_call_final",
        "One call followed by final response.",
        "add",
        {"a": 2, "b": 3},
        "multiround",
    ),
    AdaptedToolsScenario(
        "two_sequential", "Use echo then add.", "echo", {"text": "2+3"}, "multiround"
    ),
    AdaptedToolsScenario(
        "history", "Use prior history then add.", "add", {"a": 2, "b": 3}, "multiround"
    ),
    AdaptedToolsScenario(
        "repeat_guard", "Do not repeat an identical call.", "add", {"a": 2, "b": 3}, "multiround"
    ),
    AdaptedToolsScenario(
        "round_limit", "Respect the configured round limit.", None, None, "multiround"
    ),
)


def summarize_results(results: list[ScenarioResult]) -> dict[str, float | int | None]:
    total = len(results)
    if not total:
        return {
            "scenarios": 0,
            "valid_call_rate": None,
            "execution_rate": None,
            "final_rate": None,
            "repeat_rate": None,
            "mean_rounds": None,
            "mean_latency_seconds": None,
        }
    return {
        "scenarios": total,
        "valid_call_rate": sum(item.call_detected and item.arguments_valid for item in results)
        / total,
        "execution_rate": sum(item.executed for item in results) / total,
        "final_rate": sum(item.final_response for item in results) / total,
        "repeat_rate": sum(item.repeated for item in results) / total,
        "mean_rounds": sum(item.rounds for item in results) / total,
        "mean_latency_seconds": sum(item.latency_seconds for item in results) / total,
    }
