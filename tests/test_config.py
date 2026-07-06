import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from app.config import load_config


def test_load_config_success(temp_config_file: str):
    config = load_config()
    assert config.timezone == "America/Santiago"
    assert "Colo-Colo" in config.teams
    assert config.radios["Colo-Colo"].label == "Cooperativa 93.3 FM"
    assert config.radios["Colo-Colo"].streamUrl == "https://stream.example.com/cooperativa.aac"
    assert "Colo-Colo" in config.team_mapping


def test_load_config_file_not_found():
    with patch.object(Path, "exists", return_value=False):
        with pytest.raises(FileNotFoundError):
            load_config()


def test_load_config_invalid_json():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "config.json"
        path.write_text("not valid json", encoding="utf-8")
        with patch("app.config.find_config_file", return_value=path):
            with pytest.raises(json.JSONDecodeError):
                load_config()
