from typing import Literal

import requests
from pydantic import BaseModel

from app.models import RadioflowExternalSuggestion


class PublishResult(BaseModel):
    ok: bool
    status: Literal["created", "deduplicated", "failed"]
    http_status: int | None = None
    suggestion_id: str | None = None
    code: str | None = None
    message: str | None = None


class RadioflowPublisher:
    def __init__(self, base_url: str, source_token: str):
        self.base_url = base_url.rstrip("/")
        self.source_token = source_token

    def publish_suggestion(self, payload: RadioflowExternalSuggestion) -> PublishResult:
        try:
            response = requests.post(
                f"{self.base_url}/api/external-suggestions",
                headers={
                    "Authorization": f"Bearer {self.source_token}",
                    "Content-Type": "application/json",
                },
                json=payload.model_dump(by_alias=True, exclude_none=True),
                timeout=30,
            )
        except requests.Timeout:
            return PublishResult(
                ok=False,
                status="failed",
                code="timeout",
                message="Request to RadioFlow timed out.",
            )
        except requests.ConnectionError:
            return PublishResult(
                ok=False,
                status="failed",
                code="connection_error",
                message="Could not connect to RadioFlow. Check RADIOFLOW_BASE_URL and that RadioFlow is running.",
            )
        except requests.RequestException as e:
            return PublishResult(
                ok=False,
                status="failed",
                code="request_error",
                message=f"RadioFlow request failed: {e}",
            )

        body = _read_json(response)
        if response.status_code in (200, 201):
            status = body.get("status", "created" if response.status_code == 201 else "deduplicated")
            return PublishResult(
                ok=True,
                status="created" if status == "created" else "deduplicated",
                http_status=response.status_code,
                suggestion_id=body.get("suggestionId"),
            )

        return _failed_result(response.status_code, body, response.text)


def _read_json(response: requests.Response) -> dict:
    try:
        body = response.json()
    except ValueError:
        return {}

    return body if isinstance(body, dict) else {}


def _failed_result(http_status: int, body: dict, response_text: str) -> PublishResult:
    if http_status in (401, 403, 400):
        return PublishResult(
            ok=False,
            status="failed",
            http_status=http_status,
            code=str(body.get("code") or _default_error_code(http_status)),
            message=str(body.get("message") or _default_error_message(http_status)),
        )

    if http_status >= 500:
        return PublishResult(
            ok=False,
            status="failed",
            http_status=http_status,
            code="radioflow_server_error",
            message=f"RadioFlow server error ({http_status}). Try again later.",
        )

    return PublishResult(
        ok=False,
        status="failed",
        http_status=http_status,
        code=str(body.get("code") or "unexpected_response"),
        message=str(body.get("message") or response_text or f"Unexpected RadioFlow response ({http_status})."),
    )


def _default_error_code(http_status: int) -> str:
    if http_status == 400:
        return "invalid_payload"
    if http_status == 401:
        return "unauthorized"
    if http_status == 403:
        return "forbidden"
    return "unexpected_response"


def _default_error_message(http_status: int) -> str:
    if http_status == 400:
        return "RadioFlow rejected the suggestion payload."
    if http_status == 401:
        return "RadioFlow authentication failed. Check RADIOFLOW_SOURCE_TOKEN."
    if http_status == 403:
        return "RadioFlow rejected the source. Check sourceKey, token, source status, and suggest_blocks capability."
    return f"Unexpected RadioFlow response ({http_status})."
