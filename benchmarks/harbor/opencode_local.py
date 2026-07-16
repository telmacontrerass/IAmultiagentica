"""opencode pointed at the same local model as ci2lab, for the same-model arm.

Harbor ships an ``opencode`` agent, but it can only forward *cloud* provider API
keys — it has no way to aim opencode at a local endpoint, and opencode has no env
var for a custom base URL either (the base URL must come from a provider block in
its config). So this subclass reuses Harbor's installed-agent machinery and adds
the one missing piece: it writes an opencode provider config into the container
and points opencode at it via ``OPENCODE_CONFIG``.

Run it with::

    harbor run -d terminal-bench@2.1 \\
      --agent opencode_local:OpenCodeLocal \\
      --allow-agent-host host.docker.internal \\
      -o jobs/opencode

Two fairness details are handled here rather than left to chance:

1. **Context window.** opencode disables auto-compaction when a model's
   ``limit.context`` is 0 (the default for an unlisted model), so a long task
   would silently overflow instead of compacting. ``opencode_local.json`` sets it
   explicitly to the same window ci2lab uses.
2. **``num_ctx``.** opencode speaks OpenAI-compatible ``/v1``, which *ignores*
   Ollama's ``num_ctx``; ci2lab speaks Ollama's native API and actually sets it.
   Left alone, ci2lab would get a larger effective context on identical hardware —
   a confound, not a result. Fix it on the **server**, not here: serve the shared
   Ollama with ``OLLAMA_CONTEXT_LENGTH=32768`` so every arm gets the same window.
   See ``README.md``.
"""

from __future__ import annotations

import shlex
from pathlib import Path

from harbor.agents.installed.opencode import OpenCode
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

CONTAINER_CONFIG_PATH = "/installed-agent/opencode-local.json"
CONTAINER_TRACE_PATH = "/logs/agent/opencode-trace.ndjson"
DEFAULT_MODEL = "ollama/qwen3-coder:30b"

_CONFIG_FILE = Path(__file__).with_name("opencode_local.json")


class OpenCodeLocal(OpenCode):
    """opencode running against a local OpenAI-compatible Ollama endpoint."""

    @staticmethod
    def name() -> str:
        return "opencode-local"

    async def install(self, environment: BaseEnvironment) -> None:
        await super().install(environment)
        # opencode resolves a custom provider only from config, so ship one in.
        config = _CONFIG_FILE.read_text(encoding="utf-8")
        await self.exec_as_agent(
            environment,
            command=(
                f"mkdir -p $(dirname {shlex.quote(CONTAINER_CONFIG_PATH)}) && "
                f"printf '%s' {shlex.quote(config)} > {shlex.quote(CONTAINER_CONFIG_PATH)}"
            ),
        )

    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        model = self.model_name or DEFAULT_MODEL
        # --format json emits the NDJSON tool trace that the tool-call KPI is
        # computed from; without --dangerously-skip-permissions opencode
        # auto-REJECTS every permission prompt and the run silently does nothing.
        command = (
            ". ~/.nvm/nvm.sh; "
            f"opencode run --model={shlex.quote(model)} --format=json "
            f"--dangerously-skip-permissions -- {shlex.quote(instruction)} "
            f"2>/dev/null | tee {shlex.quote(CONTAINER_TRACE_PATH)}"
        )
        await self.exec_as_agent(
            environment,
            command=command,
            env={
                "OPENCODE_CONFIG": CONTAINER_CONFIG_PATH,
                "OPENCODE_DISABLE_AUTOUPDATE": "1",
                "OPENCODE_DISABLE_MODELS_FETCH": "1",
            },
        )

    def populate_context_post_run(self, context: AgentContext) -> None:
        from ci2lab.bench.opencode_trace import summarize_opencode_trace_file

        trace = self.logs_dir / "opencode-trace.ndjson"
        quality = summarize_opencode_trace_file(trace)
        if quality is None:
            return
        context.metadata = {**(context.metadata or {}), "tool_call_quality": quality.to_dict()}
