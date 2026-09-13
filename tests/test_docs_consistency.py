"""Calendar env vars, routes and doc sections stay in step with the code (C5.2)."""
import re
from pathlib import Path

from app.api.main import create_app
from app.core.config import Settings

ENV_PATTERN = re.compile(
    r"os\.(?:getenv|environ\.get)\(\s*[\"'](CALENDAR_[A-Z0-9_]*)[\"']"
)
API_SETTINGS = Settings(api_token="t" * 40, gemini_key="test", model="test")
CALENDAR_SYNC_DOC = Path("docs/CALENDAR_SYNC.md")
REQUIRED_SECTIONS = (
    "Setup",
    "Sync policy",
    "Schema",
    "Endpoints",
    "Privacy",
    "Limits",
    "Troubleshooting",
    "Environment",
)


def calendar_env_names():
    names = set()
    for directory in ("app", "scripts"):
        for path in Path(directory).rglob("*.py"):
            names |= set(ENV_PATTERN.findall(path.read_text(encoding="utf-8")))
    return names


def test_every_calendar_env_var_is_documented_and_configured():
    names = calendar_env_names()
    assert names, "no calendar settings found in the code"
    for target in (
        Path(".env.example"),
        Path("compose.yml"),
        CALENDAR_SYNC_DOC,
    ):
        text = target.read_text(encoding="utf-8")
        assert not (names - set(re.findall(r"CALENDAR_[A-Z0-9_]*", text))), target


def test_env_example_declares_each_key_once():
    keys = [
        line.split("=", 1)[0].strip()
        for line in Path(".env.example").read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    ]
    assert sorted(keys) == sorted(set(keys)), "duplicate keys contradict each other"


def test_env_example_only_declares_settings_the_code_reads():
    declared = {
        key
        for key in (
            line.split("=", 1)[0].strip()
            for line in Path(".env.example").read_text(encoding="utf-8").splitlines()
            if "=" in line and not line.lstrip().startswith("#")
        )
        if "CALENDAR" in key
    }
    assert declared == calendar_env_names()


def test_calendar_routes_appear_in_the_docs():
    paths = {
        path
        for path in create_app(settings=API_SETTINGS, influx=object()).openapi()["paths"]
        if "calendar" in path
    }
    assert paths
    docs = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (CALENDAR_SYNC_DOC, Path("docs/HEALTH_API.md"), Path("docs/AI_BACKEND.md"))
    )
    for path in paths:
        assert path in docs, path


def test_calendar_doc_covers_every_required_section():
    headings = {
        line.lstrip("#").strip()
        for line in CALENDAR_SYNC_DOC.read_text(encoding="utf-8").splitlines()
        if line.startswith("#")
    }
    assert not [name for name in REQUIRED_SECTIONS if name not in headings]
