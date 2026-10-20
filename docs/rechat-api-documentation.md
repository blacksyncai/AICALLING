# Rechat documentation entry

Integrations now links to the user-provided official documentation:
https://docs.api.rechat.com/master/user.html

This is a documentation entry, not an enabled native account connector or CSV import. The API catalog exposes `native=false`, `can_import=false`, `can_log_calls=false`, and an explicit setup-required reason. Connect attempts are rejected rather than saving an unverified token or simulating success. The Integrations list now shows an API docs link for documented providers awaiting API verification.

Direct retrieval of the Rechat documentation failed with the environment proxy's network restriction. Public Rechat-owned app templates were inspected (`rechat/apps-contacts-boilerplate`, commit de7f9ca97f88e6256f43955339ff41a3c7bf7b93, and `apps-crm-boilerplate`); they describe embedded app interfaces but do not establish a server-side authentication/refresh/contact API contract for this connector. No endpoints or authentication grants were invented from those types.

`docs.api.rechat.com` and `api.rechat.com` were added to the environment network draft while preserving existing destinations. The save returned `requires_publish=true`; this does not apply runtime network access. Direct documentation access or an export of the relevant official API contracts is needed before implementing native authentication and contact/call synchronization. No Rechat credentials, account writes, provider fees or contact data were used.
