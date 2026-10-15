# BlackSync connector (ChatGPT, Claude and other MCP clients)

A remote MCP server that lets an AI assistant work in a customer's BlackSync account: onboarding, agents,
knowledge, contacts, campaigns, test calls and call results.

- **Server URL:** `https://blacksync.si/api/mcp` (Streamable HTTP, stateless JSON responses; GET/DELETE return 405)
- **Auth:** OAuth 2.1, with BlackSync as both the authorization server and the resource server
- **Customer setup guide:** `/connect/help`; connected assistants are listed under Integrations → ChatGPT & Claude

## OAuth

| Endpoint | Purpose |
| --- | --- |
| `/.well-known/oauth-protected-resource[/api/mcp]` | RFC 9728 metadata (resource, authorization server) |
| `/.well-known/oauth-authorization-server` | RFC 8414 metadata (S256 PKCE, DCR, CIMD, `iss` in responses) |
| `POST /api/oauth/register` | Dynamic client registration (public clients, or ones with a client secret) |
| `GET /api/oauth/authorize` | Validates the request, then sends the browser to `/connect` to approve |
| `GET /api/oauth/request`, `POST /api/oauth/approve` | Used by the approval page (the user signs in with the normal BlackSync login) |
| `POST /api/oauth/token` | `authorization_code` (PKCE S256 required) and `refresh_token` (rotated) grants |
| `POST /api/oauth/revoke` | RFC 7009 revocation |
| `GET/DELETE /api/oauth/connections` | The user's connected assistants |

### Client registration

Clients can register in either of two ways:

- **Dynamic client registration.** The client registers through `POST /api/oauth/register`.
- **Client ID metadata document.** The client uses an https URL as its `client_id`. These documents are fetched only from known hosts: chatgpt.com, claude.ai, claude.com and openai.com.

The approval page warns when the redirect isn't to a known assistant host.

### Codes and tokens

- The database stores only SHA-256 hashes of codes, tokens and client secrets.
- Lifetimes: access tokens 1 hour, refresh tokens 90 days, authorization codes 10 minutes.
- Authorization codes are single use. Replaying a code revokes what it was exchanged for.
- A rotated refresh token can be retried once within 60 seconds, in case the client lost the response.

### Accounts

The user picks an account when they approve. A user without an account can still connect: the `create_account` tool sets one up, and the connection then uses it.

## Tools

The tools are defined in `backend/app/connector/tools.py`.

Each tool calls the same router functions the web app uses, so permissions, plan limits and validation stay identical.

Tools that change data have `readOnlyHint: false`. `call_with_agent` and `start_campaign` are also marked `destructiveHint` and `openWorldHint`, so the assistant asks the user before running them.

| Area | Tools |
| --- | --- |
| Getting started | `get_started` (checklist and next step), `list_industries`, `create_account` |
| Knowledge | `get_business_profile`, `update_business_profile`, `scan_website`, `add_knowledge` |
| Agents | `list_agents`, `get_agent`, `list_voices`, `get_script_guide` + `create_agent` (the assistant writes the full script with the user and saves it to a new, paused agent — no Build with AI credits), `update_agent`, `launch_agent`, `call_with_agent` |
| Results | `list_calls`, `get_call` (transcript), `get_analytics` |
| Contacts and campaigns | `list_contacts`, `add_contacts`, `list_campaigns`, `get_campaign`, `create_campaign`, `start_campaign`, `pause_campaign` |
| Account | `list_phone_numbers`, `get_billing` |
| Lookup | `search`, `fetch` |

### Errors

Tool errors come back as `isError` results with a plain message the assistant can read.

Each connection is rate limited to 120 tool calls per minute.

Tests: `backend/tests/test_connector.py`.
