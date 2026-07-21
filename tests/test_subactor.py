import json

from urirun_connector_subactor import core


class Response:
    status = 200
    def __init__(self, payload): self.payload = payload
    def __enter__(self): return self
    def __exit__(self, *_): return None
    def read(self, _limit): return json.dumps(self.payload).encode()


def test_all_owned_schemes_have_dispatch_and_doctor_routes():
    routes = core.bindings()["bindings"]
    for scheme in core.SCHEMES:
        assert f"{scheme}://host/process/command/dispatch" in routes
        assert f"{scheme}://host/doctor/query/report" in routes


def test_site_generator_uses_only_configured_service(monkeypatch):
    calls = []
    monkeypatch.setenv("SITE_GENERATOR_URL", "http://site-generator")
    monkeypatch.setenv("SITE_GENERATOR_SERVICE_TOKEN", "safe-token")
    monkeypatch.setattr(core, "urlopen", lambda request, timeout: calls.append(request) or Response({"ok": True}))
    result = core.generate_site("example.test", "Example")
    assert result["ok"] and calls[0].full_url == "http://site-generator/api/generate.php"
    assert calls[0].headers["Authorization"] == "Bearer safe-token"
    assert "safe-token" not in json.dumps(result)


def test_generic_dispatch_rejects_unconfigured_target(monkeypatch):
    monkeypatch.delenv("SUBACTOR_SUPPORT_URL", raising=False)
    assert core.dispatch_support("/api/cases", {})["ok"] is False


def test_concrete_routes_are_registered():
    routes = core.bindings()["bindings"]
    assert "site-generator://host/site/command/generate" in routes
    assert "organization://host/status/query" in routes
    assert "organization://org-demo/status/query" in routes
    assert "recruitment://host/job-offer/command/draft" in routes


def test_recruitment_draft_uses_llm_gateway_without_caller_supplied_target(monkeypatch):
    calls = []
    monkeypatch.setenv("LLM_GATEWAY_INTERNAL_URL", "http://llm-gateway:8084")
    monkeypatch.setenv("LLM_GATEWAY_SERVICE_TOKEN", "gateway-token")
    monkeypatch.setattr(core, "urlopen", lambda request, timeout: calls.append((request, timeout)) or Response({"ok": True, "data": {"offer": {"status": "draft"}}}))

    result = core.draft_job_offer(
        "Utwórz ofertę dla inżyniera automatyzacji PHP.",
        {"work_mode": "remote"},
        {"organization": {"name": "Subactor"}},
    )

    assert result["ok"] is True
    request, timeout = calls[0]
    assert request.full_url == "http://llm-gateway:8084/forms/recruitment/job-offer/draft"
    assert request.headers["Authorization"] == "Bearer gateway-token"
    assert timeout == 60.0
    assert "gateway-token" not in json.dumps(result)


def test_recruitment_draft_rejects_unbounded_instruction(monkeypatch):
    assert core.draft_job_offer("za krótko")["ok"] is False
    assert core.draft_job_offer("x" * 6001)["ok"] is False
