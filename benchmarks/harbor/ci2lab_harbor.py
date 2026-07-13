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
    CONTAINER_WORKDIR,
    agent_env,
    build_run_command,
    read_run_summary,
)


class Ci2LabAgent(BaseInstalledAgent):
    """Single-agent ci2lab (the ReAct loop) under Terminal-Bench."""

    MULTI = False

    def __init__(self, *args: object, **kwargs: object) -> None:
        # ``workdir`` is a ci2lab-specific knob (``--agent-kwarg workdir=/foo``);
        # pop it before delegating so Harbor's base never sees an unknown kwarg.
        self._workdir = str(kwargs.pop("workdir", CONTAINER_WORKDIR))
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
        # Pin an exact ci2lab ref (wheel or git@<commit>) here for a reproducible
        # paper run; ``ci2lab`` installs the latest published build.
        await self.exec_as_agent(environment, command="pip install --no-input ci2lab")

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
            env=agent_env(),
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
        }


class Ci2LabMultiAgent(Ci2LabAgent):
    """Multi-agent ci2lab (the H3 single-vs-multi control)."""

    MULTI = True

    @staticmethod
    def name() -> str:
        return "ci2lab-multi"
