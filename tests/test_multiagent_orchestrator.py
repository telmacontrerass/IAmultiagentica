import json

import pytest

from ci2lab.harness import AgentConfig, default_selection
from ci2lab.harness.multiagent.orchestrator import (
    _build_implementation_prompt,
    _build_planner_prompt,
    _build_repair_prompt,
    _build_research_prompt,
    _build_review_prompt,
    _build_security_review_prompt,
    _build_validation_prompt,
    choose_coder_role,
    final_run_status,
    has_write_tool_evidence,
    looks_like_untraceable_fs_mutation,
    run_multi_agent,
    should_run_security_review,
    should_skip_implementation,
    subagent_blocked,
    validation_failed,
    write_task_lacks_evidence,
)
from ci2lab.harness.multiagent.state import AgentRole, MultiAgentRun, SubAgentResult


def _result(role: AgentRole, output: str, *, attempt: int = 1, **kwargs) -> SubAgentResult:
    return SubAgentResult(
        role=role,
        task=f"{role.value} task",
        output=output,
        attempt=attempt,
        **kwargs,
    )


def test_choose_coder_role_prefers_specific_evidence():
    plan = _result(AgentRole.PLANNER, "Update ci2lab/harness/orchestrator.py")
    research = _result(AgentRole.RESEARCHER, "This is Python harness code.")

    assert choose_coder_role(plan, research) == AgentRole.PYTHON_CODER

    plan = _result(AgentRole.PLANNER, "Update ui/static/app.js and styles.css")
    research = _result(AgentRole.RESEARCHER, "Frontend behavior.")

    assert choose_coder_role(plan, research) == AgentRole.FRONTEND_CODER


def test_should_skip_implementation_for_read_only_pdf_task():
    plan = _result(AgentRole.PLANNER, "Read the PDF and summarize its contents.")
    research = _result(AgentRole.RESEARCHER, "Relevant document: paper.pdf")

    assert should_skip_implementation(
        "read the contents of the pdf and summarize it",
        plan,
        research,
    )


def test_should_not_skip_implementation_for_document_edit_task():
    plan = _result(AgentRole.PLANNER, "Update README.md")
    research = _result(AgentRole.RESEARCHER, "Relevant document: README.md")

    assert not should_skip_implementation(
        "update the README with a new example",
        plan,
        research,
    )


def test_validation_failed_detects_failure_and_pass():
    assert validation_failed(_result(AgentRole.VALIDATOR, "pytest failed"))
    assert not validation_failed(_result(AgentRole.VALIDATOR, "pytest passed"))
    assert not validation_failed(_result(AgentRole.VALIDATOR, "no errors"))


def test_subagent_blocked_detects_explicit_and_round_limit_blocks():
    assert subagent_blocked(_result(AgentRole.RESEARCHER, "BLOCKED: missing file"))
    assert subagent_blocked(
        _result(AgentRole.RESEARCHER, "Reached the max rounds limit without a final answer.")
    )
    assert not subagent_blocked(_result(AgentRole.RESEARCHER, "Found the context."))


def test_planner_prompt_requires_role_assignments_dependencies_and_boundaries():
    prompt = _build_planner_prompt("Add a feature")

    assert "authoritative execution plan" in prompt
    assert "Role assignments" in prompt
    assert "Dependencies" in prompt
    assert "Boundaries" in prompt
    assert "non-overlapping" in prompt


def test_downstream_prompts_require_following_planner_contract():
    plan = _result(
        AgentRole.PLANNER,
        "Role assignments: researcher reads files; python_coder edits app.py.\n"
        "Dependencies: coder uses researcher findings.\n"
        "Boundaries: reviewer does not edit files.",
    )
    research = _result(AgentRole.RESEARCHER, "Relevant file: app.py")
    implementation = _result(AgentRole.PYTHON_CODER, "Changed app.py")

    research_prompt = _build_research_prompt("Add a feature", plan)
    implementation_prompt = _build_implementation_prompt("Add a feature", plan, research)
    validation_prompt = _build_validation_prompt(
        "Add a feature",
        plan,
        research,
        implementation,
    )
    from ci2lab.harness.multiagent.state import MultiAgentRun

    run = MultiAgentRun(user_prompt="Add a feature")
    run.add_result(plan)
    run.add_result(research)
    run.add_result(implementation)
    review_prompt = _build_review_prompt(run)

    assert "Follow the planner's execution plan" in research_prompt
    assert "Only perform the research/context gathering assigned" in research_prompt
    assert "Implement only the tasks assigned" in implementation_prompt
    # Wording is plan-source-agnostic: a document task runs no planner.
    assert "outside the stated boundaries" in implementation_prompt
    assert "planner's validation expectations" in validation_prompt
    assert "did not follow the plan" in validation_prompt
    assert "against the planner's execution plan" in review_prompt
    assert "avoided overlapping responsibilities" in review_prompt


def test_validator_prompt_requires_real_tool_evidence_for_claims():
    plan = _result(AgentRole.PLANNER, "Create prueba_multiagente.txt.")
    research = _result(AgentRole.RESEARCHER, "No existing target file found.")
    implementation = _result(
        AgentRole.GENERALIST_CODER,
        "I created prueba_multiagente.txt and checked the content.",
        tool_calls=[],
    )

    prompt = _build_validation_prompt(
        "Create prueba_multiagente.txt with MULTIAGENTE_OK.",
        plan,
        research,
        implementation,
    )

    assert "Real tool-call evidence available" in prompt
    assert "Filesystem write evidence:\nnone" in prompt
    assert "Readback/content evidence:\nnone" in prompt
    assert "insufficient evidence" in prompt
    assert "non-existent verification helpers" in prompt
    assert "verificar_archivo" not in prompt
    assert "check_content" not in prompt


def test_validator_prompt_records_successful_write_and_readback_evidence():
    plan = _result(AgentRole.PLANNER, "Create prueba_multiagente.txt.")
    research = _result(AgentRole.RESEARCHER, "No existing target file found.")
    implementation = _result(
        AgentRole.GENERALIST_CODER,
        "Implemented requested file.",
        tool_calls=[
            {
                "tool": "write_file",
                "ok": True,
                "arguments": {"path": "prueba_multiagente.txt"},
                "output_preview": "Wrote prueba_multiagente.txt",
            },
            {
                "tool": "read_file",
                "ok": True,
                "arguments": {"path": "prueba_multiagente.txt"},
                "output_preview": "MULTIAGENTE_OK",
            },
        ],
    )

    prompt = _build_validation_prompt(
        "Create prueba_multiagente.txt with MULTIAGENTE_OK.",
        plan,
        research,
        implementation,
    )

    assert "generalist_coder: write_file(prueba_multiagente.txt)" in prompt
    assert "generalist_coder: read_file(prueba_multiagente.txt)" in prompt
    assert "MULTIAGENTE_OK" in prompt


def test_reviewer_prompt_does_not_allow_creation_claim_without_implementer():
    from ci2lab.harness.multiagent.state import MultiAgentRun

    run = MultiAgentRun(user_prompt="Read the PDF and summarize it.")
    run.add_result(_result(AgentRole.RESEARCHER, "Found the PDF summary."))

    prompt = _build_review_prompt(run)

    assert "Selected implementer: none selected" in prompt
    assert "Filesystem write evidence:\nnone" in prompt
    assert "You may say a file was created or modified only" in prompt
    assert "insufficient evidence" in prompt


def test_security_reviewer_prompt_does_not_allow_filesystem_write_claim_without_tool_result():
    from ci2lab.harness.multiagent.state import MultiAgentRun

    run = MultiAgentRun(user_prompt="Review filesystem safety.")
    run.add_result(_result(AgentRole.RESEARCHER, "No writes needed."))
    run.add_result(_result(AgentRole.REVIEWER, "Looks safe."))

    prompt = _build_security_review_prompt(run)

    assert "Selected implementer: none selected" in prompt
    assert "Filesystem write evidence:\nnone" in prompt
    assert "do not state that an implementer created, modified, or wrote files" in prompt
    assert "insufficient evidence of filesystem writes" in prompt


def test_should_run_security_review_for_sensitive_terms():
    from ci2lab.harness.multiagent.state import MultiAgentRun

    run = MultiAgentRun(user_prompt="Change permission handling")
    run.add_result(_result(AgentRole.PYTHON_CODER, "Updated approval rules"))

    assert should_run_security_review(run)


def test_run_multi_agent_sequential_flow(monkeypatch):
    calls: list[tuple[AgentRole, int]] = []
    selections = []
    outputs = {
        AgentRole.PLANNER: "Plan: edit ci2lab/harness/example.py",
        AgentRole.RESEARCHER: "Relevant Python file: ci2lab/harness/example.py",
        AgentRole.PYTHON_CODER: "Implemented Python change.",
        AgentRole.VALIDATOR: "pytest passed",
        AgentRole.REVIEWER: "No issues found.",
    }

    def fake_run_subagent(role, task_prompt, selection, config, *, attempt=1):
        calls.append((role, attempt))
        selections.append(selection)
        return _result(role, outputs[role], attempt=attempt)

    monkeypatch.setattr(
        "ci2lab.harness.multiagent.orchestrator.run_subagent",
        fake_run_subagent,
    )

    selected = default_selection("user-selected:7b")
    result = run_multi_agent(
        "Make a Python change",
        selected,
        config=AgentConfig(cwd=".", run_log_enabled=False),
    )

    assert calls == [
        (AgentRole.PLANNER, 1),
        (AgentRole.RESEARCHER, 1),
        (AgentRole.PYTHON_CODER, 1),
        (AgentRole.VALIDATOR, 1),
        (AgentRole.REVIEWER, 1),
    ]
    assert selections == [selected] * len(calls)
    assert "Selected implementer: python_coder" in result
    assert "pytest passed" in result


def test_run_multi_agent_skips_coder_for_read_only_pdf_task(monkeypatch):
    calls: list[tuple[AgentRole, int]] = []
    outputs = {
        AgentRole.PLANNER: "Plan: read the PDF and answer from its content.",
        AgentRole.RESEARCHER: "The PDF content says the main topic is formal writing.",
        AgentRole.REVIEWER: "The answer is grounded in the document. No code needed.",
    }

    def fake_run_subagent(role, task_prompt, selection, config, *, attempt=1):
        calls.append((role, attempt))
        return _result(role, outputs[role], attempt=attempt)

    monkeypatch.setattr(
        "ci2lab.harness.multiagent.orchestrator.run_subagent",
        fake_run_subagent,
    )

    result = run_multi_agent(
        "access the contents of the pdf test.pdf and tell me what it is about",
        default_selection("test:1b"),
        config=AgentConfig(cwd=".", run_log_enabled=False),
    )

    assert calls == [
        (AgentRole.PLANNER, 1),
        (AgentRole.RESEARCHER, 1),
        (AgentRole.REVIEWER, 1),
    ]
    assert "Selected implementer: none (read-only task)" in result
    assert "formal writing" in result


def test_run_multi_agent_stops_when_researcher_is_blocked(monkeypatch):
    calls: list[AgentRole] = []

    def fake_run_subagent(role, task_prompt, selection, config, *, attempt=1):
        calls.append(role)
        if role == AgentRole.PLANNER:
            return _result(role, "Plan: inspect the requested PDF.")
        if role == AgentRole.RESEARCHER:
            return _result(role, "BLOCKED: test.pdf was not found.")
        raise AssertionError(f"Unexpected role after blocked researcher: {role}")

    monkeypatch.setattr(
        "ci2lab.harness.multiagent.orchestrator.run_subagent",
        fake_run_subagent,
    )

    result = run_multi_agent(
        "access the contents of the pdf test.pdf and tell me what it is about",
        default_selection("test:1b"),
        config=AgentConfig(cwd=".", run_log_enabled=False),
    )

    assert calls == [AgentRole.PLANNER, AgentRole.RESEARCHER]
    assert "status: blocked" in result
    assert "Blocked role: researcher" in result
    assert "test.pdf was not found" in result


def test_run_multi_agent_prints_subagent_progress(monkeypatch):
    outputs = {
        AgentRole.PLANNER: "Plan: edit ci2lab/harness/example.py",
        AgentRole.RESEARCHER: "Relevant Python file: ci2lab/harness/example.py",
        AgentRole.PYTHON_CODER: "Implemented Python change.",
        AgentRole.VALIDATOR: "pytest passed",
        AgentRole.REVIEWER: "No issues found.",
    }
    printed: list[str] = []

    def fake_run_subagent(role, task_prompt, selection, config, *, attempt=1):
        return _result(role, outputs[role], attempt=attempt)

    monkeypatch.setattr(
        "ci2lab.harness.multiagent.orchestrator.run_subagent",
        fake_run_subagent,
    )
    monkeypatch.setattr(
        "ci2lab.harness.multiagent.orchestrator.console.print",
        lambda message: printed.append(str(message)),
    )

    run_multi_agent(
        "Make a Python change",
        default_selection("test:1b"),
        config=AgentConfig(cwd=".", run_log_enabled=False),
    )

    assert any("Planning the work" in message for message in printed)
    assert any("completed planner" in message for message in printed)
    assert any("Gathering the needed context" in message for message in printed)
    assert any("completed python_coder" in message for message in printed)
    assert any("Checking the result" in message for message in printed)
    assert any("completed reviewer" in message for message in printed)


def test_all_multiagent_role_progress_labels_are_english():
    from ci2lab.harness.multiagent.orchestrator import _role_progress_label

    expected = {
        AgentRole.PLANNER: "Planning the work",
        AgentRole.RESEARCHER: "Gathering the needed context",
        AgentRole.PYTHON_CODER: "Applying Python changes",
        AgentRole.FRONTEND_CODER: "Applying interface changes",
        AgentRole.TEST_CODER: "Updating tests",
        AgentRole.DOCS_CODER: "Updating documentation",
        AgentRole.GENERALIST_CODER: "Applying the requested changes",
        AgentRole.VALIDATOR: "Checking the result",
        AgentRole.REVIEWER: "Reviewing the outcome",
        AgentRole.SECURITY_REVIEWER: "Reviewing security and permissions",
    }

    assert {
        role: _role_progress_label(role, 1)
        for role in AgentRole
    } == expected


def test_run_multi_agent_repairs_with_same_coder(monkeypatch):
    calls: list[tuple[AgentRole, int]] = []
    validator_outputs = iter(["pytest failed: assertion error", "pytest passed"])

    def fake_run_subagent(role, task_prompt, selection, config, *, attempt=1):
        calls.append((role, attempt))
        if role == AgentRole.PLANNER:
            return _result(role, "Plan: edit ci2lab/harness/example.py")
        if role == AgentRole.RESEARCHER:
            return _result(role, "Relevant Python file: ci2lab/harness/example.py")
        if role == AgentRole.PYTHON_CODER:
            return _result(role, f"Python change attempt {attempt}", attempt=attempt)
        if role == AgentRole.VALIDATOR:
            return _result(role, next(validator_outputs), attempt=attempt)
        return _result(role, "Review complete", attempt=attempt)

    monkeypatch.setattr(
        "ci2lab.harness.multiagent.orchestrator.run_subagent",
        fake_run_subagent,
    )

    result = run_multi_agent(
        "Make a Python change",
        default_selection("test:1b"),
        config=AgentConfig(cwd=".", run_log_enabled=False),
        max_repair_attempts=2,
    )

    assert calls == [
        (AgentRole.PLANNER, 1),
        (AgentRole.RESEARCHER, 1),
        (AgentRole.PYTHON_CODER, 1),
        (AgentRole.VALIDATOR, 1),
        (AgentRole.PYTHON_CODER, 2),
        (AgentRole.VALIDATOR, 2),
        (AgentRole.REVIEWER, 1),
    ]
    assert "Selected implementer: python_coder" in result
    assert "pytest passed" in result


def test_run_multi_agent_adds_security_review_when_needed(monkeypatch):
    calls: list[tuple[AgentRole, int]] = []

    def fake_run_subagent(role, task_prompt, selection, config, *, attempt=1):
        calls.append((role, attempt))
        if role == AgentRole.PLANNER:
            return _result(role, "Plan: update permission code in ci2lab/security")
        if role == AgentRole.RESEARCHER:
            return _result(role, "Security-sensitive approval behavior")
        if role == AgentRole.PYTHON_CODER:
            return _result(role, "Implemented permission change")
        if role == AgentRole.VALIDATOR:
            return _result(role, "pytest passed")
        if role == AgentRole.SECURITY_REVIEWER:
            return _result(role, "Security review passed")
        return _result(role, "Review complete")

    monkeypatch.setattr(
        "ci2lab.harness.multiagent.orchestrator.run_subagent",
        fake_run_subagent,
    )

    result = run_multi_agent(
        "Change permission handling",
        default_selection("test:1b"),
        config=AgentConfig(cwd=".", run_log_enabled=False),
    )

    assert calls[-2:] == [
        (AgentRole.REVIEWER, 1),
        (AgentRole.SECURITY_REVIEWER, 1),
    ]
    assert "Security review passed" in result


def test_multiagent_trace_records_phase_sequence(tmp_path, monkeypatch):
    outputs = {
        AgentRole.PLANNER: "Plan output",
        AgentRole.RESEARCHER: "Research output",
        AgentRole.PYTHON_CODER: "Implemented output",
        AgentRole.VALIDATOR: "pytest passed",
        AgentRole.REVIEWER: "Review output",
    }

    def fake_run_subagent(role, task_prompt, selection, config, *, attempt=1):
        return _result(
            role,
            outputs.get(role, "Generic output"),
            attempt=attempt,
            role_anchor=f"Role anchor: {role.value}",
            allowed_tools=["read_file"],
            input_prompt=task_prompt,
            rounds=1,
        )

    monkeypatch.setattr(
        "ci2lab.harness.multiagent.orchestrator.run_subagent",
        fake_run_subagent,
    )

    cfg = AgentConfig(
        cwd=str(tmp_path),
        runs_dir=str(tmp_path / "runs"),
        run_log_enabled=True,
    )
    run_multi_agent("Make a Python change", default_selection("test:1b"), config=cfg)

    run_dirs = sorted((tmp_path / "runs").iterdir())
    trace = json.loads((run_dirs[0] / "multiagent_trace.json").read_text(encoding="utf-8"))
    assert trace["planned_phases"][:2] == ["planner", "researcher"]
    assert trace["selected_coder_role"] == "generalist_coder"
    assert trace["executed_phases"][:5] == [
        "planner",
        "researcher",
        "generalist_coder",
        "validator",
        "reviewer",
    ]
    assert (run_dirs[0] / "multiagent_trace.json").is_file()


def test_multiagent_trace_records_role_anchor_and_allowed_tools(tmp_path, monkeypatch):
    def fake_run_subagent(role, task_prompt, selection, config, *, attempt=1):
        return _result(
            role,
            "ok" if role != AgentRole.VALIDATOR else "pytest passed",
            attempt=attempt,
            role_anchor=f"Role anchor: You are currently acting as {role.value}.",
            allowed_tools=["read_file", "grep"],
            can_write=False,
            input_prompt=task_prompt,
            rounds=2,
        )

    monkeypatch.setattr(
        "ci2lab.harness.multiagent.orchestrator.run_subagent",
        fake_run_subagent,
    )

    cfg = AgentConfig(
        cwd=str(tmp_path),
        runs_dir=str(tmp_path / "runs"),
        run_log_enabled=True,
    )
    run_multi_agent("Inspect the repo", default_selection("test:1b"), config=cfg)

    trace_path = next((tmp_path / "runs").iterdir()) / "multiagent_trace.json"
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    planner = next(item for item in trace["phases"] if item["role"] == "planner")
    assert planner["role_anchor"].startswith("Role anchor:")
    assert planner["allowed_tools"] == ["read_file", "grep"]


def test_multiagent_trace_records_skipped_or_failed_phase(tmp_path, monkeypatch):
    def fake_run_subagent(role, task_prompt, selection, config, *, attempt=1):
        if role == AgentRole.RESEARCHER:
            raise RuntimeError("research exploded")
        return _result(
            role,
            "ok",
            attempt=attempt,
            role_anchor=f"Role anchor: {role.value}",
            allowed_tools=[],
            input_prompt=task_prompt,
        )

    monkeypatch.setattr(
        "ci2lab.harness.multiagent.orchestrator.run_subagent",
        fake_run_subagent,
    )

    cfg = AgentConfig(
        cwd=str(tmp_path),
        runs_dir=str(tmp_path / "runs"),
        run_log_enabled=True,
    )
    with pytest.raises(RuntimeError, match="research exploded"):
        run_multi_agent("Inspect the repo", default_selection("test:1b"), config=cfg)

    trace_path = next((tmp_path / "runs").iterdir()) / "multiagent_trace.json"
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    assert trace["failed_phase"] == "researcher"
    researcher = next(item for item in trace["phases"] if item["role"] == "researcher")
    assert researcher["status"] == "failed"
    assert "research exploded" in researcher["error"]


_WRITE_PROMPT = (
    "Crea un archivo llamado prueba_multiagente.txt en la raíz del workspace con "
    "exactamente este contenido: MULTIAGENTE_OK. Después verifica que el archivo "
    "existe y que el contenido es correcto. No modifiques ningún otro archivo."
)

_PYTHON_SCRIPT_OUTPUT = (
    "```python\n"
    'with open("prueba_multiagente.txt", "w") as f:\n'
    '    f.write("MULTIAGENTE_OK")\n'
    "```"
)

_WRITE_READBACK_TOOL_CALLS = [
    {
        "tool": "write_file",
        "ok": True,
        "arguments": {"path": "prueba_multiagente.txt"},
        "output_preview": "Wrote prueba_multiagente.txt",
    },
    {
        "tool": "read_file",
        "ok": True,
        "arguments": {"path": "prueba_multiagente.txt"},
        "output_preview": "MULTIAGENTE_OK",
    },
]


def _force_code_change_intent(monkeypatch) -> None:
    """Pin the intent decision so these orchestrator tests exercise the evidence
    gate, not the (separately tested) intent-routing classifier."""
    from ci2lab.harness.multiagent.intent import (
        MultiAgentIntent,
        MultiAgentIntentDecision,
    )

    decision = MultiAgentIntentDecision(
        intent=MultiAgentIntent.CODE_CHANGE,
        requires_write=True,
        allowed_phases=["planner", "researcher", "coder", "validator", "reviewer"],
        reason="forced code_change for orchestrator evidence-gate test",
        confidence="high",
    )
    monkeypatch.setattr(
        "ci2lab.harness.multiagent.orchestrator.classify_multiagent_intent",
        lambda _prompt: decision,
    )


def _write_run(implementation: SubAgentResult, validation_output: str) -> MultiAgentRun:
    run = MultiAgentRun(user_prompt=_WRITE_PROMPT)
    run.requires_write = True
    run.selected_coder_role = implementation.role
    run.add_result(_result(AgentRole.PLANNER, "Plan: create the file."))
    run.add_result(_result(AgentRole.RESEARCHER, "No existing target file."))
    run.add_result(implementation)
    run.add_result(_result(AgentRole.VALIDATOR, validation_output))
    return run


# --- Evidence-gate regression coverage ------------------------------------
#
# Root cause reproduced from run 2026-06-18_122425_20a4d28d: the coder returned
# a Python `open(..., "w")` script instead of calling write_file, so no tool
# evidence existed, yet the run was reported as completed because the validator
# text contained the substring "ok" (from MULTIAGENTE_OK).


def test_validation_failed_treats_insufficient_evidence_as_failure():
    assert validation_failed(
        _result(AgentRole.VALIDATOR, "Insufficient evidence: no write_file result.")
    )
    assert validation_failed(
        _result(AgentRole.VALIDATOR, "Insuficiente Evidencia. No hay evidencia de escritura.")
    )


def test_validation_failed_ignores_ok_substring_in_content():
    # The literal content token must not be read as a success ("ok" inside
    # MULTIAGENTE_OK) — this is the exact false-positive from the failing run.
    assert not validation_failed(_result(AgentRole.VALIDATOR, "Result content: MULTIAGENTE_OK"))
    # And when the validator reports insufficient evidence, the same content
    # token must not flip it back to success.
    assert validation_failed(
        _result(
            AgentRole.VALIDATOR,
            "No hay evidencia. MULTIAGENTE_OK. Insufficient evidence to confirm the write.",
        )
    )


def test_looks_like_untraceable_fs_mutation_detects_returned_script():
    assert looks_like_untraceable_fs_mutation(_PYTHON_SCRIPT_OUTPUT)
    assert looks_like_untraceable_fs_mutation('Path("x.txt").write_text("hi")')
    assert not looks_like_untraceable_fs_mutation("I will use write_file to create the file.")


def test_has_write_tool_evidence_requires_successful_write_tool():
    no_evidence = _result(AgentRole.GENERALIST_CODER, _PYTHON_SCRIPT_OUTPUT, tool_calls=[])
    assert not has_write_tool_evidence([no_evidence])

    failed_write = _result(
        AgentRole.GENERALIST_CODER,
        "tried",
        tool_calls=[{"tool": "write_file", "ok": False, "arguments": {"path": "x"}}],
    )
    assert not has_write_tool_evidence([failed_write])

    real_write = _result(
        AgentRole.GENERALIST_CODER, "done", tool_calls=_WRITE_READBACK_TOOL_CALLS
    )
    assert has_write_tool_evidence([real_write])


def test_write_task_lacks_evidence_for_returned_script_but_not_for_real_write():
    script_run = _write_run(
        _result(AgentRole.GENERALIST_CODER, _PYTHON_SCRIPT_OUTPUT, tool_calls=[]),
        "Insufficient evidence.",
    )
    assert write_task_lacks_evidence(script_run)
    assert final_run_status(script_run) != "completed"

    real_run = _write_run(
        _result(AgentRole.GENERALIST_CODER, "Created via tools.", tool_calls=_WRITE_READBACK_TOOL_CALLS),
        "Validation passed.",
    )
    assert not write_task_lacks_evidence(real_run)
    assert final_run_status(real_run) == "completed"


def test_final_run_status_downgrades_write_task_without_evidence_even_if_validator_passes():
    # Even when the validator is fooled into reporting success, the deterministic
    # evidence gate must refuse a clean completion for a write task.
    fooled = _write_run(
        _result(AgentRole.GENERALIST_CODER, _PYTHON_SCRIPT_OUTPUT, tool_calls=[]),
        "All checks passed, looks ok.",
    )
    assert final_run_status(fooled) == "insufficient_evidence"


def test_implementation_and_repair_prompts_require_traceable_write_tools():
    plan = _result(AgentRole.PLANNER, "Create prueba_multiagente.txt.")
    research = _result(AgentRole.RESEARCHER, "No existing file.")
    impl_prompt = _build_implementation_prompt(_WRITE_PROMPT, plan, research)
    assert "write_file" in impl_prompt
    assert 'open(path, "w")' in impl_prompt
    assert "never executed" in impl_prompt

    repair_prompt = _build_repair_prompt(
        _WRITE_PROMPT,
        plan,
        research,
        _result(AgentRole.GENERALIST_CODER, _PYTHON_SCRIPT_OUTPUT),
        _result(AgentRole.VALIDATOR, "Insufficient evidence."),
    )
    assert "write_file" in repair_prompt
    assert 'open(path, "w")' in repair_prompt


def test_run_multi_agent_write_task_without_tool_evidence_is_not_completed(monkeypatch):
    _force_code_change_intent(monkeypatch)

    def fake_run_subagent(role, task_prompt, selection, config, *, attempt=1):
        if role == AgentRole.PLANNER:
            return _result(role, "Plan: create the file.")
        if role == AgentRole.RESEARCHER:
            return _result(role, "No existing target file.")
        if role == AgentRole.GENERALIST_CODER:
            return _result(role, _PYTHON_SCRIPT_OUTPUT, attempt=attempt, tool_calls=[])
        if role == AgentRole.VALIDATOR:
            return _result(role, "Insufficient evidence of the file write.", attempt=attempt)
        return _result(role, "Review complete.", attempt=attempt)

    monkeypatch.setattr(
        "ci2lab.harness.multiagent.orchestrator.run_subagent",
        fake_run_subagent,
    )

    result = run_multi_agent(
        _WRITE_PROMPT,
        default_selection("test:1b"),
        config=AgentConfig(cwd=".", run_log_enabled=False),
        max_repair_attempts=0,
    )

    assert "status: completed" not in result
    assert "Selected implementer: generalist_coder" in result


def test_run_multi_agent_write_task_with_tool_evidence_completes(monkeypatch):
    _force_code_change_intent(monkeypatch)

    def fake_run_subagent(role, task_prompt, selection, config, *, attempt=1):
        if role == AgentRole.PLANNER:
            return _result(role, "Plan: create the file.")
        if role == AgentRole.RESEARCHER:
            return _result(role, "No existing target file.")
        if role == AgentRole.GENERALIST_CODER:
            return _result(
                role, "Created the file with tools.", attempt=attempt,
                tool_calls=_WRITE_READBACK_TOOL_CALLS,
            )
        if role == AgentRole.VALIDATOR:
            return _result(role, "Validation passed; content is correct.", attempt=attempt)
        return _result(role, "Review complete.", attempt=attempt)

    monkeypatch.setattr(
        "ci2lab.harness.multiagent.orchestrator.run_subagent",
        fake_run_subagent,
    )

    result = run_multi_agent(
        _WRITE_PROMPT,
        default_selection("test:1b"),
        config=AgentConfig(cwd=".", run_log_enabled=False),
    )

    assert "status: completed" in result
    assert "Selected implementer: generalist_coder" in result


def test_multiagent_trace_truncates_large_tool_results(tmp_path, monkeypatch):
    huge = "x" * 5000

    def fake_run_subagent(role, task_prompt, selection, config, *, attempt=1):
        status_output = "pytest passed" if role == AgentRole.VALIDATOR else "ok"
        return _result(
            role,
            status_output,
            attempt=attempt,
            role_anchor=f"Role anchor: {role.value}",
            allowed_tools=["read_file"],
            input_prompt=task_prompt,
            tool_calls=[
                {
                    "tool": "read_file",
                    "ok": True,
                    "outcome": "approved",
                    "arguments": {"path": "big.txt"},
                    "output_preview": huge,
                    "error_preview": None,
                }
            ],
        )

    monkeypatch.setattr(
        "ci2lab.harness.multiagent.orchestrator.run_subagent",
        fake_run_subagent,
    )

    cfg = AgentConfig(
        cwd=str(tmp_path),
        runs_dir=str(tmp_path / "runs"),
        run_log_enabled=True,
    )
    run_multi_agent("Inspect the repo", default_selection("test:1b"), config=cfg)

    trace_path = next((tmp_path / "runs").iterdir()) / "multiagent_trace.json"
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    planner = next(item for item in trace["phases"] if item["role"] == "planner")
    preview = planner["tool_calls"][0]["output_preview"]
    assert len(preview) < 2000
    assert "truncated" in preview
