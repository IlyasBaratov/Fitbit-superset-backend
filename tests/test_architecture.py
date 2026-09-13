"""Layer boundaries and import-time safety for the extracted application."""
import ast
import importlib
from pathlib import Path
from unittest.mock import patch


def test_all_application_modules_import_without_runtime_side_effects():
    with patch("requests.sessions.Session.request", side_effect=AssertionError("network during import")), patch("app.providers.auth.FileTokenManager.refresh", side_effect=AssertionError("OAuth during import")), patch("builtins.input", side_effect=AssertionError("stdin")), patch("logging.basicConfig", side_effect=AssertionError("logging during import")):
        for path in Path("app").rglob("*.py"):
            if path.name != "__init__.py":
                importlib.import_module(".".join(path.with_suffix("").parts))


def test_pure_mappers_have_no_infrastructure_imports():
    for provider in ("fitbit", "google_health", "google_calendar"):
        for filename in ("mapper.py", "vitals.py", "activity.py", "sleep.py"):
            path = Path("app/providers") / provider / filename
            if not path.exists():
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            modules = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
            assert all(not module.startswith(("app.storage", "app.ingestion")) and not module.endswith("client") for module in modules)
            imports = [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
            assert "requests" not in imports


def test_no_mutable_worker_globals_or_interactive_input():
    for directory in ("app/providers", "app/ingestion", "app/worker"):
        for path in Path(directory).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            assert not any(isinstance(node, ast.Global) for node in ast.walk(tree))
            assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "input" for node in ast.walk(tree))
