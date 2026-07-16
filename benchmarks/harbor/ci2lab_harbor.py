"""ci2lab as a Terminal-Bench (Harbor) installed agent.

Run a Harbor suite against ci2lab with, e.g.::

    harbor run -d terminal-bench@2.1 \\
      --agent ci2lab_harbor:Ci2LabAgent \\
      --allow-agent-host host.docker.internal \\
      -o jobs/ci2lab

This module imports ``harbor`` and so must run inside the Harbor environment
(Python >= 3.12). It also imports ci2lab's own pure helpers, so ci2lab must be
importable in that same environment (``pip install ci2lab``). Make this module
importable by Harbor's ``--agent module:Class`` resolver by either installing it
(``pip install -e benchmarks/harbor``) or putting this directory on
``PYTHONPATH``. See ``README.md`` in this directory for the full run guide.

The installed-agent methods (``install`` / ``run``) execute on the Harbor host
and issue commands *into* the task container via ``exec_as_*``. ci2lab points
its own backend at the host's Ollama endpoint, so Harbor's model routing is
bypassed and the same-model arm costs nothing beyond local compute.
"""

from __future__ import annotations

from harbor.agents.installed.base import BaseInstalledAgent
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

from ci2lab import __version__ as _CI2LAB_VERSION
from ci2lab.bench.harbor import (
    DEFAULT_BACKEND_URL,
    DEFAULT_MAX_ROUNDS,
    DEFAULT_MODEL,
    DEFAULT_NUM_CTX,
    DEFAULT_WHEEL_URL,
    agent_env,
    build_install_command,
    build_run_command,
    read_run_summary,
)


class Ci2LabAgent(BaseInstalledAgent):
    """Single-agent ci2lab (the ReAct loop) under Terminal-Bench."""

    MULTI = False

    def __init__(self, *args: object, **kwargs: object) -> None:
        # ci2lab-specific knobs (``--agent-kwarg workdir=/foo``,
        # ``--agent-kwarg wheel_url=...``); pop them before delegating so Harbor's
        # base never sees an unknown kwarg.
        # Default to None so Harbor runs ci2lab in the task's own configured
        # workdir (it varies by dataset: /app, /workdir, /workspace, ...).
        # Forcing a single path fails every task built on a different root.
        _wd = kwargs.pop("workdir", None)
        self._workdir = str(_wd) if _wd is not None else None
        self._wheel_url = str(kwargs.pop("wheel_url", DEFAULT_WHEEL_URL))
        # The host endpoint is not discoverable from inside the container: the
        # defaults name ``host.docker.internal``, which only resolves on Docker
        # Desktop. On a native-Linux daemon Harbor adds no host-gateway mapping,
        # so the host must be addressed by IP (e.g. the bridge gateway).
        self._backend_url = str(kwargs.pop("backend_url", DEFAULT_BACKEND_URL))
        self._model = str(kwargs.pop("model", DEFAULT_MODEL))
        self._num_ctx = int(str(kwargs.pop("num_ctx", DEFAULT_NUM_CTX)))
        self._max_rounds = int(str(kwargs.pop("max_rounds", DEFAULT_MAX_ROUNDS)))
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]

    @staticmethod
    def name() -> str:
        return "ci2lab"

    def version(self) -> str | None:
        # Return the packaged version directly; avoids depending on the
        # container's ``ci2lab --version`` for Harbor's version metadata.
        return _CI2LAB_VERSION

    def get_version_command(self) -> str | None:
        return "ci2lab --version"

    async def install(self, environment: BaseEnvironment) -> None:
        await self.exec_as_root(
            environment,
            command="apt-get update && apt-get install -y python3 python3-pip",
            env={"DEBIAN_FRONTEND": "noninteractive"},
        )
        # ci2lab is not on PyPI: the container pulls a wheel served from the host
        # (see build_install_command). The wheel filename pins the exact build
        # under test — do not float it.
        await self.exec_as_agent(
            environment, command=build_install_command(self._wheel_url)
        )

    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        command = build_run_command(instruction, multi=self.MULTI, workdir=self._workdir)
        await self.exec_as_agent(
            environment,
            command=command,
            env=agent_env(
                model=self._model,
                backend_url=self._backend_url,
                num_ctx=self._num_ctx,
                max_rounds=self._max_rounds,
            ),
            cwd=self._workdir,
        )

    def populate_context_post_run(self, context: AgentContext) -> None:
        # Harbor logs zero tokens for installed agents; recover the real counts
        # from ci2lab's own run log, mounted back at ``self.logs_dir``.
        readback = read_run_summary(self.logs_dir)
        if readback is None:
            return
        context.n_input_tokens = readback.prompt_tokens
        context.n_output_tokens = readback.completion_tokens
        context.metadata = {
            **(context.metadata or {}),
            "ci2lab_total_tokens": readback.total_tokens,
            "ci2lab_rounds": readback.rounds,
            "ci2lab_status": readback.status,
            # Terminal-Bench grades only the container's final state, so the
            # tool-calling axis would otherwise be invisible to it.
            "tool_call_quality": readback.tool_call_quality,
        }


class Ci2LabMultiAgent(Ci2LabAgent):
    """Multi-agent ci2lab (the H3 single-vs-multi control)."""

    MULTI = True

    @staticmethod
    def name() -> str:
        return "ci2lab-multi"
