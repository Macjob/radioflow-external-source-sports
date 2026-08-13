import json
from datetime import datetime, timezone
from pathlib import Path

from app.chile_sports.sources import AnfpAnnouncementSource

FIXTURES = Path(__file__).parent / "fixtures"


class Response:
    status_code = 200
    headers = {"x-wp-totalpages": "1"}

    def json(self):
        return json.loads((FIXTURES / "anfp_reprogramming_posts.json").read_text(encoding="utf-8"))


class Session:
    def __init__(self):
        self.kwargs = None

    def get(self, url, **kwargs):
        self.kwargs = kwargs
        return Response()


def test_anfp_rest_source_detects_reprogramming_without_complex_nlp():
    session = Session()
    source = AnfpAnnouncementSource(
        "https://www.anfp.cl/wp-json/wp/v2/posts",
        session=session,
    )

    rows = source.fetch(datetime(2026, 5, 1, tzinfo=timezone.utc))

    assert len(rows) == 1
    assert rows[0].external_id == "15132"
    assert rows[0].change_type == "reprogrammed"
    assert "Everton" in rows[0].content
    assert session.kwargs["params"]["modified_after"] == "2026-05-01T00:00:00Z"
