"""Keep the published Readiness documentation aligned with the API contract."""

from pathlib import Path

from app.api.main import create_app


def test_readiness_openapi_and_documentation_discoverability():
    operation = create_app().openapi()["paths"]["/api/health/readiness-score"]["get"]
    assert [parameter["name"] for parameter in operation["parameters"]] == ["period"]
    assert operation["security"] == [{"HTTPBearer": []}]
    assert {"200", "422"} <= set(operation["responses"])
    assert operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/ReadinessScoreResponse"
    )

    docs = Path("docs/HEALTH_API.md").read_text(encoding="utf-8")
    readme = Path("README.md").read_text(encoding="utf-8")
    for required in (
        "/api/health/readiness-score", "readiness-emulator-v0.3",
        "observed_google_health", "calculated_v0.3", "Sleep Score is not an input",
    ):
        assert required in docs
    assert "Readiness Score" in readme
