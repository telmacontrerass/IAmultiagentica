"""Deterministic rules for final-answer groundedness."""

from __future__ import annotations

import re

from ci2lab.harness.grounding_review.evidence import EvidenceLedger

URL_RE = re.compile(r"https?://[^\s)\]>\"']+")

_UNCERTAINTY_RE = re.compile(
    r"\b("
    r"i (do not|don't|cannot|can't) know|"
    r"no (lo )?(se|sé|puedo confirmar|puedo verificar)|"
    r"cannot verify|can't verify|not enough evidence|"
    r"no tengo evidencia|no hay evidencia"
    r")\b",
    re.IGNORECASE,
)
_CURRENT_RE = re.compile(
    r"\b("
    r"latest|current|currently|today|now|as of|recent|newest|"
    r"price|stock|exchange rate|version|release|ceo|president|"
    r"ultimo|último|actual|actualmente|hoy|ahora|reciente|"
    r"precio|cotizacion|cotización|version|versión|lanzamiento|"
    r"presidente|consejero delegado|ceo"
    r")\b",
    re.IGNORECASE,
)
_ACTION_CLAIM_RE = re.compile(
    r"\b("
    r"created|wrote|updated|modified|edited|patched|implemented|fixed|deleted|renamed|"
    r"cre[eé]|cree|he creado|escrib[ií]|actualic[eé]|modifiqu[eé]|edit[eé]|"
    r"parche[eé]|implement[eé]|arregl[eé]|corrig[eé]|borr[eé]|renombr[eé]"
    r")\b",
    re.IGNORECASE,
)
_COMMAND_CLAIM_RE = re.compile(
    r"\b("
    r"ran|executed|tested|tests? passed|all tests pass|exit code|"
    r"ejecut[eé]|corr[ií] las pruebas|tests? pas|pruebas? pas|codigo de salida|"
    r"c[oó]digo de salida"
    r")\b",
    re.IGNORECASE,
)
_PROJECT_CLAIM_RE = re.compile(
    r"("
    r"\b[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+\.(py|md|json|yaml|yml|toml|js|ts|tsx|css|html|txt)\b|"
    r"\b(the|this|el|este)\s+(repo|repository|project|codebase|archivo|fichero|"
    r"repositorio|proyecto)\s+(uses|contains|has|is|usa|contiene|tiene|est[aá])\b|"
    r"\b(defined in|located in|se encuentra en|definido en)\b"
    r")",
    re.IGNORECASE,
)
_SOURCE_CLAIM_RE = re.compile(
    r"\b(according to|source|sources|citation|segun|según|fuente|fuentes|cita)\b",
    re.IGNORECASE,
)
_NUMERIC_FACT_RE = re.compile(
    r"\b\d+(?:[.,]\d+)?\s?(%|eur|usd|gbp|€|\$|ms|s|kg|km|mb|gb|tb|tokens?)\b",
    re.IGNORECASE,
)
# A "no-regression" claim: the answer asserts the change is safe BEYOND the
# specific thing it fixed ("nothing else broke"). Substantiating this needs a
# broad check, not just the one test tied to the fix — see _ran_broad_check.
_NO_REGRESSION_RE = re.compile(
    r"("
    r"no other (behaviou?rs?|functionality|features?|tests?|code|logic)|"
    r"nothing else (was |is )?(broke|broken|affected|changed|impacted)|"
    r"without (breaking|affecting|impacting|changing) (any |anything |other )|"
    r"did(n't| not) break|does(n't| not) break|didn't affect|does not affect|"
    r"no regressions?|no side.?effects?|"
    r"sin romper|sin afectar|sin impactar|no rompe|no afecta|"
    r"ninguna otra (funcionalidad|prueba|parte|caracter[ií]stica)"
    r")",
    re.IGNORECASE,
)
# A test/check runner in a bash command.
_TEST_RUNNER_RE = re.compile(
    r"\b("
    r"pytest|py\.test|unittest|tox|nox|nosetests|"
    r"go test|cargo test|npm (run )?test|yarn test|pnpm test|"
    r"make (test|check)|rspec|jest|vitest|mocha|ctest|gradle test|mvn test"
    r")\b",
    re.IGNORECASE,
)
# The run is NARROWED to a specific file/module/node/selector, so it cannot
# substantiate a claim about the WHOLE project's behaviour.
_TEST_NARROWED_RE = re.compile(
    r"(::|\s-k[\s=]|[\w./-]+\.(py|js|ts|tsx|jsx|go|rb|rs|java|cs|php)\b)",
    re.IGNORECASE,
)


# Identifier-shaped codes (ERR-4219, JIRA-1042): uppercase tag, dash, digits.
# An answer may only state one if it appears in the prompt or in this turn's
# tool evidence — these are exactly the tokens weak models confabulate.
_CODE_TOKEN_RE = re.compile(r"\b[A-Z][A-Z0-9]{1,9}-\d{2,6}\b")

# Well-known public identifiers whose numbers are world knowledge, not
# workspace facts (standards, algorithms). Never treated as invented.
_KNOWN_CODE_PREFIXES = frozenset(
    {"ISO", "RFC", "IEEE", "IEC", "ANSI", "UTF", "SHA", "AES", "RSA", "COVID"}
)


def _contains_uncertainty(answer: str) -> bool:
    return bool(_UNCERTAINTY_RE.search(answer))


def _ran_broad_check(ledger: EvidenceLedger) -> bool:
    """True when a successful bash run invoked a test/check runner un-narrowed.

    A whole-suite run (``pytest -q``, ``make test``) can ground a no-regression
    claim; a run scoped to a single file/node (``pytest test_x.py``, ``... -k
    foo``) cannot — it only re-confirms the thing the agent set out to fix.
    """
    for record in ledger.records:
        if not record.ok or record.tool_name != "bash":
            continue
        command = str(record.arguments.get("command", ""))
        if _TEST_RUNNER_RE.search(command) and not _TEST_NARROWED_RE.search(command):
            return True
    return False


def _urls_not_in_evidence(answer: str, ledger: EvidenceLedger) -> list[str]:
    evidence = ledger.evidence_text
    return [url for url in URL_RE.findall(answer) if url not in evidence]


def _code_tokens_not_in_evidence(answer: str, ledger: EvidenceLedger) -> list[str]:
    haystack = ledger.evidence_text.lower()
    return [
        token
        for token in _CODE_TOKEN_RE.findall(answer)
        if token.split("-", 1)[0] not in _KNOWN_CODE_PREFIXES and token.lower() not in haystack
    ]


def find_grounding_issues(answer: str, ledger: EvidenceLedger) -> list[str]:
    """Return concrete issues that make the final answer unsafe to present.

    The rules are deliberately narrow and evidence-based. They do not attempt
    broad semantic truth evaluation; they catch answer patterns that need real
    support from tools or the user prompt.
    """
    text = (answer or "").strip()
    if not text or _contains_uncertainty(text):
        return []

    issues: list[str] = []
    unsupported_urls = _urls_not_in_evidence(text, ledger)
    if unsupported_urls:
        issues.append(
            "The answer includes URL(s) that were not present in the prompt or tool evidence: "
            + ", ".join(sorted(set(unsupported_urls)))
        )

    # Only meaningful on evidence-bearing turns: in plain conversation (no tool
    # records) code-shaped tokens are ordinary prose, not workspace findings.
    if ledger.records:
        invented_codes = _code_tokens_not_in_evidence(text, ledger)
        if invented_codes:
            issues.append(
                "The answer states identifier-like code(s) that appear nowhere in the "
                "prompt or this turn's tool evidence: "
                + ", ".join(sorted(set(invented_codes)))
                + ". Do not invent codes; re-check with the tools and quote the real value."
            )

    if _CURRENT_RE.search(text) and not (
        ledger.has_web_evidence or ledger.has_read_evidence or ledger.has_mutation_evidence
    ):
        issues.append(
            "The answer makes current, recent, price, version, or public-role claims without "
            "web/read evidence from this turn."
        )

    if _ACTION_CLAIM_RE.search(text) and not ledger.has_mutation_evidence:
        issues.append(
            "The answer claims files or workspace state were changed, but no successful mutating "
            "tool result supports that claim."
        )

    if _COMMAND_CLAIM_RE.search(text) and not ledger.has_runtime_evidence:
        issues.append(
            "The answer claims a command/test/check was run or passed, but no successful runtime "
            "tool result supports that claim."
        )

    if (
        _NO_REGRESSION_RE.search(text)
        and ledger.has_mutation_evidence
        and not _ran_broad_check(ledger)
    ):
        issues.append(
            "The answer claims no other behaviour/functionality was broken after a code change, "
            "but the evidence shows no broad verification: the project's full test suite/checks "
            "were never run un-narrowed (only a scoped run, or none). Run the whole suite, and "
            "check the callers of any shared code you changed, before claiming no regressions."
        )

    if _PROJECT_CLAIM_RE.search(text) and not (
        ledger.has_read_evidence or ledger.has_mutation_evidence or ledger.has_runtime_evidence
    ):
        issues.append(
            "The answer makes repository, file, or codebase claims without read/runtime evidence "
            "from this turn."
        )

    if _SOURCE_CLAIM_RE.search(text) and not (ledger.has_web_evidence or ledger.has_read_evidence):
        issues.append(
            "The answer refers to sources or citations without fetched/read source evidence."
        )

    if _NUMERIC_FACT_RE.search(text) and not (
        ledger.has_web_evidence
        or ledger.has_read_evidence
        or ledger.has_runtime_evidence
        or ledger.has_mutation_evidence
        or "calc" in ledger.successful_tools
        or "symcalc" in ledger.successful_tools
    ):
        issues.append(
            "The answer states numeric measured facts without calculation, read, web, or runtime "
            "evidence."
        )

    return issues
