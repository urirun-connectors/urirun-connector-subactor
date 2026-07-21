# urirun-connector-subactor

Server-side connector for URI processes implemented by Subactor services.

It provides concrete routes such as `site-generator://host/site/command/generate`,
`organization://host/status/query`, and
`recruitment://host/job-offer/command/draft`, plus a controlled
`<scheme>://host/process/command/dispatch` route for Subactor-owned schemes.
Every target base URL and credential comes from the node environment; an actor
cannot inject a target host or bearer token through the process payload.

Supported schemes: `analytics`, `audit`, `contractor`, `docs`, `llm`, `mail`, `org`,
`organization`, `policy`, `problem`, `project`, `recruitment`, `site-generator`, `social`,
`support`, `test`, `testql`, and `webpage`.

The remediation planner exposes four exact, bounded routes:

- `project://remediation/query/snapshot`
- `project://remediation/query/catalog`
- `llm://remediation/command/propose-order`
- `policy://remediation/command/validate-plan`

They forward only to the deployment-controlled control service and never accept
a host, token, model or free-form prompt from the caller. The policy route
contains no Python copy of the validation rules; the canonical validator remains
in Subactor core.

The problem-reaction observer exposes four observation-only routes:

- `problem://events/query/by-fingerprint`
- `problem://reaction/command/record-occurrence`
- `problem://reaction/query/classification`
- `audit://problem/command/append-classification`

They use the deployment-controlled Control URL and a token limited to
`problems:observe`. Repeating the same fingerprint/correlation pair is
idempotent; callers cannot enable infrastructure mutation or replay the audit
classification.

For `site-generator://host/site/command/generate`, configure `SITE_GENERATOR_URL` and
`SITE_GENERATOR_SERVICE_TOKEN`. Generic service adapters use
`SUBACTOR_<SCHEME>_URL` and optional `SUBACTOR_<SCHEME>_TOKEN`.

The recruitment draft route accepts only an instruction, current form values,
and an explicitly approved context object. It forwards to the deployment-owned
LLM Gateway using `LLM_GATEWAY_INTERNAL_URL` and `LLM_GATEWAY_SERVICE_TOKEN`.
Callers cannot inject a provider URL or credential, and raw page HTML is not an
input. The gateway returns a strict-schema draft with `status=draft`; the portal
validates it again before a human can insert it into the form.
