"""Agent adapters: a uniform interface over ci2lab, Claude Code and Codex.

Each adapter runs one task sample and returns a normalized
:class:`~ci2lab.bench.metrics.RunResult`, so the runner, tasks, workspace
provisioning and grading are identical across systems — only the adapter
differs.
"""

from __future__ import annotations

from ci2lab.bench.adapters.base import ADAPTER_NAMES, AgentAdapter, get_adapter

__all__ = ["ADAPTER_NAMES", "AgentAdapter", "get_adapter"]
