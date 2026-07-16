# urirun-connector-subactor

Server-side connector for URI processes implemented by Subactor services.

It provides concrete routes such as `site-generator://host/site/command/generate` and
`organization://host/status/query`, plus a controlled
`<scheme>://host/process/command/dispatch` route for Subactor-owned schemes.
Every target base URL and credential comes from the node environment; an actor
cannot inject a target host or bearer token through the process payload.

Supported schemes: `analytics`, `contractor`, `docs`, `mail`, `org`,
`organization`, `project`, `site-generator`, `social`, `support`, `test`,
`testql`, and `webpage`.

For `site-generator://host/site/command/generate`, configure `SITE_GENERATOR_URL` and
`SITE_GENERATOR_SERVICE_TOKEN`. Generic service adapters use
`SUBACTOR_<SCHEME>_URL` and optional `SUBACTOR_<SCHEME>_TOKEN`.
