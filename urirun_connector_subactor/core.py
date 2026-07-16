"""Server-side URI adapters for Subactor-owned business processes.

External products retain dedicated connectors.  This package owns the URI
schemes implemented by Subactor services themselves and forwards them only to
deployment-controlled base URLs; callers cannot supply a host or a secret.
"""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import urirun

CONNECTOR_ID = "subactor"
SCHEMES = (
    "analytics", "contractor", "docs", "mail", "org", "organization",
    "project", "site-generator", "social", "support", "test", "testql", "webpage",
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


for _scheme in SCHEMES:
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
        "markdown": markdown,
        "audience": audience,
    }
    return _call(
        "site-generator", "/api/generate.php", payload,
        base_env="SITE_GENERATOR_URL", token_env="SITE_GENERATOR_SERVICE_TOKEN",
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
