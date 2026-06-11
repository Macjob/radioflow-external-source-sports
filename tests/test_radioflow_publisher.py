from unittest.mock import MagicMock, patch

import requests

from app.models import RadioflowExternalSuggestion
from app.radioflow_publisher import RadioflowPublisher


def _suggestion() -> RadioflowExternalSuggestion:
    return RadioflowExternalSuggestion(
        source_key="sports-test",
        external_content_id="sports-match-123",
        title="Hoy juega Colo-Colo",
        description="Colo-Colo vs Other Team a las 19:30",
        suggested_date="2026-06-11",
        suggested_start_time="19:30",
        suggested_end_time="21:30",
        metadata={"team": "Colo-Colo"},
    )


def _response(status_code: int, body: dict | None = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = body if body is not None else {}
    response.text = str(body if body is not None else "")
    return response


class TestRadioflowPublisher:
    def test_posts_camel_case_payload_with_bearer_token(self):
        publisher = RadioflowPublisher("http://radioflow.local/", "rf_ext_token")
        response = _response(201, {"ok": True, "status": "created", "suggestionId": "sug-1"})

        with patch("requests.post", return_value=response) as mock_post:
            result = publisher.publish_suggestion(_suggestion())

        assert result.ok is True
        mock_post.assert_called_once()
        url = mock_post.call_args.args[0]
        kwargs = mock_post.call_args.kwargs
        assert url == "http://radioflow.local/api/external-suggestions"
        assert kwargs["headers"]["Authorization"] == "Bearer rf_ext_token"
        assert kwargs["headers"]["Content-Type"] == "application/json"
        assert kwargs["json"]["sourceKey"] == "sports-test"
        assert kwargs["json"]["externalContentId"] == "sports-match-123"
        assert "source_key" not in kwargs["json"]
        assert "external_content_id" not in kwargs["json"]

    def test_201_is_created(self):
        publisher = RadioflowPublisher("http://radioflow.local", "rf_ext_token")

        with patch("requests.post", return_value=_response(201, {"status": "created", "suggestionId": "sug-1"})):
            result = publisher.publish_suggestion(_suggestion())

        assert result.ok is True
        assert result.status == "created"
        assert result.http_status == 201
        assert result.suggestion_id == "sug-1"

    def test_200_deduplicated_is_deduplicated(self):
        publisher = RadioflowPublisher("http://radioflow.local", "rf_ext_token")

        with patch("requests.post", return_value=_response(200, {"status": "deduplicated", "suggestionId": "sug-1"})):
            result = publisher.publish_suggestion(_suggestion())

        assert result.ok is True
        assert result.status == "deduplicated"
        assert result.http_status == 200
        assert result.suggestion_id == "sug-1"

    def test_401_is_friendly_auth_error(self):
        publisher = RadioflowPublisher("http://radioflow.local", "rf_ext_token")

        with patch("requests.post", return_value=_response(401, {"code": "invalid_token", "message": "Invalid external source token."})):
            result = publisher.publish_suggestion(_suggestion())

        assert result.ok is False
        assert result.status == "failed"
        assert result.http_status == 401
        assert result.code == "invalid_token"
        assert "Invalid external source token" in result.message

    def test_403_is_friendly_permission_error(self):
        publisher = RadioflowPublisher("http://radioflow.local", "rf_ext_token")

        with patch("requests.post", return_value=_response(403, {"code": "missing_capability", "message": "Missing capability."})):
            result = publisher.publish_suggestion(_suggestion())

        assert result.ok is False
        assert result.status == "failed"
        assert result.http_status == 403
        assert result.code == "missing_capability"
        assert "Missing capability" in result.message

    def test_400_is_friendly_payload_error(self):
        publisher = RadioflowPublisher("http://radioflow.local", "rf_ext_token")

        with patch("requests.post", return_value=_response(400, {"code": "invalid_payload", "message": "External payload failed validation."})):
            result = publisher.publish_suggestion(_suggestion())

        assert result.ok is False
        assert result.status == "failed"
        assert result.http_status == 400
        assert result.code == "invalid_payload"
        assert "payload" in result.message.lower()

    def test_5xx_is_friendly_server_error(self):
        publisher = RadioflowPublisher("http://radioflow.local", "rf_ext_token")

        with patch("requests.post", return_value=_response(500, {"message": "Internal error"})):
            result = publisher.publish_suggestion(_suggestion())

        assert result.ok is False
        assert result.status == "failed"
        assert result.http_status == 500
        assert result.code == "radioflow_server_error"
        assert "RadioFlow server error" in result.message

    def test_invalid_json_error_response_is_friendly(self):
        publisher = RadioflowPublisher("http://radioflow.local", "rf_ext_token")
        response = _response(502)
        response.json.side_effect = ValueError("not json")
        response.text = "Bad gateway"

        with patch("requests.post", return_value=response):
            result = publisher.publish_suggestion(_suggestion())

        assert result.ok is False
        assert result.status == "failed"
        assert result.http_status == 502
        assert result.code == "radioflow_server_error"
        assert "RadioFlow server error" in result.message

    def test_connection_errors_are_friendly(self):
        publisher = RadioflowPublisher("http://radioflow.local", "rf_ext_token")

        with patch("requests.post", side_effect=requests.ConnectionError("no route")):
            result = publisher.publish_suggestion(_suggestion())

        assert result.ok is False
        assert result.status == "failed"
        assert result.http_status is None
        assert result.code == "connection_error"
        assert "Could not connect" in result.message

    def test_timeouts_are_friendly(self):
        publisher = RadioflowPublisher("http://radioflow.local", "rf_ext_token")

        with patch("requests.post", side_effect=requests.Timeout("slow")):
            result = publisher.publish_suggestion(_suggestion())

        assert result.ok is False
        assert result.status == "failed"
        assert result.http_status is None
        assert result.code == "timeout"
        assert "timed out" in result.message
