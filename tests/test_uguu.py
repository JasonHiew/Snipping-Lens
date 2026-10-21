import asyncio

import httpx
import pytest

from sniplens.api import ApiProtocolError, ApiResponseError, UguuClient


class ScriptedTransport(httpx.MockTransport):
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        super().__init__(self._handle)

    def _handle(self, request):
        self.requests.append(request)
        return self.responses.pop(0)


def upload(transport):
    client = UguuClient(client=httpx.AsyncClient(transport=transport))
    return asyncio.run(client.upload_image(b"image"))


def test_upload_returns_url():
    transport = ScriptedTransport(
        [httpx.Response(200, json={"success": True, "files": [{"url": "https://h.uguu.se/abc.png"}]})]
    )
    assert upload(transport) == "https://h.uguu.se/abc.png"
    request = transport.requests[0]
    assert request.method == "POST"
    assert request.url == "https://uguu.se/upload"
    assert b'name="files[]"' in request.content
    assert b'filename="snip.png"' in request.content
    assert b"Content-Type: image/png" in request.content


@pytest.mark.parametrize(
    "body",
    [
        {"success": False, "files": [{"url": "https://h.uguu.se/abc.png"}]},
        {"success": True, "files": []},
        {"success": True, "files": [{"url": "http://h.uguu.se/abc.png"}]},
        ["not", "an", "object"],
    ],
)
def test_unexpected_json_raises_protocol_error(body):
    with pytest.raises(ApiProtocolError):
        upload(ScriptedTransport([httpx.Response(200, json=body)]))


def test_non_json_body_raises_protocol_error():
    with pytest.raises(ApiProtocolError):
        upload(ScriptedTransport([httpx.Response(200, text="<html>error</html>")]))


def test_error_status_raises_response_error():
    with pytest.raises(ApiResponseError) as excinfo:
        upload(ScriptedTransport([httpx.Response(413, text="too large")]))
    assert excinfo.value.status_code == 413


def test_retryable_status_is_retried(monkeypatch):
    async def no_sleep(_delay):
        pass

    monkeypatch.setattr("sniplens.api.litterbox.asyncio.sleep", no_sleep)
    transport = ScriptedTransport(
        [
            httpx.Response(503),
            httpx.Response(200, json={"success": True, "files": [{"url": "https://h.uguu.se/abc.png"}]}),
        ]
    )
    assert upload(transport) == "https://h.uguu.se/abc.png"
    assert len(transport.requests) == 2
