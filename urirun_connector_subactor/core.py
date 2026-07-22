"""Server-side URI adapters for Subactor-owned business processes.

External products retain dedicated connectors.  This package owns the URI
schemes implemented by Subactor services themselves and forwards them only to
deployment-controlled base URLs; callers cannot supply a host or a secret.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

import urirun

CONNECTOR_ID = "subactor"
SCHEMES = (
    "analytics", "audit", "contractor", "docs", "mail", "org", "organization",
    "llm", "policy", "problem", "project", "recruitment", "site-generator", "social", "support", "test", "testql", "webpage",
)
connectors = {scheme: urirun.connector(f"subactor-{scheme}", scheme=scheme) for scheme in SCHEMES}
# Compatibility export expected by generated connector tooling.
conn = connectors["site-generator"]


def _env_prefix(scheme: str) -> str:
    return scheme.upper().replace("-", "_")


def _call(
    scheme: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    method: str = "POST",
    base_env: str | None = None,
    token_env: str | None = None,
    timeout_seconds: float = 15.0,
) -> dict[str, Any]:
    prefix = _env_prefix(scheme)
    base_name = base_env or f"SUBACTOR_{prefix}_URL"
    token_name = token_env or f"SUBACTOR_{prefix}_TOKEN"
    base = os.environ.get(base_name, "").strip().rstrip("/")
    if not base:
        return urirun.fail(f"{base_name} is not configured", connector=CONNECTOR_ID, scheme=scheme)
    clean_path = "/" + str(path or "").lstrip("/")
    if ".." in clean_path.split("/"):
        return urirun.fail("relative path segments are not allowed", connector=CONNECTOR_ID, scheme=scheme)
    token = os.environ.get(token_name, "").strip()
    token_file = os.environ.get(f"{token_name}_FILE", "").strip()
    if not token and token_file:
        try:
            with open(token_file, "r", encoding="utf-8") as stream:
                token = stream.read(8192).strip()
        except (OSError, ValueError):
            return urirun.fail(f"{token_name}_FILE is unavailable", connector=CONNECTOR_ID, scheme=scheme)
    headers = {"accept": "application/json", "user-agent": "urirun-connector-subactor/0.1"}
    data = None
    if method != "GET":
        headers["content-type"] = "application/json"
        data = json.dumps(payload or {}).encode("utf-8")
    if token:
        headers["authorization"] = f"Bearer {token}"
    request = Request(base + clean_path, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=max(0.1, min(float(timeout_seconds), 60.0))) as response:
            raw = response.read(8 * 1024 * 1024).decode("utf-8", errors="replace")
            try:
                result: Any = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                result = {"text": raw}
            return urirun.ok(connector=CONNECTOR_ID, scheme=scheme, status=response.status, result=result)
    except HTTPError as exc:
        return urirun.fail("Subactor service rejected the request", connector=CONNECTOR_ID, scheme=scheme, status=exc.code)
    except (URLError, TimeoutError, ValueError) as exc:
        return urirun.fail("Subactor service is unavailable", connector=CONNECTOR_ID, scheme=scheme, error_type=type(exc).__name__)


def _register_gateway(scheme: str) -> None:
    def dispatch(path: str = "/", payload: dict[str, Any] | None = None, timeout_seconds: float = 15.0) -> dict[str, Any]:
        return _call(scheme, path, payload, timeout_seconds=timeout_seconds)

    dispatch.__name__ = f"dispatch_{scheme.replace('-', '_')}"
    dispatch.__qualname__ = dispatch.__name__
    globals()[dispatch.__name__] = dispatch
    connectors[scheme].handler(
        "process/command/dispatch",
        isolated=True,
        external=True,
        meta={"label": f"Dispatch {scheme} process to its configured Subactor service"},
    )(dispatch)

    def doctor() -> dict[str, Any]:
        env_name = f"SUBACTOR_{_env_prefix(scheme)}_URL"
        return urirun.ok(connector=CONNECTOR_ID, scheme=scheme, configured=bool(os.environ.get(env_name)), status="ready")

    doctor.__name__ = f"doctor_{scheme.replace('-', '_')}"
    doctor.__qualname__ = doctor.__name__
    globals()[doctor.__name__] = doctor
    connectors[scheme].handler("doctor/query/report", isolated=True, meta={"label": f"{scheme} readiness"})(doctor)


GATEWAY_SCHEMES = tuple(scheme for scheme in SCHEMES if scheme not in {"llm", "policy"})


for _scheme in GATEWAY_SCHEMES:
    _register_gateway(_scheme)


@connectors["site-generator"].handler(
    "site-generator://host/site/command/generate",
    isolated=True,
    external=True,
    meta={"label": "Generate a static Subactor website"},
)
def generate_site(
    domain: str,
    project_name: str,
    headline: str = "",
    description: str = "",
    contact_email: str = "",
    markdown: str = "",
    audience: str = "business",
) -> dict[str, Any]:
    payload = {
        "domain": domain,
        "project_name": project_name,
        "headline": headline or project_name,
        "description": description,
        "contact_email": contact_email,
        "markdown": markdown or f"## O projekcie\n\n{description or project_name}",
        "audience": audience,
    }
    return _call(
        "site-generator", "/api/generate.php", payload,
        base_env="SITE_GENERATOR_URL", token_env="SITE_GENERATOR_SERVICE_TOKEN",
    )


@connectors["organization"].handler(
    "organization://org-demo/status/query",
    isolated=True,
    external=True,
    meta={"label": "Read the default Subactor organization dashboard"},
)
@connectors["organization"].handler(
    "status/query",
    isolated=True,
    external=True,
    meta={"label": "Read the Subactor organization dashboard"},
)
def organization_status(organization_id: str = "org-demo") -> dict[str, Any]:
    path = "/api/dashboard?" + urlencode({"organization_id": organization_id})
    return _call(
        "organization", path, method="GET",
        base_env="ORG_CORE_INTERNAL_URL", token_env="ORG_CORE_SERVICE_TOKEN",
    )


_ANALYTICS_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$")
_ANALYTICS_EVENT_TYPE = re.compile(r"^[a-z][a-z0-9_.-]{1,127}$")
_SENSITIVE_ANALYTICS_KEY = re.compile(r"password|secret|token|authorization|api[_-]?key|credential", re.IGNORECASE)


def _analytics_reference(value: str, field: str, *, required: bool = False) -> str:
    normalized = str(value or "").strip()
    if not normalized and not required:
        return ""
    if not _ANALYTICS_REFERENCE.fullmatch(normalized):
        raise ValueError(f"analytics_{field}_invalid")
    return normalized


def _contains_sensitive_analytics_key(value: Any) -> bool:
    if isinstance(value, list):
        return any(_contains_sensitive_analytics_key(item) for item in value)
    if not isinstance(value, dict):
        return False
    return any(
        _SENSITIVE_ANALYTICS_KEY.search(str(key)) or _contains_sensitive_analytics_key(item)
        for key, item in value.items()
    )


def _analytics_call(path: str, payload: dict[str, Any] | None = None, *, method: str = "GET") -> dict[str, Any]:
    return _call(
        "analytics",
        path,
        payload,
        method=method,
        base_env="SUBACTOR_ANALYTICS_URL",
        token_env="SUBACTOR_ANALYTICS_TOKEN",
    )


def _analytics_query(path: str, tenant_id: str = "") -> dict[str, Any]:
    try:
        tenant = _analytics_reference(tenant_id, "tenant_id")
    except ValueError as exc:
        return urirun.fail(str(exc), connector=CONNECTOR_ID, scheme="analytics")
    query = f"?{urlencode({'tenant_id': tenant})}" if tenant else ""
    return _analytics_call(f"{path}{query}")


@connectors["analytics"].handler(
    "event/command/ingest",
    isolated=True,
    external=True,
    meta={"label": "Append one canonical Subactor analytics event"},
)
def ingest_analytics_event(
    event_type: str,
    source: str,
    correlation_id: str = "",
    event_id: str = "",
    occurred_at: str = "",
    tenant_id: str = "",
    session_id: str = "",
    domain: str = "",
    variant_key: str = "",
    receiver_state: str = "",
    request_intent: str = "",
    requester_actor: str = "",
    environment: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        normalized_type = str(event_type or "").strip()
        if not _ANALYTICS_EVENT_TYPE.fullmatch(normalized_type):
            raise ValueError("analytics_event_type_invalid")
        normalized_source = _analytics_reference(source, "source", required=True)
        references = {
            "correlation_id": _analytics_reference(correlation_id, "correlation_id"),
            "event_id": _analytics_reference(event_id, "event_id"),
            "tenant_id": _analytics_reference(tenant_id, "tenant_id"),
            "session_id": _analytics_reference(session_id, "session_id"),
            "variant_key": _analytics_reference(variant_key, "variant_key"),
            "receiver_state": _analytics_reference(receiver_state, "receiver_state"),
            "request_intent": _analytics_reference(request_intent, "request_intent"),
            "requester_actor": _analytics_reference(requester_actor, "requester_actor"),
        }
        if len(str(domain or "")) > 253 or len(str(occurred_at or "")) > 64:
            raise ValueError("analytics_event_field_too_long")
        objects = {
            "environment": environment if isinstance(environment, dict) else {},
            "context": context if isinstance(context, dict) else {},
            "data": data if isinstance(data, dict) else {},
        }
        if any(_contains_sensitive_analytics_key(value) for value in objects.values()):
            raise ValueError("analytics_event_sensitive_field")
    except ValueError as exc:
        return urirun.fail(str(exc), connector=CONNECTOR_ID, scheme="analytics")
    payload = {
        "type": normalized_type,
        "source": normalized_source,
        "occurred_at": str(occurred_at or "").strip(),
        "domain": str(domain or "").strip(),
        **references,
        **objects,
    }
    return _analytics_call("/api/events", payload, method="POST")


@connectors["analytics"].handler("overview/query", isolated=True, external=True, meta={"label": "Read analytics overview"})
def analytics_overview(tenant_id: str = "") -> dict[str, Any]:
    return _analytics_query("/api/overview", tenant_id)


@connectors["analytics"].handler("sessions/query", isolated=True, external=True, meta={"label": "Read live analytics sessions"})
def analytics_sessions(tenant_id: str = "") -> dict[str, Any]:
    return _analytics_query("/api/sessions", tenant_id)


@connectors["analytics"].handler("session/query/story", isolated=True, external=True, meta={"label": "Read one analytics session story"})
def analytics_session_story(session_id: str) -> dict[str, Any]:
    try:
        session = _analytics_reference(session_id, "session_id", required=True)
    except ValueError as exc:
        return urirun.fail(str(exc), connector=CONNECTOR_ID, scheme="analytics")
    return _analytics_call(f"/api/sessions/{quote(session, safe='')}")


@connectors["analytics"].handler("funnel/query", isolated=True, external=True, meta={"label": "Read analytics funnel projection"})
def analytics_funnel(tenant_id: str = "") -> dict[str, Any]:
    return _analytics_query("/api/funnel", tenant_id)


@connectors["analytics"].handler("health/query", isolated=True, external=True, meta={"label": "Read tenant analytics health"})
def analytics_health(tenant_id: str = "") -> dict[str, Any]:
    return _analytics_query("/api/health", tenant_id)


@connectors["analytics"].handler("timeline/query", isolated=True, external=True, meta={"label": "Read analytics timeline"})
def analytics_timeline(tenant_id: str = "") -> dict[str, Any]:
    return _analytics_query("/api/timeline", tenant_id)


@connectors["analytics"].handler("correlations/query", isolated=True, external=True, meta={"label": "Read analytics correlations"})
def analytics_correlations(tenant_id: str = "") -> dict[str, Any]:
    return _analytics_query("/api/correlations", tenant_id)


@connectors["analytics"].handler("communication-score/query", isolated=True, external=True, meta={"label": "Read communication score"})
def analytics_communication_score(tenant_id: str = "") -> dict[str, Any]:
    return _analytics_query("/api/score", tenant_id)


@connectors["analytics"].handler("recommendations/query", isolated=True, external=True, meta={"label": "Read evidence-based recommendations"})
def analytics_recommendations(tenant_id: str = "") -> dict[str, Any]:
    return _analytics_query("/api/recommendations", tenant_id)


@connectors["analytics"].handler("alerts/query", isolated=True, external=True, meta={"label": "Read analytics alerts"})
def analytics_alerts(tenant_id: str = "") -> dict[str, Any]:
    return _analytics_query("/api/alerts", tenant_id)


@connectors["recruitment"].handler(
    "job-offer/command/draft",
    isolated=True,
    external=True,
    meta={"label": "Generate a validated recruitment job-offer draft"},
)
def draft_job_offer(
    instruction: str,
    current_values: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate a job-offer draft through the deployment-controlled LLM gateway.

    The caller supplies only a bounded instruction, current form values and an
    explicitly approved context object.  Provider credentials stay in the LLM
    gateway; this connector never accepts a URL, token or arbitrary HTML.
    """
    clean_instruction = str(instruction or "").strip()
    if len(clean_instruction) < 10 or len(clean_instruction) > 6000:
        return urirun.fail("instruction must contain 10..6000 characters", connector=CONNECTOR_ID, scheme="recruitment")
    return _call(
        "recruitment",
        "/forms/recruitment/job-offer/draft",
        {
            "instruction": clean_instruction,
            "current_values": current_values if isinstance(current_values, dict) else {},
            "context": context if isinstance(context, dict) else {},
        },
        base_env="LLM_GATEWAY_INTERNAL_URL",
        token_env="LLM_GATEWAY_SERVICE_TOKEN",
        timeout_seconds=60.0,
    )


def _planner_project_id(project_id: str) -> str:
    normalized = str(project_id or "").strip()
    if not normalized or len(normalized) > 64 or not normalized.replace("-", "a").isalnum():
        raise ValueError("invalid_project_id")
    return normalized


def _control_call(scheme: str, path: str, payload: dict[str, Any] | None = None, *, method: str = "POST") -> dict[str, Any]:
    return _call(
        scheme,
        path,
        payload,
        method=method,
        base_env="SUBACTOR_CONTROL_URL",
        token_env="SUBACTOR_CONTROL_TOKEN",
        timeout_seconds=60.0,
    )


def _problem_reference(fingerprint: str, correlation_id: str = "") -> tuple[str, str]:
    clean_fingerprint = str(fingerprint or "").strip()
    clean_correlation = str(correlation_id or "").strip()
    if not re.fullmatch(r"[a-f0-9]{64}", clean_fingerprint):
        raise ValueError("invalid_problem_fingerprint")
    if clean_correlation and not re.fullmatch(r"[a-f0-9-]{36}", clean_correlation):
        raise ValueError("invalid_problem_correlation_id")
    return clean_fingerprint, clean_correlation


@connectors["problem"].handler(
    "problem://events/query/by-fingerprint",
    isolated=True,
    external=True,
    meta={"label": "Read one safe problem profile by fingerprint"},
)
def problem_by_fingerprint(fingerprint: str, correlation_id: str = "") -> dict[str, Any]:
    try:
        fingerprint, correlation_id = _problem_reference(fingerprint, correlation_id)
    except ValueError as exc:
        return urirun.fail(str(exc), connector=CONNECTOR_ID, scheme="problem")
    query = {"fingerprint": fingerprint}
    if correlation_id:
        query["correlation_id"] = correlation_id
    return _control_call("problem", "/api/problems/events/by-fingerprint?" + urlencode(query), method="GET")


@connectors["problem"].handler(
    "problem://reaction/command/record-occurrence",
    isolated=True,
    external=True,
    meta={"label": "Record an idempotent observation of an existing problem occurrence"},
)
def record_problem_occurrence(fingerprint: str, correlation_id: str, external_mutations: int = 0) -> dict[str, Any]:
    try:
        fingerprint, correlation_id = _problem_reference(fingerprint, correlation_id)
        if not correlation_id:
            raise ValueError("problem_correlation_id_required")
        if external_mutations != 0:
            raise ValueError("external_mutations_must_equal_zero")
    except ValueError as exc:
        return urirun.fail(str(exc), connector=CONNECTOR_ID, scheme="problem")
    return _control_call("problem", "/api/problems/reactions/occurrences", {
        "fingerprint": fingerprint,
        "correlation_id": correlation_id,
        "external_mutations": 0,
    })


@connectors["problem"].handler(
    "problem://reaction/query/classification",
    isolated=True,
    external=True,
    meta={"label": "Read the deterministic non-mutating reaction classification"},
)
def problem_reaction_classification(
    fingerprint: str,
    correlation_id: str = "",
    automatic_mutation_allowed: bool = False,
) -> dict[str, Any]:
    try:
        fingerprint, correlation_id = _problem_reference(fingerprint, correlation_id)
        if automatic_mutation_allowed is not False:
            raise ValueError("automatic_mutation_must_equal_false")
    except ValueError as exc:
        return urirun.fail(str(exc), connector=CONNECTOR_ID, scheme="problem")
    query = {"fingerprint": fingerprint}
    if correlation_id:
        query["correlation_id"] = correlation_id
    return _control_call("problem", "/api/problems/reactions/classification?" + urlencode(query), method="GET")


@connectors["audit"].handler(
    "audit://problem/command/append-classification",
    isolated=True,
    external=True,
    meta={"label": "Append a non-replayable canonical problem classification audit event"},
)
def append_problem_classification(fingerprint: str, correlation_id: str, replayable: bool = False) -> dict[str, Any]:
    try:
        fingerprint, correlation_id = _problem_reference(fingerprint, correlation_id)
        if not correlation_id:
            raise ValueError("problem_correlation_id_required")
        if replayable is not False:
            raise ValueError("problem_classification_must_not_be_replayable")
    except ValueError as exc:
        return urirun.fail(str(exc), connector=CONNECTOR_ID, scheme="audit")
    return _control_call("audit", "/api/problems/reactions/audit-classification", {
        "fingerprint": fingerprint,
        "correlation_id": correlation_id,
        "replayable": False,
    })


@connectors["project"].handler(
    "project://remediation/query/snapshot",
    isolated=True,
    external=True,
    meta={"label": "Read one remediation project snapshot"},
)
def remediation_snapshot(project_id: str, correlation_id: str = "") -> dict[str, Any]:
    try:
        project = _planner_project_id(project_id)
    except ValueError as exc:
        return urirun.fail(str(exc), connector=CONNECTOR_ID, scheme="project")
    if correlation_id and (len(str(correlation_id)) > 80 or any(c.isspace() for c in str(correlation_id))):
        return urirun.fail("invalid_correlation_id", connector=CONNECTOR_ID, scheme="project")
    return _control_call("project", "/api/projects/remediation/snapshot?" + urlencode({"project_id": project}), method="GET")


@connectors["project"].handler(
    "project://remediation/query/catalog",
    isolated=True,
    external=True,
    meta={"label": "Read the active deterministic remediation catalog"},
)
def remediation_catalog(project_id: str) -> dict[str, Any]:
    try:
        project = _planner_project_id(project_id)
    except ValueError as exc:
        return urirun.fail(str(exc), connector=CONNECTOR_ID, scheme="project")
    return _control_call("project", "/api/projects/remediation/catalog?" + urlencode({"project_id": project}), method="GET")


def _project_selection(project_id: str = "", domain: str = "") -> dict[str, str]:
    selection: dict[str, str] = {}
    if str(project_id or "").strip():
        selection["project_id"] = _planner_project_id(project_id)
    clean_domain = str(domain or "").strip().lower()
    if clean_domain:
        if not re.fullmatch(r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", clean_domain):
            raise ValueError("invalid_project_domain")
        selection["domain"] = clean_domain
    return selection


@connectors["project"].handler(
    "project://registry/query/manifests",
    isolated=True,
    external=True,
    meta={"label": "Read the canonical project reconciliation manifest projection"},
)
def project_registry_manifests(project_id: str = "", domain: str = "", correlation_id: str = "") -> dict[str, Any]:
    try:
        selection = _project_selection(project_id, domain)
        if correlation_id and (len(str(correlation_id)) > 80 or any(c.isspace() for c in str(correlation_id))):
            raise ValueError("invalid_correlation_id")
    except ValueError as exc:
        return urirun.fail(str(exc), connector=CONNECTOR_ID, scheme="project")
    query = "?" + urlencode(selection) if selection else ""
    return _control_call("project", "/api/projects/reconciliation" + query, method="GET")


@connectors["project"].handler(
    "project://domain/query/health",
    isolated=True,
    external=True,
    meta={"label": "Read one project domain health projection"},
)
def project_domain_health(
    project_id: str = "",
    domain: str = "",
    correlation_id: str = "",
    strict_tls: bool = True,
) -> dict[str, Any]:
    try:
        selection = _project_selection(project_id, domain)
        if not selection:
            raise ValueError("project_selection_required")
        if strict_tls is not True:
            raise ValueError("strict_tls_must_equal_true")
        if correlation_id and (len(str(correlation_id)) > 80 or any(c.isspace() for c in str(correlation_id))):
            raise ValueError("invalid_correlation_id")
    except ValueError as exc:
        return urirun.fail(str(exc), connector=CONNECTOR_ID, scheme="project")
    return _control_call("project", "/api/projects/reconciliation?" + urlencode(selection), method="GET")


@connectors["llm"].handler(
    "llm://remediation/command/propose-order",
    isolated=True,
    external=True,
    meta={"label": "Request a bounded remediation ordering proposal"},
)
def propose_remediation_order(project_id: str, catalog_only: bool = True) -> dict[str, Any]:
    try:
        project = _planner_project_id(project_id)
        if catalog_only is not True:
            raise ValueError("catalog_only_must_equal_true")
    except ValueError as exc:
        return urirun.fail(str(exc), connector=CONNECTOR_ID, scheme="llm")
    return _control_call("llm", "/api/projects/remediation/propose-order", {"project_id": project, "catalog_only": True})


@connectors["policy"].handler(
    "policy://remediation/command/validate-plan",
    isolated=True,
    external=True,
    meta={"label": "Validate a proposal with the canonical control policy"},
)
def validate_remediation_plan(
    project_id: str,
    proposal: dict[str, Any] | None = None,
    reject_unknown_fields: bool = True,
    fallback: str = "deterministic",
) -> dict[str, Any]:
    try:
        project = _planner_project_id(project_id)
        if reject_unknown_fields is not True or fallback != "deterministic":
            raise ValueError("validation_policy_required")
        if proposal is not None and not isinstance(proposal, dict):
            raise ValueError("proposal_object_required")
    except ValueError as exc:
        return urirun.fail(str(exc), connector=CONNECTOR_ID, scheme="policy")
    return _control_call(
        "policy",
        "/api/projects/remediation/validate-plan",
        {"project_id": project, "proposal": proposal, "reject_unknown_fields": True, "fallback": "deterministic"},
    )


def bindings() -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for connector in connectors.values():
        merged.update(connector.bindings()["bindings"])
    return {"version": "urirun.bindings.v2", "bindings": merged}


def urirun_bindings() -> dict[str, Any]:
    return bindings()


def manifest() -> dict[str, Any]:
    document = urirun.load_manifest(__package__) or {"id": CONNECTOR_ID}
    document["uriSchemes"] = list(SCHEMES)
    document["routes"] = sorted(bindings()["bindings"])
    return document


def main(argv: list[str] | None = None) -> int:
    return conn.cli(argv, manifest_prose=urirun.load_manifest(__package__))


if __name__ == "__main__":
    raise SystemExit(main())
