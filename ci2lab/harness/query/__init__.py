"""Agent query loop (ReAct).

`run_agent` lives in `loop.py`; supporting modules handle LLM I/O, PDF nudges
and session persistence hooks.
"""

from ci2lab.harness.query.loop import run_agent

__all__ = ["run_agent"]
