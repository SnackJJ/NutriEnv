"""The SSE assembler and its failure modes.

Every gateway convention in here was observed or reproduced: a streaming tool name can arrive
once, repeated verbatim, split into fragments, or re-sent cumulatively, and an unterminated
stream must not be mistaken for a short answer.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from email.message import Message
from http.client import IncompleteRead

import pytest

from nutrienv.io.chat import (
    _assemble_stream,
    _should_retry_without_usage,
    post_chat_completion_raw,
)

TOOLS = [
    {"type": "function", "function": {"name": "search_foods", "parameters": {}}},
    {"type": "function", "function": {"name": "get_dri", "parameters": {}}},
]


class _Response:
    """Enough of an ``http.client.HTTPResponse`` for ``for line in resp``."""

    def __init__(self, payload: bytes):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        return iter(self._payload.splitlines(keepends=True))


def _sse(frames, *, done=True) -> bytes:
    body = b"".join(("data: " + json.dumps(f) + "\n\n").encode() for f in frames)
    return body + (b"data: [DONE]\n\n" if done else b"")


def _delta(**fields) -> dict:
    return {"choices": [{"delta": fields}]}


def _finish(reason="stop") -> dict:
    return {"choices": [{"delta": {}, "finish_reason": reason}]}


def _tool_fragment(name, arguments="", index=None, call_id=None) -> dict:
    fn = {"arguments": arguments}
    if name is not None:
        fn["name"] = name
    call = {"function": fn}
    if index is not None:
        call["index"] = index
    if call_id:
        call["id"] = call_id
    return {"choices": [{"delta": {"tool_calls": [call]}}]}


@pytest.fixture
def stream(monkeypatch):
    """Patch urlopen with a scripted SSE body; returns the recorded request bodies."""

    def install(payload: bytes):
        sent: list[dict] = []

        def fake_urlopen(request, timeout=None):
            sent.append(json.loads(request.data.decode()))
            return _Response(payload)

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        return sent

    return install


def _assemble(payload, tools=TOOLS):
    return _assemble_stream(
        "http://x", {"tools": tools} if tools else {}, "k", 60.0, "err"
    )


# --- tool name conventions -------------------------------------------------------------


def test_name_sent_once_is_kept(stream):
    stream(
        _sse(
            [
                _tool_fragment("search_foods", "", 0, "c1"),
                _tool_fragment(None, '{"q":', 0),
                _tool_fragment(None, '"milk"}', 0),
            ]
        )
    )
    calls = _assemble(None)["choices"][0]["message"]["tool_calls"]
    assert calls[0]["function"]["name"] == "search_foods"
    assert calls[0]["function"]["arguments"] == '{"q":"milk"}'


def test_name_repeated_in_every_delta_is_not_doubled(stream):
    stream(
        _sse(
            [
                _tool_fragment("search_foods", '{"q":', 0, "c1"),
                _tool_fragment("search_foods", '"milk"}', 0),
            ]
        )
    )
    calls = _assemble(None)["choices"][0]["message"]["tool_calls"]
    assert calls[0]["function"]["name"] == "search_foods"


def test_name_split_into_fragments_is_joined(stream):
    stream(
        _sse([_tool_fragment("search", "", 0, "c1"), _tool_fragment("_foods", "{}", 0)])
    )
    calls = _assemble(None)["choices"][0]["message"]["tool_calls"]
    assert calls[0]["function"]["name"] == "search_foods"


def test_name_resent_cumulatively_replaces(stream):
    stream(
        _sse(
            [
                _tool_fragment("sea", "", 0, "c1"),
                _tool_fragment("search_", "", 0),
                _tool_fragment("search_foods", "{}", 0),
            ]
        )
    )
    calls = _assemble(None)["choices"][0]["message"]["tool_calls"]
    assert calls[0]["function"]["name"] == "search_foods"


def test_suffix_fragment_is_not_swallowed(stream):
    stream(
        _sse([_tool_fragment("search_food", "", 0, "c1"), _tool_fragment("s", "{}", 0)])
    )
    calls = _assemble(None)["choices"][0]["message"]["tool_calls"]
    assert calls[0]["function"]["name"] == "search_foods"


def test_parallel_calls_with_index_stay_separate(stream):
    stream(
        _sse(
            [
                _tool_fragment("search_foods", "{}", 0, "c1"),
                _tool_fragment("get_dri", "{}", 1, "c2"),
            ]
        )
    )
    calls = _assemble(None)["choices"][0]["message"]["tool_calls"]
    assert [c["function"]["name"] for c in calls] == ["search_foods", "get_dri"]


def test_parallel_calls_without_index_do_not_merge(stream):
    stream(
        _sse(
            [
                _tool_fragment("search_foods", "{}", None, "c1"),
                _tool_fragment("get_dri", "{}", None, "c2"),
            ]
        )
    )
    calls = _assemble(None)["choices"][0]["message"]["tool_calls"]
    assert [c["function"]["name"] for c in calls] == ["search_foods", "get_dri"]
    assert [c["function"]["arguments"] for c in calls] == ["{}", "{}"]


# --- truncation and unusable streams ---------------------------------------------------


def test_stream_cut_short_raises_instead_of_grading_a_partial(stream):
    stream(_sse([_delta(content='{"op": "log_'), _delta(content="meal")], done=False))
    with pytest.raises(IncompleteRead, match="without \\[DONE\\]"):
        _assemble(None)


def test_stream_without_any_frame_raises(stream):
    # A provider that ignores `stream: true` and answers with a plain JSON body.
    stream(json.dumps({"choices": [{"message": {"content": "hi"}}]}).encode())
    with pytest.raises(IncompleteRead, match="no SSE frame"):
        _assemble(None)


def test_stream_carrying_nothing_raises(stream):
    stream(_sse([]))
    with pytest.raises(IncompleteRead, match="no content"):
        _assemble(None)


def test_finish_reason_alone_terminates_a_stream(stream):
    # Some gateways omit [DONE] but do report finish_reason.
    stream(_sse([_delta(content="done"), _finish()], done=False))
    assert _assemble(None)["choices"][0]["message"]["content"] == "done"


# --- alternative framings --------------------------------------------------------------


def test_whole_message_frames_are_assembled(stream):
    stream(_sse([{"choices": [{"message": {"role": "assistant", "content": "hi"}}]}]))
    assert _assemble(None)["choices"][0]["message"]["content"] == "hi"


def test_reasoning_only_reply_is_not_an_infra_failure(stream):
    stream(_sse([_delta(reasoning_content="think"), _finish()]))
    message = _assemble(None)["choices"][0]["message"]
    assert message["content"] == ""
    assert message["reasoning_content"] == "think"


def test_usage_is_returned_and_stream_options_can_be_withheld(stream):
    payload = _sse(
        [
            _delta(content="x"),
            {"choices": [], "usage": {"completion_tokens": 3}},
            _finish(),
        ]
    )
    sent = stream(payload)
    assert _assemble(None)["usage"] == {"completion_tokens": 3}
    assert sent[0]["stream_options"] == {"include_usage": True}

    sent = stream(payload)
    _assemble_stream("http://x", {}, "k", 60.0, "err", include_usage=False)
    assert "stream_options" not in sent[0]


# --- the optional-field downgrade ------------------------------------------------------


def test_should_retry_without_usage_only_on_a_streaming_400():
    err400 = urllib.error.HTTPError("u", 400, "bad", Message(), None)
    err429 = urllib.error.HTTPError("u", 429, "slow", Message(), None)
    assert _should_retry_without_usage(err400, stream=True, include_usage=True)
    assert not _should_retry_without_usage(err400, stream=True, include_usage=False)
    assert not _should_retry_without_usage(err400, stream=False, include_usage=True)
    assert not _should_retry_without_usage(err429, stream=True, include_usage=True)


def test_rejected_stream_options_is_dropped_and_the_call_succeeds(monkeypatch):
    sent: list[dict] = []

    def fake_urlopen(request, timeout=None):
        body = json.loads(request.data.decode())
        sent.append(body)
        if "stream_options" in body:
            raise urllib.error.HTTPError("u", 400, "unknown field", Message(), None)
        return _Response(_sse([_delta(content="ok"), _finish()]))

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    body = post_chat_completion_raw("http://x", {}, "k", 60.0, retries=3)
    assert body["choices"][0]["message"]["content"] == "ok"
    assert (
        len(sent) == 2
        and "stream_options" in sent[0]
        and "stream_options" not in sent[1]
    )
