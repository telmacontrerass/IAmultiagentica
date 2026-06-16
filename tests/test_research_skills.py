from __future__ import annotations

import json
import shutil
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from ci2lab.harness import AgentConfig, default_selection, run_agent
from ci2lab.harness.llm_client import LLMResponse
from ci2lab.harness.tools.skill_tool import invoke_skill


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _mount_skill(workspace: Path, skill_name: str) -> None:
    src = _repo_root() / "ci2lab" / "harness" / "skills" / "builtin" / skill_name / "SKILL.md"
    dst = workspace / ".ci2lab" / "skills" / skill_name
    dst.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst / "SKILL.md")


def _serve_fixture_dir(directory: Path):
    handler = partial(SimpleHTTPRequestHandler, directory=str(directory))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _json_review_from_fetched(tool_content: str, url: str) -> str:
    normalized = " ".join(tool_content.split())
    assert "Deterministic API Cache Guide" in tool_content
    assert "Use ETag and If-None-Match to avoid unnecessary payload downloads." in tool_content
    assert "Never cache responses that include user-specific secrets." in tool_content
    assert (
        "does not cover authentication flows, key rotation, or distributed cache invalidation."
        in normalized
    )

    payload = {
        "url": url,
        "title": "Deterministic API Cache Guide",
        "key_points": [
            "Uses ETag-based revalidation with If-None-Match.",
            "Uses TTL cache with explicit expiry metadata.",
            "Uses exponential backoff for transient failures.",
        ],
        "relevant_api_or_concepts": [
            "ETag",
            "If-None-Match",
            "TTL",
            "exponential backoff",
        ],
        "constraints_or_warnings": [
            "Warning: stale data can appear during upstream outages.",
            "Limitation: retries are capped at 3 attempts per request.",
        ],
        "quoted_evidence": [
            "Use ETag and If-None-Match to avoid unnecessary payload downloads.",
            "Never cache responses that include user-specific secrets.",
        ],
        "practical_recommendations": [
            "Implement ETag/If-None-Match revalidation for GET endpoints.",
            "Treat secret-bearing responses as non-cacheable.",
            "Cap retries and log retry exhaustion events.",
        ],
        "unknowns_or_not_verified": [
            "Authentication flows are not covered.",
            "Key rotation behavior is not covered.",
            "Distributed cache invalidation is not covered.",
        ],
    }
    return json.dumps(payload, ensure_ascii=False)


def test_research_skill_contract_is_strict(tmp_path: Path) -> None:
    _mount_skill(tmp_path, "research_web_doc_review")
    cfg = AgentConfig(cwd=str(tmp_path))
    prompt = invoke_skill(
        cfg,
        "research_web_doc_review",
        "http://127.0.0.1:9999/research_doc_sample.html",
    )
    assert "Do not use internet search, memory, or external sources." in prompt
    assert "Include short verbatim quotes from the fetched text as evidence." in prompt
    assert "`unknowns_or_not_verified`" in prompt
    assert cfg.skill_allowed_tools == frozenset({"web_fetch"})


def test_research_web_doc_review_offline_deterministic(tmp_path: Path) -> None:
    _mount_skill(tmp_path, "research_web_doc_review")
    fixture_dir = _repo_root() / "tests" / "fixtures" / "web"
    server, thread = _serve_fixture_dir(fixture_dir)
    url = f"http://127.0.0.1:{server.server_port}/research_doc_sample.html"

    selection = default_selection("test:1b")
    config = AgentConfig(
        cwd=str(tmp_path),
        stream=False,
        auto_confirm=True,
        run_log_enabled=False,
        max_rounds=6,
    )

    call_count = {"n": 0}

    def fake_chat(messages, *, tools=None):  # noqa: ANN001
        call_count["n"] += 1
        if call_count["n"] == 1:
            return LLMResponse(
                content="",
                tool_calls=[{
                    "id": "c1",
                    "function": {
                        "name": "skill",
                        "arguments": json.dumps(
                            {"skill_name": "research_web_doc_review", "args": url}
                        ),
                    },
                }],
            )
        if call_count["n"] == 2:
            return LLMResponse(
                content="",
                tool_calls=[{
                    "id": "c2",
                    "function": {
                        "name": "web_fetch",
                        "arguments": json.dumps({"url": url}),
                    },
                }],
            )
        tool_msgs = [m for m in messages if isinstance(m, dict) and m.get("role") == "tool"]
        fetched = next(
            (m.get("content", "") for m in reversed(tool_msgs) if "Fetched http://127.0.0.1:" in str(m.get("content", ""))),
            "",
        )
        return LLMResponse(content=_json_review_from_fetched(fetched, url), tool_calls=[])

    try:
        with patch("ci2lab.harness.query.loop.LLMClient") as MockClient:
            MockClient.return_value.chat.side_effect = fake_chat
            result = run_agent(
                f"Use skill research_web_doc_review for {url}",
                selection,
                config=config,
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    parsed = json.loads(result)
    required = {
        "url",
        "title",
        "key_points",
        "relevant_api_or_concepts",
        "constraints_or_warnings",
        "quoted_evidence",
        "practical_recommendations",
        "unknowns_or_not_verified",
    }
    assert set(parsed.keys()) == required
    assert parsed["url"] == url
    assert len(parsed["quoted_evidence"]) >= 2
    assert parsed["quoted_evidence"][0] in (
        "Use ETag and If-None-Match to avoid unnecessary payload downloads.",
        "Never cache responses that include user-specific secrets.",
    )
    all_text = json.dumps(parsed, ensure_ascii=False)
    assert all("http" not in item.lower() or url in item for item in parsed["practical_recommendations"])
    assert "wikipedia.org" not in all_text.lower()
    assert "arxiv.org" not in all_text.lower()
    assert any("not covered" in item.lower() for item in parsed["unknowns_or_not_verified"])


def test_research_web_vs_repo_skill_contract(tmp_path: Path) -> None:
    _mount_skill(tmp_path, "research_web_vs_repo")
    cfg = AgentConfig(cwd=str(tmp_path))
    prompt = invoke_skill(
        cfg,
        "research_web_vs_repo",
        "url=http://127.0.0.1:9999/research_doc_sample.html file=sample_path_handler.py",
    )
    assert "Do not use external sources, search, or unstated assumptions." in prompt
    assert "Do not modify files." in prompt
    assert "`changes_not_recommended`" in prompt
    assert cfg.skill_allowed_tools == frozenset({"web_fetch", "read_file"})


def test_research_web_vs_repo_offline_deterministic(tmp_path: Path) -> None:
    _mount_skill(tmp_path, "research_web_vs_repo")

    src_file = _repo_root() / "tests" / "fixtures" / "research_repo" / "sample_path_handler.py"
    local_file = tmp_path / "sample_path_handler.py"
    shutil.copy2(src_file, local_file)

    fixture_dir = _repo_root() / "tests" / "fixtures" / "web"
    server, thread = _serve_fixture_dir(fixture_dir)
    url = f"http://127.0.0.1:{server.server_port}/research_doc_sample.html"

    selection = default_selection("test:1b")
    config = AgentConfig(
        cwd=str(tmp_path),
        stream=False,
        auto_confirm=True,
        run_log_enabled=False,
        max_rounds=8,
    )
    rel_path = "sample_path_handler.py"
    call_count = {"n": 0}

    def fake_chat(messages, *, tools=None):  # noqa: ANN001
        call_count["n"] += 1
        if call_count["n"] == 1:
            return LLMResponse(
                content="",
                tool_calls=[{
                    "id": "c1",
                    "function": {
                        "name": "skill",
                        "arguments": json.dumps(
                            {
                                "skill_name": "research_web_vs_repo",
                                "args": f"url={url} file={rel_path}",
                            }
                        ),
                    },
                }],
            )
        if call_count["n"] == 2:
            return LLMResponse(
                content="",
                tool_calls=[{
                    "id": "c2",
                    "function": {
                        "name": "web_fetch",
                        "arguments": json.dumps({"url": url}),
                    },
                }],
            )
        if call_count["n"] == 3:
            return LLMResponse(
                content="",
                tool_calls=[{
                    "id": "c3",
                    "function": {
                        "name": "read_file",
                        "arguments": json.dumps({"path": rel_path}),
                    },
                }],
            )

        tool_msgs = [m for m in messages if isinstance(m, dict) and m.get("role") == "tool"]
        fetched = next(
            (
                m.get("content", "")
                for m in reversed(tool_msgs)
                if "Fetched http://127.0.0.1:" in str(m.get("content", ""))
            ),
            "",
        )
        local_text = next(
            (
                m.get("content", "")
                for m in reversed(tool_msgs)
                if "normalize_user_path" in str(m.get("content", ""))
            ),
            "",
        )
        assert "Use ETag and If-None-Match to avoid unnecessary payload downloads." in fetched
        assert "Limitation: retries are capped at 3 attempts per request." in fetched
        assert "def retry_attempts() -> int:" in local_text
        assert "return 5" in local_text

        payload = {
            "url": url,
            "local_files_reviewed": [rel_path],
            "doc_facts": [
                "Doc recommends ETag and If-None-Match revalidation.",
                "Doc states retry attempts are capped at 3.",
            ],
            "repo_observations": [
                "Path handling rejects parent traversal using a ValueError.",
                "retry_attempts() currently returns 5.",
            ],
            "matches": [
                "Both doc and code include defensive handling concepts (validation/retries).",
            ],
            "gaps_or_risks": [
                "Code retry_attempts()=5 conflicts with documented cap of 3.",
            ],
            "recommended_changes": [
                "Align retry_attempts() with the documented limit of 3.",
            ],
            "changes_not_recommended": [
                "Do not remove the parent traversal guard in normalize_user_path().",
            ],
            "quoted_evidence": [
                "Use ETag and If-None-Match to avoid unnecessary payload downloads.",
                "Limitation: retries are capped at 3 attempts per request.",
            ],
            "unknowns_or_not_verified": [
                "Authentication and key rotation are not covered by the provided documentation.",
            ],
        }
        return LLMResponse(content=json.dumps(payload, ensure_ascii=False), tool_calls=[])

    try:
        with patch("ci2lab.harness.query.loop.LLMClient") as MockClient:
            MockClient.return_value.chat.side_effect = fake_chat
            result = run_agent(
                f"Compare documentation {url} against {rel_path} using research_web_vs_repo",
                selection,
                config=config,
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    parsed = json.loads(result)
    required = {
        "url",
        "local_files_reviewed",
        "doc_facts",
        "repo_observations",
        "matches",
        "gaps_or_risks",
        "recommended_changes",
        "changes_not_recommended",
        "quoted_evidence",
        "unknowns_or_not_verified",
    }
    assert set(parsed.keys()) == required
    assert parsed["url"] == url
    assert rel_path in parsed["local_files_reviewed"]
    assert parsed["quoted_evidence"]
    assert parsed["repo_observations"]
    assert parsed["matches"]
    assert parsed["gaps_or_risks"]
    assert parsed["recommended_changes"]
    assert parsed["changes_not_recommended"]
    all_text = json.dumps(parsed, ensure_ascii=False).lower()
    assert "wikipedia.org" not in all_text
    assert "arxiv.org" not in all_text

