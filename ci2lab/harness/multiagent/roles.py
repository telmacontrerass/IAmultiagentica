"""Role definitions for the sequential multi-agent harness."""

from __future__ import annotations

from dataclasses import dataclass

from ci2lab.harness.multiagent.state import AgentRole
from ci2lab.harness.tools.capabilities import FILE_WRITE_TOOLS


@dataclass(frozen=True)
class RoleSpec:
    """Static capabilities and instructions for one subagent role."""

    role: AgentRole
    description: str
    allowed_tools: frozenset[str]
    system_instructions: str
    phase_purpose: str
    must_not: str
    expected_output: str
    can_write: bool = False


# Local-filesystem read tools every role may use. This is intentionally narrower
# than `capabilities.READ_ONLY_TOOLS` (which also covers web/cacheable lookups):
# it is the permission base for a role, not the loop's cache-eligibility set.
READ_TOOLS = frozenset({
    "ls",
    "glob",
    "read_file",
    "read_document",
    "grep",
})

# An implementer can read plus author any file type. Sharing the canonical
# `FILE_WRITE_TOOLS` keeps "what counts as a write" identical to the loop's
# write-intent gate, so a coder role is always recognized as write-capable.
EDIT_TOOLS = READ_TOOLS | FILE_WRITE_TOOLS

RUNTIME_TOOLS = READ_TOOLS | frozenset({
    "bash",
})

# Peer-review lenses are read-only. Scope and novelty may consult the web to
# check a venue's scope or the state of the art — but any external citation only
# counts if the source was actually fetched (verified in grounding.py).
WEB_READ_TOOLS = READ_TOOLS | frozenset({
    "web_search",
    "web_fetch",
})

# A short instruction shared by every grounded reviewer lens. It is appended to
# each lens's system_instructions so the anti-hallucination contract is repeated
# in every isolated subagent context.
_GROUNDING_CONTRACT = (
    "GROUNDING CONTRACT (non-negotiable): The anchored manuscript in the task is "
    "the ONLY source of truth about this paper. Never use outside knowledge of "
    "the paper, its authors, or its results, and never invent quotes, section "
    "names, numbers, or citations. Emit your findings ONLY as a JSON array; each "
    "item is {\"claim\", \"evidence_type\" (manuscript|absence|external), "
    "\"evidence_quote\" (verbatim, for manuscript), \"anchor\" (e.g. A12), "
    "\"absence_terms\" (the exact strings you searched, for absence), "
    "\"external_url\" (only if you actually fetched it), \"severity\" "
    "(major|minor), \"reviewer_judgment\"}. If you cannot quote it from the "
    "manuscript, do not assert it; say it is not found instead. For an external "
    "citation, FETCH it with web_fetch first; if the fetch fails (paywall, "
    "offline, dead link) still report it with its URL — it will be routed to a "
    "manual-check section, not dropped, and the paper will not be blamed for a "
    "source you could not open."
)


ROLE_SPECS: dict[AgentRole, RoleSpec] = {
    AgentRole.PLANNER: RoleSpec(
        role=AgentRole.PLANNER,
        description="Breaks the user request into ordered subtasks and success criteria.",
        allowed_tools=frozenset(),
        system_instructions=(
            "You are the planning subagent. Produce a concise implementation plan, "
            "identify dependencies, and state success criteria. Do not modify files."
        ),
        phase_purpose="Create a concise, safe implementation plan for the requested task.",
        must_not="Do not edit files, do not run validation, and do not claim implementation is complete.",
        expected_output="A short plan with ordered steps, relevant files or areas, dependencies, and success criteria.",
    ),
    AgentRole.RESEARCHER: RoleSpec(
        role=AgentRole.RESEARCHER,
        description="Inspects repository context and reports relevant files or constraints.",
        allowed_tools=READ_TOOLS,
        system_instructions=(
            "You are the research subagent. Inspect only the context needed for the "
            "task and summarize the files, APIs, and constraints found. Do not modify files."
        ),
        phase_purpose="Gather evidence and inspect only the repository context needed for this task.",
        must_not="Do not implement changes, do not edit files, and do not claim validation or review is finished.",
        expected_output="A focused summary of relevant files, APIs, constraints, and risks for the current task.",
    ),
    AgentRole.PYTHON_CODER: RoleSpec(
        role=AgentRole.PYTHON_CODER,
        description="Implements Python backend or harness changes.",
        allowed_tools=EDIT_TOOLS,
        system_instructions=(
            "You are the Python implementation subagent. Apply focused Python changes "
            "that satisfy the plan and preserve existing behavior."
        ),
        phase_purpose="Implement the requested Python or harness change for this phase.",
        must_not="Do not switch to planning, validation, or review work, and do not claim success before tool results or tests confirm it.",
        expected_output="A focused implementation with concise evidence of what changed.",
        can_write=True,
    ),
    AgentRole.FRONTEND_CODER: RoleSpec(
        role=AgentRole.FRONTEND_CODER,
        description="Implements frontend UI, JavaScript, HTML, or CSS changes.",
        allowed_tools=EDIT_TOOLS,
        system_instructions=(
            "You are the frontend implementation subagent. Apply focused UI, HTML, "
            "CSS, or JavaScript changes that match the existing application style."
        ),
        phase_purpose="Implement the requested frontend change for this phase.",
        must_not="Do not switch to planning, validation, or review work, and do not claim success before tool results or tests confirm it.",
        expected_output="A focused frontend implementation with concise evidence of what changed.",
        can_write=True,
    ),
    AgentRole.TEST_CODER: RoleSpec(
        role=AgentRole.TEST_CODER,
        description="Adds or updates tests for the requested behavior.",
        allowed_tools=EDIT_TOOLS,
        system_instructions=(
            "You are the test implementation subagent. Add or update focused tests "
            "for the requested behavior without unrelated refactors."
        ),
        phase_purpose="Implement or update tests needed for the requested behavior.",
        must_not="Do not switch to planning, validation, or review work, and do not claim success before tool results confirm the test changes.",
        expected_output="Focused test changes and concise evidence of what was added or updated.",
        can_write=True,
    ),
    AgentRole.DOCS_CODER: RoleSpec(
        role=AgentRole.DOCS_CODER,
        description="Updates documentation or examples.",
        allowed_tools=EDIT_TOOLS,
        system_instructions=(
            "You are the documentation subagent. Update docs or examples clearly "
            "and keep code behavior unchanged unless explicitly requested."
        ),
        phase_purpose="Implement the requested documentation or example update for this phase.",
        must_not="Do not switch to planning, validation, or review work, and do not change code behavior unless explicitly required.",
        expected_output="Focused documentation or example updates with concise evidence of what changed.",
        can_write=True,
    ),
    AgentRole.GENERALIST_CODER: RoleSpec(
        role=AgentRole.GENERALIST_CODER,
        description="Implements changes that do not fit a narrower coder role.",
        allowed_tools=EDIT_TOOLS,
        system_instructions=(
            "You are the general implementation subagent. Make the smallest coherent "
            "change that satisfies the task and preserves existing behavior."
        ),
        phase_purpose="Implement the requested change for this phase with the smallest coherent edit.",
        must_not="Do not switch to planning, validation, or review work, and do not claim success before tool results or tests confirm it.",
        expected_output="A focused implementation with concise evidence of what changed.",
        can_write=True,
    ),
    AgentRole.VALIDATOR: RoleSpec(
        role=AgentRole.VALIDATOR,
        description="Runs validation and reports pass/fail evidence.",
        allowed_tools=RUNTIME_TOOLS,
        system_instructions=(
            "You are the validation subagent. Run or recommend focused checks, report "
            "whether validation passed, and include actionable failure details."
        ),
        phase_purpose="Validate the current result using tests or deterministic checks.",
        must_not="Do not implement changes, do not rewrite the plan, and do not hide failures.",
        expected_output="A clear validation result that states pass or fail and includes actionable failure details when needed.",
    ),
    AgentRole.REVIEWER: RoleSpec(
        role=AgentRole.REVIEWER,
        description="Reviews the final result for regressions and completeness.",
        allowed_tools=READ_TOOLS,
        system_instructions=(
            "You are the review subagent. Review the completed work for bugs, "
            "missing tests, regressions, and incomplete requirements. Do not modify files."
        ),
        phase_purpose="Review the completed result for bugs, regressions, gaps, and incomplete requirements.",
        must_not="Do not implement changes, do not edit files, and do not claim validation work you did not perform.",
        expected_output="A concise review with concrete findings, risks, and missing coverage if any.",
    ),
    AgentRole.SECURITY_REVIEWER: RoleSpec(
        role=AgentRole.SECURITY_REVIEWER,
        description="Reviews permission, command, and security-sensitive changes.",
        allowed_tools=READ_TOOLS,
        system_instructions=(
            "You are the security review subagent. Check for permission, command "
            "execution, secret-handling, and filesystem safety risks. Do not modify files."
        ),
        phase_purpose="Look for security risks, permission expansion, leaks, bypasses, or unsafe tool use.",
        must_not="Do not implement changes, do not edit files, and do not ignore potential security or permission regressions.",
        expected_output="A concise security review with concrete risks, permission concerns, and unsafe behaviors if found.",
    ),
    AgentRole.INTAKE_REVIEWER: RoleSpec(
        role=AgentRole.INTAKE_REVIEWER,
        description="Diagnoses review readiness and establishes shared, grounded context.",
        allowed_tools=READ_TOOLS,
        system_instructions=(
            "You are the intake/diagnostic reviewer. Establish the review context "
            "before any detailed critique: a faithful 5-7 line summary, the paper's "
            "field/subfield, target venue and article type (use the values given, "
            "else infer and clearly mark them as inferred), the manuscript maturity "
            "(engineering_report | early_manuscript | submission_candidate | "
            "near_ready) with a one-line reason, an evidence audit (which of "
            "baselines/metrics/ablations/failure-cases/reproducibility/comparison "
            "are present vs absent), and the single claimed contribution. Quote "
            "verbatim with anchors. Do not modify files. " + _GROUNDING_CONTRACT
        ),
        phase_purpose="Diagnose readiness and produce the grounded shared context for the other reviewers.",
        must_not="Do not write files, do not give a verdict, and do not invent any detail not present in the manuscript.",
        expected_output="A grounded diagnosis (summary, field/venue/type, maturity, evidence audit, claimed contribution) plus a JSON findings array.",
    ),
    AgentRole.SCOPE_REVIEWER: RoleSpec(
        role=AgentRole.SCOPE_REVIEWER,
        description="Judges journal/venue fit and desk-rejection risk.",
        allowed_tools=WEB_READ_TOOLS,
        system_instructions=(
            "You are the scope / journal-fit reviewer. Judge whether the manuscript "
            "fits the target venue and its editorial expectations: fit (High/Medium/"
            "Low), desk-rejection risk (Low/Medium/High), the main reason, and "
            "concrete changes to improve fit. You may fetch the venue's scope page "
            "if a venue is named. Do not modify files. " + _GROUNDING_CONTRACT
        ),
        phase_purpose="Assess venue fit and desk-rejection risk, grounded in the manuscript and (if fetched) the venue scope.",
        must_not="Do not write files, do not invent the venue's policies, and do not fabricate quotes.",
        expected_output="A scope/fit assessment plus a JSON findings array.",
    ),
    AgentRole.NOVELTY_REVIEWER: RoleSpec(
        role=AgentRole.NOVELTY_REVIEWER,
        description="Audits the claimed vs actual contribution and novelty.",
        allowed_tools=WEB_READ_TOOLS,
        system_instructions=(
            "You are the novelty / contribution auditor — the highest-stakes lens. "
            "Separate the CLAIMED contribution from the ACTUAL, supported one. Flag "
            "claims that exceed the evidence, and judge whether this is an "
            "engineering artifact vs a research contribution. You may use the web to "
            "check prior work, but cite an external source ONLY if you actually "
            "fetched it; otherwise restrict novelty judgments to the paper's own "
            "positioning. Do not modify files. " + _GROUNDING_CONTRACT
        ),
        phase_purpose="Audit the contribution and novelty, grounded in the manuscript and only verified external sources.",
        must_not="Do not write files, do not cite sources you did not fetch, and do not overstate or invent prior work.",
        expected_output="A contribution/novelty audit plus a JSON findings array.",
    ),
    AgentRole.METHODOLOGY_REVIEWER: RoleSpec(
        role=AgentRole.METHODOLOGY_REVIEWER,
        description="Evaluates methodological soundness and reproducibility.",
        allowed_tools=READ_TOOLS,
        system_instructions=(
            "You are the methodology & evidence reviewer. Assess whether the method "
            "is defensible and reproducible: justified design decisions, adequate "
            "metrics, baselines, comparisons, ablations, sensitivity/threats-to-"
            "validity, and reported limitations. Tie each weakness to a concrete "
            "missing experiment or analysis. Do not modify files. " + _GROUNDING_CONTRACT
        ),
        phase_purpose="Assess methodology, evidence, and reproducibility, grounded in the manuscript.",
        must_not="Do not write files, do not assume experiments not described, and do not invent results.",
        expected_output="A methodology review plus a JSON findings array.",
    ),
    AgentRole.FIELD_EXPERT_REVIEWER: RoleSpec(
        role=AgentRole.FIELD_EXPERT_REVIEWER,
        description="Applies the conventions and expectations of the paper's field.",
        allowed_tools=READ_TOOLS,
        system_instructions=(
            "You are the field-specialist reviewer. Apply THIS paper's field's "
            "conventions (e.g. software engineering expects strong empirical "
            "evaluation; AI systems expects benchmarks/architecture/scalability; "
            "engineering education expects pedagogical validation; industrial AI "
            "expects real-world robustness/integration). Adapt to the reviewer "
            "profile's expertise if given. Each concern needs a concrete fix. Do not "
            "modify files. " + _GROUNDING_CONTRACT
        ),
        phase_purpose="Raise field-specific concerns this community would require, grounded in the manuscript.",
        must_not="Do not write files, and do not impose conventions from an unrelated field as if they were this paper's.",
        expected_output="Field-specific concerns plus a JSON findings array.",
    ),
    AgentRole.ADVERSARIAL_REVIEWER: RoleSpec(
        role=AgentRole.ADVERSARIAL_REVIEWER,
        description="The tough, skeptical 'Reviewer 2' building the case to reject.",
        allowed_tools=READ_TOOLS,
        system_instructions=(
            "You are Reviewer 2 — the tough, skeptical reviewer. Build the strongest "
            "good-faith case to REJECT this manuscript at the target venue, ranked by "
            "severity, then state exactly what must change to move to accept. Be "
            "specific and grounded in the manuscript; do NOT invent flaws. Do not "
            "modify files. " + _GROUNDING_CONTRACT
        ),
        phase_purpose="Mount the strongest grounded objections a hostile reviewer would raise.",
        must_not="Do not write files, and do not fabricate weaknesses unsupported by the manuscript.",
        expected_output="Ranked major criticisms and accept conditions, plus a JSON findings array.",
    ),
    AgentRole.FORMAT_REVIEWER: RoleSpec(
        role=AgentRole.FORMAT_REVIEWER,
        description="Checks structure, formatting, and submission-readiness requirements.",
        allowed_tools=READ_TOOLS,
        system_instructions=(
            "You are the formatting / submission-readiness reviewer. Check structure "
            "and submission requirements: length, expected sections, abstract, "
            "keywords, references, figures/tables, data availability, code "
            "availability, ethics/AI-use statement, conflict-of-interest, author "
            "contributions. Use any author-guidelines source if present. Mark each "
            "item PASS/FAIL/UNKNOWN with the fix needed. Do not modify files. "
            + _GROUNDING_CONTRACT
        ),
        phase_purpose="Produce a grounded submission checklist for the target venue.",
        must_not="Do not write files, and do not claim an element is present/absent without checking the manuscript.",
        expected_output="A submission checklist plus a JSON findings array.",
    ),
    AgentRole.GROUNDEDNESS_VERIFIER: RoleSpec(
        role=AgentRole.GROUNDEDNESS_VERIFIER,
        description="Adversarially checks that each surviving finding's quote supports its claim.",
        allowed_tools=READ_TOOLS,
        system_instructions=(
            "You are the groundedness verifier. For each finding given to you, the "
            "quote has already been confirmed to exist in the manuscript by code. "
            "Your job is the harder check: does the quote ACTUALLY support the "
            "claim, or is the claim an over-reading or misattribution? For each "
            "finding return {\"index\", \"supported\" (true/false), \"reason\"}. "
            "Default to supported=false when the quote does not clearly back the "
            "claim. Do not modify files."
        ),
        phase_purpose="Confirm each verified quote genuinely supports its claim; reject over-readings.",
        must_not="Do not write files, do not add new findings, and do not pass a claim the quote does not support.",
        expected_output="A JSON array of per-finding support verdicts.",
    ),
    AgentRole.REVISION_PLANNER: RoleSpec(
        role=AgentRole.REVISION_PLANNER,
        description="Synthesizes verified findings into a decision-ready review report.",
        allowed_tools=READ_TOOLS,
        system_instructions=(
            "You are the revision planner. Synthesize ONLY the verified findings "
            "given to you into a single decision-ready report using the exact "
            "section structure requested. Do not introduce any finding or claim no "
            "reviewer raised, and do not weaken the grounding: keep the anchors. Do "
            "not modify files."
        ),
        phase_purpose="Assemble the verified findings into the stable PAPER REVIEW REPORT structure.",
        must_not="Do not write files, do not invent new findings, and do not drop the supporting anchors.",
        expected_output="The structured PAPER REVIEW REPORT built only from verified findings.",
    ),
}
