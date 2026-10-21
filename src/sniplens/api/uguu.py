import json

from sniplens.api.errors import ApiProtocolError, ApiResponseError
from sniplens.api.litterbox import LitterboxClient


class UguuClient(LitterboxClient):
    """Uploader for uguu.se, which this fork uses instead of Litterbox. It
    reuses Litterbox's client setup and replay-safe retry policy; only the
    request shape and the JSON response differ."""

    API_URL = "https://uguu.se/upload"

    async def upload_image(self, image, filename="snip.png", expiry=None):
        # uguu.se has a fixed expiry, so `expiry` is accepted only to keep the
        # call signature interchangeable with LitterboxClient
        return await super().upload_image(image, filename, expiry)

    def _build_request(self, image, filename, expiry):
        return self._client.build_request(
            "POST",
            self.API_URL,
            files={"files[]": (filename, image, "image/png")},
        )

    def _raise_for_api_error(self, response):
        if response.is_success:
            return
        raise ApiResponseError(
            f"Uguu upload failed with status {response.status_code}",
            status_code=response.status_code,
            body=response.text,
        )

    def _decode_response(self, response):
        try:
            data = response.json()
        except json.JSONDecodeError:
            raise ApiProtocolError(f"Uguu returned an unexpected response: {response.text[:200]}")
        url = ""
        if isinstance(data, dict) and data.get("success") and data.get("files"):
            url = str(data["files"][0].get("url", ""))
        if not url.startswith("https://"):
            raise ApiProtocolError(f"Uguu returned an unexpected response: {response.text[:200]}")
        return url
