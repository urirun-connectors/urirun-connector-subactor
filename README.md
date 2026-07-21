# urirun-connector-subactor

Server-side connector for URI processes implemented by Subactor services.

It provides concrete routes such as `site-generator://host/site/command/generate`,
`organization://host/status/query`, and
`recruitment://host/job-offer/command/draft`, plus a controlled
`<scheme>://host/process/command/dispatch` route for Subactor-owned schemes.
Every target base URL and credential comes from the node environment; an actor
cannot inject a target host or bearer token through the process payload.

Supported schemes: `analytics`, `contractor`, `docs`, `mail`, `org`,
`organization`, `project`, `recruitment`, `site-generator`, `social`, `support`, `test`,
`testql`, and `webpage`.

For `site-generator://host/site/command/generate`, configure `SITE_GENERATOR_URL` and
`SITE_GENERATOR_SERVICE_TOKEN`. Generic service adapters use
`SUBACTOR_<SCHEME>_URL` and optional `SUBACTOR_<SCHEME>_TOKEN`.

The recruitment draft route accepts only an instruction, current form values,
and an explicitly approved context object. It forwards to the deployment-owned
LLM Gateway using `LLM_GATEWAY_INTERNAL_URL` and `LLM_GATEWAY_SERVICE_TOKEN`.
Callers cannot inject a provider URL or credential, and raw page HTML is not an
input. The gateway returns a strict-schema draft with `status=draft`; the portal
validates it again before a human can insert it into the form.
