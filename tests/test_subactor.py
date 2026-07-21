import json

import pytest

from urirun_connector_subactor import core


class Response:
    status = 200
    def __init__(self, payload): self.payload = payload
    def __enter__(self): return self
    def __exit__(self, *_): return None
    def read(self, _limit): return json.dumps(self.payload).encode()


def test_all_owned_schemes_have_dispatch_and_doctor_routes():
    routes = core.bindings()["bindings"]
    for scheme in core.GATEWAY_SCHEMES:
        assert f"{scheme}://host/process/command/dispatch" in routes
        assert f"{scheme}://host/doctor/query/report" in routes
    assert "llm://host/doctor/query/report" not in routes
    assert "policy://host/doctor/query/report" not in routes


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
    assert "project://remediation/query/snapshot" in routes
    assert "project://remediation/query/catalog" in routes
    assert "llm://remediation/command/propose-order" in routes
    assert "policy://remediation/command/validate-plan" in routes


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


def test_planner_adapters_use_only_configured_control_target(monkeypatch, tmp_path):
    calls = []
    token_file = tmp_path / "control-token"
    token_file.write_text("scoped-control-token\n")
    monkeypatch.setenv("SUBACTOR_CONTROL_URL", "http://hr-control:8181")
    monkeypatch.delenv("SUBACTOR_CONTROL_TOKEN", raising=False)
    monkeypatch.setenv("SUBACTOR_CONTROL_TOKEN_FILE", str(token_file))
    monkeypatch.setattr(core, "urlopen", lambda request, timeout: calls.append((request, timeout)) or Response({"ok": True}))

    assert core.remediation_snapshot("project-1", "correlation-1")["ok"]
    assert core.remediation_catalog("project-1")["ok"]
    assert core.propose_remediation_order("project-1", True)["ok"]
    assert core.validate_remediation_plan("project-1", {"ordered_modules": []}, True, "deterministic")["ok"]

    assert [request.full_url for request, _ in calls] == [
        "http://hr-control:8181/api/projects/remediation/snapshot?project_id=project-1",
        "http://hr-control:8181/api/projects/remediation/catalog?project_id=project-1",
        "http://hr-control:8181/api/projects/remediation/propose-order",
        "http://hr-control:8181/api/projects/remediation/validate-plan",
    ]
    assert all(request.headers["Authorization"] == "Bearer scoped-control-token" for request, _ in calls)


def test_planner_adapters_fail_closed_on_actor_controlled_policy(monkeypatch):
    monkeypatch.setenv("SUBACTOR_CONTROL_URL", "http://hr-control:8181")
    assert core.remediation_snapshot("../secret")["ok"] is False
    assert core.propose_remediation_order("project-1", False)["ok"] is False
    assert core.validate_remediation_plan("project-1", {}, False, "accept-anything")["ok"] is False
    with pytest.raises(TypeError):
        core.propose_remediation_order("project-1", model="caller-model", prompt="arbitrary")
    with pytest.raises(TypeError):
        core.remediation_snapshot("project-1", url="http://caller", token="secret")
