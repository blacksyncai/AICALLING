# Admin white label

Open **Admin portal → Clients → White label** from a client's action menu, or open the account details
and use its White label card. The platform super-admin login and the separate admin-portal unlock are
both required by every settings, logo, DNS and activation endpoint. Account owners/admins cannot configure it.

## What changes

Enable branding and set the display name, upload a PNG/JPEG/WebP logo (2 MB maximum), and optionally
enter a full hostname such as `app.customer.com`. The admin card previews the identity before activation.
Signed-in account members see the name/logo on the app shell even on the primary app URL. Active custom
hosts also use the identity before sign-in and in page titles/favicon. The marketing-site shortcut is hidden
in branded workspaces. The admin portal retains BlackSync branding.

This is app branding: voice-agent scripts, outbound email senders, billing/receipts, support operations,
and legal notices keep their existing configuration. The provider's authentication screen can still display
its required attribution. No real call or AI pipeline code is changed.

## One-time deployment configuration

Deploy the API and web from the same commit. The existing database startup adds the `white_labels`
table to the current database; it does not replace the database, reset data, or modify historical calls.
Logos are validated, decoded and resized to sanitized PNG bytes in that table, so a new file-storage
service is not required. The API image must install the added Pillow dependency.

Set `WHITE_LABEL_CNAME_TARGET` on the API to the actual custom-domain routing alias supplied by the
web hosting service. Do not guess an alias or use the API/voice-worker host. There is no default target:
DNS verification and activation are unavailable until it is configured.

The repository contains Railway, Render and older ECS deployment files and does not establish which
live hosting account owns the app. This implementation does not create hosting resources or claim
that DNS alone provisions HTTPS. Adding the hostname and issuing its certificate remain explicit
admin steps in the existing hosting account. Use a subdomain; apex flattening/proxied CNAMEs are not
supported by this direct-CNAME verifier.

### Password sign-in

Cookies remain host-only. Customers sign in on their own hostname; cookies from the primary app
are not shared across customer domains. There is no need to relax cookie scope or CORS.

### Clerk sign-in

Set `WHITE_LABEL_PRIMARY_ORIGIN=https://<canonical-app-host>` on **both** API and web. On customer hosts,
the web middleware and ClerkProvider use the SDK's `isSatellite` and `domain` options with central
sign-in/sign-up URLs. Verified customer sign-in/sign-up pages redirect to those primary authentication
pages with a return URL for the customer's dashboard; the SDK handles session synchronization.

Enable the appropriate satellite/multidomain setup in the existing Clerk instance and allow each customer's
HTTPS return origin. Configure any required DNS/proxy settings in Clerk, and complete a real sign-in on
the new hostname before confirming authentication readiness in the admin portal. This code cannot enable
a provider feature or prove certificate/auth readiness from a DNS answer, and validation uses no live Clerk
credentials. Primary-domain login behavior remains the default when satellite configuration is absent.

## Connect a customer domain

1. Save branding and the full hostname. The database enforces one account per hostname. Changing the
   hostname rotates the random proof token and clears verification/activation.
2. Add the displayed ownership TXT record at `_blacksync.<hostname>` and the CNAME pointing to the configured
   ingress alias. The UI shows complete names and values with copy buttons; some DNS dashboards expect
   names relative to their zone. Use DNS-only mode during verification.
3. Check DNS. The API queries a fixed DNS-over-HTTPS resolver for the exact owners and record types;
   it does not fetch arbitrary customer URLs. Ownership **and** routing must match. Resolver errors grant
   no verification. Missing records deactivate the mapping when checked.
4. Attach the hostname to web hosting, finish TLS, and configure/test sign-in. Confirm those two readiness
   checks and activate. Activation rechecks DNS; checking boxes cannot bypass ownership/routing proof.
5. Visit the workspace. Membership is still required: a domain selects the account but never grants access.
   Account switching to another tenant is blocked on a bound domain. Use the primary app for switching accounts.

Deactivating a domain or disabling branding revokes that hostname's account access in the API. Pending
reserved hosts also fail closed, rather than showing some other active account. DNS changes are rechecked
on explicit checks/activation, not continuously polled; keep monitoring and hosting/certificate management
with the existing hosting operator. If a domain is retired, remove it from hosting/DNS before releasing the
hostname from the account. Replacing the configured ingress target requires verification again.

The web ingress replaces incoming `X-Forwarded-Host` before proxying API requests. Any deployment exposing
the API through an additional proxy should enforce the same single-authority forwarded-host behavior.
There is no cross-tenant HTML/metadata cache: host branding is resolved without shared caching, while
sanitized logos use content-addressed immutable URLs.

## Tests

Backend: `python -m pytest -q tests/test_white_label.py tests/test_accounts.py tests/test_clerk.py` in `backend`.
Frontend: `npm run typecheck`, `npm run build`, and
`node --experimental-strip-types --test src/lib/white-label-clerk.test.mjs` in `web`.
Tests use the existing temporary SQLite fixture, mocked DNS, and local browser sessions with fake credentials.
