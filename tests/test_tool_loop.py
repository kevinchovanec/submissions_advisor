"""The agent tool loop: hard stops, error signalling, and the log_submission guard.

Drives stream_response against a scripted fake client, so no API key or network is
needed. The stops matter because the loop runs on the user's own API key — an
unbounded one bills them indefinitely.
"""

from __future__ import annotations

import agent


# --- fake Anthropic client -------------------------------------------------

class _Block:
    def __init__(self, type_, text=None, name=None, input_=None, id_=None):
        self.type = type_
        self.text = text
        self.name = name
        self.input = input_ or {}
        self.id = id_ or f"toolu_{name}"

    def model_dump(self, mode=None, exclude_none=False):
        d = {"type": self.type}
        if self.text is not None:
            d["text"] = self.text
        if self.name is not None:
            d.update(name=self.name, input=self.input, id=self.id)
        return d


class _Usage:
    input_tokens = 10
    output_tokens = 5
    cache_read_input_tokens = 0
    cache_creation_input_tokens = 0


class _Message:
    def __init__(self, content, stop_reason="end_turn"):
        self.content = content
        self.stop_reason = stop_reason
        self.usage = _Usage()


class _Event:
    """Minimal stand-in for an SDK stream event."""

    def __init__(self, type_, content_block=None, delta=None):
        self.type = type_
        self.content_block = content_block
        self.delta = delta


class _Delta:
    def __init__(self, type_, text=None):
        self.type = type_
        self.text = text


class _FakeStream:
    """Replays a message as the event sequence the SDK would produce."""

    def __init__(self, message):
        self._message = message

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        for b in self._message.content:
            yield _Event("content_block_start", content_block=b)
            if b.type == "text":
                yield _Event("content_block_delta", delta=_Delta("text_delta", b.text))
            yield _Event("content_block_stop")

    def get_final_message(self):
        return self._message


class _FakeMessages:
    def __init__(self, script):
        self._script = list(script)
        self.calls = 0
        self.last_kwargs = None

    def stream(self, **kwargs):
        self.calls += 1
        self.last_kwargs = kwargs
        # Repeat the final scripted response if the loop asks for more.
        msg = self._script.pop(0) if self._script else _Message([_Block("text", text="done")])
        return _FakeStream(msg)


class _FakeClient:
    def __init__(self, script):
        self.messages = _FakeMessages(script)


def _drive(storage, journals, script, **kw):
    """Run stream_response to completion; return (yielded text, history, usage, client)."""
    client = _FakeClient(script)
    import anthropic
    original = anthropic.Anthropic
    anthropic.Anthropic = lambda **k: client
    try:
        gen = agent.stream_response([], "hello", journals, storage, api_key="unused", **kw)
        chunks = []
        try:
            while True:
                chunks.append(next(gen))
        except StopIteration as stop:
            history, usage = stop.value
        return "".join(chunks), history, usage, client
    finally:
        anthropic.Anthropic = original


def _tool_results(history):
    """Every tool_result block in the built history."""
    out = []
    for msg in history:
        content = msg.get("content")
        if msg["role"] == "user" and isinstance(content, list):
            out.extend(b for b in content if isinstance(b, dict) and b.get("type") == "tool_result")
    return out


# --- tests -----------------------------------------------------------------

class TestIterationCap:
    def test_loop_stops_at_the_cap(self, storage, journals, monkeypatch):
        monkeypatch.setattr(agent, "MAX_TOOL_ITERATIONS", 3)
        monkeypatch.setattr(agent, "fetch_page", lambda url, max_chars=None: _ok_page())
        forever = [
            _Message([_Block("tool_use", name="fetch_page", input_={"url": "https://a.example"}, id_=f"t{i}")])
            for i in range(10)
        ]
        text, _, _, client = _drive(storage, journals, forever)
        assert client.messages.calls == 3
        assert "Stopped after 3 tool rounds" in text

    def test_normal_conversation_stops_when_no_tools_are_called(self, storage, journals):
        text, _, _, client = _drive(storage, journals, [_Message([_Block("text", text="Here you go.")])])
        assert client.messages.calls == 1
        assert text == "Here you go."

    def test_max_tokens_stop_reason_is_surfaced(self, storage, journals):
        script = [_Message([_Block("text", text="cut off mid")], stop_reason="max_tokens")]
        text, _, _, client = _drive(storage, journals, script)
        assert "hit the length limit" in text
        assert client.messages.calls == 1


class TestFetchBudget:
    def test_budget_is_enforced_and_reported_as_an_error(self, storage, journals, monkeypatch):
        monkeypatch.setattr(agent, "MAX_FETCHES_PER_TURN", 2)
        monkeypatch.setattr(agent, "MAX_TOOL_ITERATIONS", 6)
        monkeypatch.setattr(agent, "fetch_page", lambda url, max_chars=None: _ok_page())
        script = [
            _Message([_Block("tool_use", name="fetch_page", input_={"url": f"https://{i}.example"}, id_=f"t{i}")])
            for i in range(5)
        ]
        text, history, _, _ = _drive(storage, journals, script)
        assert "Fetch budget reached (2 pages)" in text
        exhausted = [r for r in _tool_results(history) if "budget for this turn is used up" in str(r["content"])]
        assert exhausted, "budget exhaustion must reach the model"
        assert all(r.get("is_error") for r in exhausted)


class TestIsErrorFlag:
    def test_failed_fetch_is_marked_is_error(self, storage, journals, monkeypatch):
        import pagefetch
        monkeypatch.setattr(
            agent, "fetch_page",
            lambda url, max_chars=None: pagefetch.PageFetch(url=url, error="Could not fetch page: 404"),
        )
        script = [
            _Message([_Block("tool_use", name="fetch_page", input_={"url": "https://x.example"})]),
            _Message([_Block("text", text="ok")]),
        ]
        _, history, _, _ = _drive(storage, journals, script)
        results = _tool_results(history)
        assert results[0]["is_error"] is True

    def test_successful_fetch_is_not_marked(self, storage, journals, monkeypatch):
        monkeypatch.setattr(agent, "fetch_page", lambda url, max_chars=None: _ok_page())
        script = [
            _Message([_Block("tool_use", name="fetch_page", input_={"url": "https://x.example"})]),
            _Message([_Block("text", text="ok")]),
        ]
        _, history, _, _ = _drive(storage, journals, script)
        assert "is_error" not in _tool_results(history)[0]

    def test_unknown_tool_is_marked(self, storage, journals):
        script = [
            _Message([_Block("tool_use", name="nonexistent_tool", input_={})]),
            _Message([_Block("text", text="ok")]),
        ]
        _, history, _, _ = _drive(storage, journals, script)
        assert _tool_results(history)[0]["is_error"] is True

    def test_missing_template_is_marked(self, storage, journals):
        script = [
            _Message([_Block("tool_use", name="get_cover_letter_template", input_={"name": "nope"})]),
            _Message([_Block("text", text="ok")]),
        ]
        _, history, _, _ = _drive(storage, journals, script)
        assert _tool_results(history)[0]["is_error"] is True


class TestLogSubmissionGuard:
    SCRIPT_TAIL = _Message([_Block("text", text="logged")])

    def _log_script(self, slug, journal="Other Mag"):
        return [
            _Message([_Block("tool_use", name="log_submission", input_={"story_slug": slug, "journal": journal})]),
            _Message([_Block("text", text="ok")]),
        ]

    def test_selected_story_is_logged(self, storage, journals):
        _, history, usage, _ = _drive(
            storage, journals, self._log_script("what-was-left"),
            story_context="x", allowed_slugs={"what-was-left"},
        )
        assert storage.logged == [("what-was-left", "Other Mag", "pending", "")]
        assert usage["wrote_data"] is True
        assert "is_error" not in _tool_results(history)[0]

    def test_unselected_story_is_refused(self, storage, journals):
        """Guards against a misattributed submission landing in the wrong story file."""
        text, history, usage, _ = _drive(
            storage, journals, self._log_script("staging"),
            story_context="x", allowed_slugs={"what-was-left"},
        )
        assert storage.logged == [], "nothing may be written for an unloaded story"
        assert usage["wrote_data"] is False
        result = _tool_results(history)[0]
        assert result["is_error"] is True
        assert "not one of the stories loaded" in result["content"]
        assert "isn't loaded in this conversation" in text

    def test_storage_failure_is_reported_as_an_error(self, storage, journals):
        storage.log_should_raise = True
        _, history, usage, _ = _drive(
            storage, journals, self._log_script("what-was-left"),
            allowed_slugs={"what-was-left"},
        )
        result = _tool_results(history)[0]
        assert result["is_error"] is True
        assert "Could not log submission" in result["content"]
        assert usage["wrote_data"] is False

    def test_wrote_data_flag_drives_client_invalidation(self, storage, journals):
        """usage['wrote_data'] is what makes the SSE done frame ask the client to
        refetch, so a just-logged journal is excluded without a page reload."""
        _, _, usage, _ = _drive(storage, journals, [_Message([_Block("text", text="no writes")])])
        assert usage["wrote_data"] is False


class TestGetStoryTool:
    def test_returns_a_full_card_for_a_roster_story(self, storage, journals):
        script = [
            _Message([_Block("tool_use", name="get_story", input_={"slug": "staging"})]),
            _Message([_Block("text", text="ok")]),
        ]
        _, history, _, _ = _drive(storage, journals, script)
        result = _tool_results(history)[0]
        assert "All the World is Staging" in result["content"]
        assert "is_error" not in result

    def test_unknown_slug_is_an_error(self, storage, journals):
        script = [
            _Message([_Block("tool_use", name="get_story", input_={"slug": "ghost"})]),
            _Message([_Block("text", text="ok")]),
        ]
        _, history, _, _ = _drive(storage, journals, script)
        result = _tool_results(history)[0]
        assert result["is_error"] is True
        assert "No story with slug" in result["content"]


class TestRequestShape:
    def test_journal_block_is_first_and_carries_the_1h_breakpoint(self, storage, journals):
        _, _, _, client = _drive(
            storage, journals, [_Message([_Block("text", text="hi")])], story_context="STORY CARD",
        )
        opening = client.messages.last_kwargs["messages"][0]["content"]
        assert opening[0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
        assert "ranked by prestige score" in opening[0]["text"]
        assert "cache_control" not in opening[1]
        assert "STORY CARD" in opening[1]["text"]

    def test_system_prompt_is_sent_without_its_own_breakpoint(self, storage, journals):
        _, _, _, client = _drive(storage, journals, [_Message([_Block("text", text="hi")])])
        assert isinstance(client.messages.last_kwargs["system"], str)

    def test_thinking_is_announced_so_the_ui_is_never_silent(self, storage, journals):
        """Thinking blocks stream with empty text, so without this the user watches a
        motionless '...' for several seconds and assumes it has hung."""
        script = [_Message([_Block("thinking", text=""), _Block("text", text="Here you go.")])]
        text, _, _, _ = _drive(storage, journals, script)
        assert "*Thinking...*" in text
        assert text.index("*Thinking...*") < text.index("Here you go.")

    def test_thinking_is_announced_only_once(self, storage, journals):
        script = [_Message([
            _Block("thinking", text=""), _Block("thinking", text=""), _Block("text", text="ok"),
        ])]
        text, _, _, _ = _drive(storage, journals, script)
        assert text.count("*Thinking...*") == 1

    def test_no_thinking_block_means_no_announcement(self, storage, journals):
        text, _, _, _ = _drive(storage, journals, [_Message([_Block("text", text="quick answer")])])
        assert "*Thinking...*" not in text
        assert text == "quick answer"

    def test_thinking_is_set_explicitly_with_room_to_think(self, storage, journals):
        """max_tokens caps thinking AND reply together, and the meaning of an omitted
        `thinking` field flipped between Sonnet 4.6 and 5. Both are pinned here so a
        future model bump can't silently truncate replies."""
        _, _, _, client = _drive(storage, journals, [_Message([_Block("text", text="hi")])])
        kwargs = client.messages.last_kwargs
        assert kwargs["thinking"] == {"type": "adaptive"}
        assert kwargs["max_tokens"] >= 16000

    def test_all_tools_are_offered(self, storage, journals):
        _, _, _, client = _drive(storage, journals, [_Message([_Block("text", text="hi")])])
        names = {t["name"] for t in client.messages.last_kwargs["tools"]}
        assert names == {
            "fetch_page", "get_journal_details", "get_editor_feedback",
            "log_submission", "get_cover_letter_template", "get_story",
        }


def _ok_page():
    import pagefetch
    return pagefetch.PageFetch(url="https://x.example", text="Guidelines: up to 5000 words.", links=[])
