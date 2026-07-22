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
    assert "project://registry/query/manifests" in routes
    assert "project://domain/query/health" in routes
    assert "llm://remediation/command/propose-order" in routes
    assert "policy://remediation/command/validate-plan" in routes
    assert "problem://events/query/by-fingerprint" in routes
    assert "problem://reaction/command/record-occurrence" in routes
    assert "problem://reaction/query/classification" in routes
    assert "audit://problem/command/append-classification" in routes
    assert "analytics://host/event/command/ingest" in routes
    assert "analytics://host/overview/query" in routes
    assert "analytics://host/session/query/story" in routes
    assert "analytics://host/funnel/query" in routes
    assert "analytics://host/correlations/query" in routes
    assert "analytics://host/communication-score/query" in routes
    assert "analytics://host/recommendations/query" in routes
    assert "analytics://host/alerts/query" in routes


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


def test_project_inventory_adapters_use_bounded_reconciliation_queries(monkeypatch):
    calls = []
    monkeypatch.setenv("SUBACTOR_CONTROL_URL", "http://hr-control:8181")
    monkeypatch.setenv("SUBACTOR_CONTROL_TOKEN", "project-read-token")
    monkeypatch.setattr(core, "urlopen", lambda request, timeout: calls.append(request) or Response({"ok": True, "projects": []}))

    assert core.project_registry_manifests()["ok"]
    assert core.project_registry_manifests("demo-project", "demo.example.com", "corr-1")["ok"]
    assert core.project_domain_health("demo-project", "demo.example.com", strict_tls=True)["ok"]

    assert [request.full_url for request in calls] == [
        "http://hr-control:8181/api/projects/reconciliation",
        "http://hr-control:8181/api/projects/reconciliation?project_id=demo-project&domain=demo.example.com",
        "http://hr-control:8181/api/projects/reconciliation?project_id=demo-project&domain=demo.example.com",
    ]
    assert all(request.headers["Authorization"] == "Bearer project-read-token" for request in calls)


def test_project_inventory_adapters_reject_unbounded_inputs():
    assert core.project_registry_manifests("../escape")["ok"] is False
    assert core.project_domain_health()["ok"] is False
    assert core.project_domain_health(domain="localhost")["ok"] is False
    assert core.project_domain_health(domain="demo.example.com", strict_tls=False)["ok"] is False


def test_problem_observer_adapters_use_bounded_control_endpoints(monkeypatch):
    calls = []
    fingerprint = "a" * 64
    correlation_id = "12345678-1234-1234-1234-123456789abc"
    monkeypatch.setenv("SUBACTOR_CONTROL_URL", "http://hr-control:8181")
    monkeypatch.setenv("SUBACTOR_CONTROL_TOKEN", "problem-observer-token")
    monkeypatch.setattr(core, "urlopen", lambda request, timeout: calls.append(request) or Response({"ok": True}))

    assert core.problem_by_fingerprint(fingerprint, correlation_id)["ok"]
    assert core.record_problem_occurrence(fingerprint, correlation_id, 0)["ok"]
    assert core.problem_reaction_classification(fingerprint, correlation_id, False)["ok"]
    assert core.append_problem_classification(fingerprint, correlation_id, False)["ok"]

    assert [request.full_url for request in calls] == [
        f"http://hr-control:8181/api/problems/events/by-fingerprint?fingerprint={fingerprint}&correlation_id={correlation_id}",
        "http://hr-control:8181/api/problems/reactions/occurrences",
        f"http://hr-control:8181/api/problems/reactions/classification?fingerprint={fingerprint}&correlation_id={correlation_id}",
        "http://hr-control:8181/api/problems/reactions/audit-classification",
    ]
    assert all(request.headers["Authorization"] == "Bearer problem-observer-token" for request in calls)
    assert "problem-observer-token" not in json.dumps([core.problem_by_fingerprint(fingerprint)])


def test_problem_observer_adapters_reject_unbounded_actor_inputs():
    fingerprint = "a" * 64
    correlation_id = "12345678-1234-1234-1234-123456789abc"
    assert core.problem_by_fingerprint("../state")["ok"] is False
    assert core.record_problem_occurrence(fingerprint, correlation_id, 1)["ok"] is False
    assert core.problem_reaction_classification(fingerprint, correlation_id, True)["ok"] is False
    assert core.append_problem_classification(fingerprint, correlation_id, True)["ok"] is False


def test_analytics_adapters_use_only_configured_service(monkeypatch):
    calls = []
    monkeypatch.setenv("SUBACTOR_ANALYTICS_URL", "http://analytics:8089")
    monkeypatch.setenv("SUBACTOR_ANALYTICS_TOKEN", "analytics-token")
    monkeypatch.setattr(core, "urlopen", lambda request, timeout: calls.append(request) or Response({"ok": True}))

    assert core.ingest_analytics_event(
        "page.view", "site-generator", correlation_id="corr-1", event_id="evt-1",
        tenant_id="tenant-1", session_id="session-1", data={"path": "/"},
    )["ok"]
    assert core.analytics_overview("tenant-1")["ok"]
    assert core.analytics_session_story("session-1")["ok"]
    assert core.analytics_correlations()["ok"]

    assert [request.full_url for request in calls] == [
        "http://analytics:8089/api/events",
        "http://analytics:8089/api/overview?tenant_id=tenant-1",
        "http://analytics:8089/api/sessions/session-1",
        "http://analytics:8089/api/correlations",
    ]
    assert all(request.headers["Authorization"] == "Bearer analytics-token" for request in calls)
    assert "analytics-token" not in json.dumps([core.analytics_overview()])


def test_analytics_adapters_reject_unbounded_or_sensitive_inputs():
    assert core.ingest_analytics_event("INVALID TYPE", "site-generator")["ok"] is False
    assert core.ingest_analytics_event("page.view", "site-generator", data={"api_key": "secret"})["ok"] is False
    assert core.analytics_overview("../tenant")["ok"] is False
    assert core.analytics_session_story("../session")["ok"] is False
    with pytest.raises(TypeError):
        core.analytics_overview(url="http://caller", token="secret")
