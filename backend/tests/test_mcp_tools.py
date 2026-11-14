"""MCP ask and analyze_fit through the real protocol.

Every test drives the streamable-HTTP endpoint end to end (a JSON-RPC POST
to /mcp, stateless mode), so the scope plumbing in McpOrBrowser and the
shared guarded pipelines are exercised exactly as a recruiter-side agent
would hit them. The claim under test: the LLM tools are not an unmetered
proxy. Every cap that binds the page binds here too, keyed to an IP-derived
visitor identity because MCP clients hold no cookies.
"""

from __future__ import annotations

import dataclasses
import json
import os
import unittest
from unittest.mock import patch

# Prevent importing app.main from initializing an external RAG connection.
os.environ["USE_RAG"] = "false"

from app import jd_service, mcp_server, session_store
from app.chat_service import UNEXPECTED_ERROR_MESSAGE
from app.constants import CHAT_LIMIT_MESSAGE, GENERIC_CHAT_ERROR, JD_LIMIT_MESSAGE, JD_SENTINEL
from app.mcp_server import mcp_visitor_id

from tests.test_chat_stream import (
    ChatStreamTestCase,
    FakeAnthropic,
    FakeStreamingMessages,
    make_settings,
    parse_sse,
)
from tests.test_jd_match import REALISTIC_JD

MCP_HEADERS = {"Accept": "application/json, text/event-stream"}
REPLY = "A helpful reply about Dakota."
ANALYSIS = "## Strong Matches\n- Shipped LLM products"


def rpc(client, method: str, params: dict | None = None, *, req_id: int = 1, ip: str | None = None):
    headers = dict(MCP_HEADERS)
    if ip:
        headers["X-Forwarded-For"] = ip
    body = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        body["params"] = params
    return client.post("/mcp", headers=headers, json=body)


def mcp_call(client, tool: str, arguments: dict, **kwargs):
    return rpc(client, "tools/call", {"name": tool, "arguments": arguments}, **kwargs)


def rpc_result(response) -> dict:
    assert response.status_code == 200, response.text
    # The MCP SDK's SSE writer uses \r\n line endings.
    for event, data in parse_sse(response.text.replace("\r\n", "\n")):
        if event == "message" and "result" in data:
            return data["result"]
    raise AssertionError(f"no JSON-RPC result in response: {response.text[:400]}")


def tool_result(response) -> tuple[bool, str]:
    """(is_error, text) from a tools/call response."""
    result = rpc_result(response)
    text = "".join(block.get("text", "") for block in result.get("content", []))
    return bool(result.get("isError")), text


def tool_json(response) -> dict:
    is_error, text = tool_result(response)
    assert not is_error, text
    return json.loads(text)


class McpTestCase(ChatStreamTestCase):
    def setUp(self) -> None:
        super().setUp()
        # create() answers every non-router call with REPLY; the questions
        # below take the no-model fast path, so the first create() call is
        # the generation itself.
        FakeAnthropic.messages_api = FakeStreamingMessages(["unused"], router_label=REPLY)

    @staticmethod
    def trusted(**overrides):
        """Production-like: client IPs come from the proxy header."""
        return dataclasses.replace(make_settings(), trust_proxy_headers=True, **overrides)


class TestToolSurface(McpTestCase):
    def test_three_read_only_tools_are_listed(self) -> None:
        with self.build_client(make_settings()) as client:
            names = {tool["name"] for tool in rpc_result(rpc(client, "tools/list"))["tools"]}
        self.assertEqual(names, {"get_resume", "ask", "analyze_fit"})


class TestAsk(McpTestCase):
    def test_ask_answers_and_continues_a_session(self) -> None:
        ip = "203.0.113.9"
        with self.build_client(self.trusted()) as client:
            first = tool_json(mcp_call(
                client, "ask", {"question": "Does Dakota know Python?"}, ip=ip,
            ))
            second = tool_json(mcp_call(
                client, "ask",
                {"question": "What else?", "session_id": first["session_id"]},
                req_id=2, ip=ip,
            ))
        self.assertEqual(first["reply"], REPLY)
        self.assertEqual(first["session_id"], second["session_id"])
        self.assertFalse(first["used_rag"])
        # The second turn carries the first exchange as history.
        roles = [m["role"] for m in FakeAnthropic.messages_api.create_calls[1]["messages"]]
        self.assertEqual(roles, ["user", "assistant", "user"])

    def test_another_caller_reusing_a_session_id_gets_no_history(self) -> None:
        # MCP callers are language models, and a model may invent a session
        # id instead of passing back the one it was given. Two callers that
        # both pick "session-1" must not read each other's conversation.
        with self.build_client(self.trusted()) as client:
            tool_json(mcp_call(
                client, "ask",
                {"question": "My marker is ZEBRA-42.", "session_id": "session-1"},
                ip="203.0.113.9",
            ))
            tool_json(mcp_call(
                client, "ask",
                {"question": "What did I say?", "session_id": "session-1"},
                req_id=2, ip="203.0.113.10",
            ))
        other_callers_turn = FakeAnthropic.messages_api.create_calls[1]["messages"]
        self.assertEqual([m["role"] for m in other_callers_turn], ["user"])
        self.assertNotIn("ZEBRA-42", json.dumps(other_callers_turn))

    def test_no_conversation_memory_without_a_trustworthy_client_ip(self) -> None:
        # With no identity to bind a conversation to, a session id alone
        # must not continue one: it would be a bearer token again.
        with self.build_client(make_settings()) as client:
            first = tool_json(mcp_call(client, "ask", {"question": "Does Dakota know Python?"}))
            tool_json(mcp_call(
                client, "ask",
                {"question": "What else?", "session_id": first["session_id"]}, req_id=2,
            ))
        roles = [m["role"] for m in FakeAnthropic.messages_api.create_calls[1]["messages"]]
        self.assertEqual(roles, ["user"])

    def test_ask_binds_the_free_quota_to_the_client_ip(self) -> None:
        settings = self.trusted(free_chat_limit=1)
        with self.build_client(settings) as client:
            ok = tool_result(mcp_call(client, "ask", {"question": "Hello?"}, ip="203.0.113.9"))
            self.assertFalse(ok[0])
            blocked = tool_result(mcp_call(client, "ask", {"question": "Again?"}, ip="203.0.113.9"))
            other = tool_result(mcp_call(client, "ask", {"question": "Hello?"}, ip="203.0.113.10"))
        self.assertTrue(blocked[0])
        self.assertIn(CHAT_LIMIT_MESSAGE, blocked[1])
        self.assertFalse(other[0])
        self.assertEqual(len(FakeAnthropic.messages_api.create_calls), 2)
        # The identity is the secret-keyed derivation of the client IP.
        expected = mcp_visitor_id("203.0.113.9", settings.session_hash_secret)
        self.assertIn(expected, session_store.get_session_store()._metadata)

    def test_ask_fails_open_without_a_trustworthy_client_ip(self) -> None:
        # Behind an unconfigured proxy every caller shares one address; a
        # shared bucket would let one caller lock everyone out. Like the
        # per-IP daily cap, the binding fails open: a fresh identity per call.
        with self.build_client(make_settings(free_chat_limit=1)) as client:
            for i in range(2):
                is_error, text = tool_result(mcp_call(client, "ask", {"question": f"Q{i}?"}))
                self.assertFalse(is_error, text)

    def test_guardrail_refusals_surface_and_internal_errors_do_not(self) -> None:
        with self.build_client(make_settings()) as client:
            is_error, text = tool_result(mcp_call(client, "ask", {"question": "   "}))
            self.assertTrue(is_error)
            # FastMCP prefixes tool errors with "Error executing tool <name>:".
            self.assertTrue(text.endswith("Message cannot be empty."), text)

            FakeAnthropic.messages_api = FakeStreamingMessages(["x"], router_raises=True)
            is_error, text = tool_result(mcp_call(client, "ask", {"question": "Hello?"}))
            self.assertTrue(is_error)
            self.assertTrue(text.endswith(GENERIC_CHAT_ERROR), text)
            # The failed turn returned its daily budget unit.
            self.assertEqual(sum(session_store._daily_conversation_count.values()), 0)

            with patch.object(mcp_server, "run_json_chat_turn", side_effect=ValueError("secret-internal")):
                is_error, text = tool_result(mcp_call(client, "ask", {"question": "Hello?"}))
            self.assertTrue(is_error)
            self.assertTrue(text.endswith(UNEXPECTED_ERROR_MESSAGE), text)
            self.assertNotIn("secret-internal", text)


class TestAnalyzeFit(McpTestCase):
    def setUp(self) -> None:
        super().setUp()
        FakeAnthropic.messages_api = FakeStreamingMessages(["unused"], router_label=ANALYSIS)

    def test_analysis_on_the_primary_model_with_the_jd_fenced(self) -> None:
        with self.build_client(make_settings()) as client:
            result = tool_json(mcp_call(client, "analyze_fit", {"job_description": REALISTIC_JD}))
            # Stored under "<visitor id>:<session id>".
            (history,) = [
                stored
                for key, stored in session_store.get_session_store()._messages.items()
                if key.endswith(":" + result["session_id"])
            ]
        self.assertEqual(result["analysis"], ANALYSIS)
        self.assertNotIn("requirement_map", result)
        call = FakeAnthropic.messages_api.create_calls[0]
        self.assertEqual(call["model"], "test-opus")
        user_text = call["messages"][-1]["content"][0]["text"]
        self.assertIn("<job_description>", user_text)
        self.assertIn("Senior Product Manager, AI Platform", user_text)
        self.assertNotIn("Senior Product Manager, AI Platform", "\n".join(b["text"] for b in call["system"]))
        # Only the neutral marker is persisted, never the pasted JD.
        self.assertEqual(history[0]["content"][0]["text"], JD_SENTINEL)

    def test_daily_jd_unit_binds_per_client_ip(self) -> None:
        with self.build_client(self.trusted()) as client:  # jd_daily_limit defaults to 1
            first = tool_result(mcp_call(client, "analyze_fit", {"job_description": REALISTIC_JD}, ip="203.0.113.9"))
            second = tool_result(mcp_call(client, "analyze_fit", {"job_description": REALISTIC_JD}, ip="203.0.113.9"))
            other = tool_result(mcp_call(client, "analyze_fit", {"job_description": REALISTIC_JD}, ip="203.0.113.10"))
        self.assertFalse(first[0], first[1])
        self.assertTrue(second[0])
        self.assertIn(JD_LIMIT_MESSAGE, second[1])
        self.assertFalse(other[0], other[1])

    def test_empty_job_description_is_a_safe_error(self) -> None:
        with self.build_client(make_settings()) as client:
            is_error, text = tool_result(mcp_call(client, "analyze_fit", {"job_description": ""}))
        self.assertTrue(is_error)
        self.assertIn("Invalid arguments", text)

    def test_requirement_map_rides_along_when_jev_is_configured(self) -> None:
        async def fake_fit_map(sanitized, resume_context, settings, **_kwargs):
            return {"requirements": [{"text": "SQL", "level": 3}], "lines": ["- SQL"]}

        settings = dataclasses.replace(make_settings(), typesafe_api_key="test-typesafe-key")
        with (
            patch.object(jd_service, "build_fit_map", fake_fit_map),
            self.build_client(settings) as client,
        ):
            result = tool_json(mcp_call(client, "analyze_fit", {"job_description": REALISTIC_JD}))
        self.assertEqual(result["requirement_map"]["requirements"][0]["text"], "SQL")
        # The description is not echoed back to the caller that sent it.
        self.assertNotIn("lines", result["requirement_map"])


if __name__ == "__main__":
    unittest.main()
