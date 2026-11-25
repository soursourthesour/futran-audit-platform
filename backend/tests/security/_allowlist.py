"""Routes that do not reach `authorize`, each with the reason it does not need to.

Keys are "METHOD /path" exactly as the app registers them. A new route that does not reach `authorize` fails
tests/security/test_route_authorize.py until it is either given a permission check or added here with a reason.

`PUBLIC` routes take no session at all (sign-in, token links, OAuth callbacks, the public API with its own bearer
token). `SIGNED_IN` routes need a session but act only on the caller's own records or on shared reference data, so no
role decides them.
"""

PUBLIC: dict[str, str] = {
    # framework and shell
    "GET /api/openapi.json": "FastAPI schema document; describes routes, holds no tenant data.",
    "GET /api/docs": "FastAPI Swagger page; static.",
    "GET /docs/oauth2-redirect": "FastAPI Swagger OAuth helper page; static.",
    "GET /api/public/v1/openapi.json": "Public API schema document; describes routes, holds no tenant data.",
    "GET /api/public/v1/docs": "Public API Swagger page; static.",
    "GET /api/public/v1/docs/oauth2-redirect": "Public API Swagger OAuth helper page; static.",
    "GET /api/v1/health": "Liveness probe; returns status, version and region only.",
    "GET /api/{rest:path}": "Catch-all that answers 404 for unknown API paths.",
    "POST /api/{rest:path}": "Catch-all that answers 404 for unknown API paths.",
    "PUT /api/{rest:path}": "Catch-all that answers 404 for unknown API paths.",
    "PATCH /api/{rest:path}": "Catch-all that answers 404 for unknown API paths.",
    "DELETE /api/{rest:path}": "Catch-all that answers 404 for unknown API paths.",
    "GET /{full_path:path}": "Serves the built web app (static files and index.html).",
    # sign-in
    "POST /api/v1/auth/login": "Sign-in; checks the password and creates the session.",
    "GET /api/v1/auth/session": "Reports whether the cookie holds a session and whether MFA is done.",
    "POST /api/v1/auth/mfa/enroll": "MFA enrolment for the half-signed-in session (current_session).",
    "POST /api/v1/auth/mfa/verify": "MFA code check for the half-signed-in session (current_session).",
    "POST /api/v1/auth/logout": "Ends the caller's own session.",
    # invitation links
    "GET /api/v1/invitations/accept/{token}": "Invitation link; the single-use token identifies the invitee.",
    "POST /api/v1/invitations/accept/{token}": "Invitation link; the single-use token identifies the invitee.",
    "POST /api/v1/invitations/decline/{token}": "Invitation link; the single-use token identifies the invitee.",
    # public token links
    "GET /api/v1/public/attest/{token}": "Attestation link; the token identifies one person's line item.",
    "POST /api/v1/public/attest/{token}": "Attestation link; the token identifies one person's line item.",
    "GET /api/v1/public/confirm/{token}": "Named-user confirmation link; the token identifies one confirmation.",
    "POST /api/v1/public/confirm/{token}": "Named-user confirmation link; the token identifies one confirmation.",
    "GET /api/v1/public/m/{token}": "Personal mail link; the token identifies one recipient.",
    "POST /api/v1/public/m/{token}/attestation": "Personal mail link; the token identifies one recipient.",
    "POST /api/v1/public/m/{token}/done": "Personal mail link; the token identifies one recipient.",
    "GET /api/v1/public/m/s/{token}": "Shared mail link; a one-time code sent to the recipient gates the answers.",
    "POST /api/v1/public/m/s/{token}/code": "Shared mail link; sends the one-time code to a listed recipient.",
    "POST /api/v1/public/m/s/{token}/verify": "Shared mail link; checks the one-time code.",
    "POST /api/v1/public/m/s/{token}/attestation": "Shared mail link; needs the verified one-time code.",
    "POST /api/v1/public/m/s/{token}/done": "Shared mail link; needs the verified one-time code.",
    "GET /api/v1/public/training/{token}": "Training link; the token identifies one assignment.",
    "POST /api/v1/public/training/{token}/check": "Training link; the token identifies one assignment.",
    "POST /api/v1/public/training/{token}/finish": "Training link; the token identifies one assignment.",
    "GET /api/v1/public/training/{token}/certificate": "Training link; the token identifies one assignment.",
    "GET /api/v1/public/trust/{slug}": "Public Trust Center page the client chose to publish.",
    "POST /api/v1/public/trust/{slug}/nda": "Public Trust Center NDA acceptance; unlocks gated documents.",
    "GET /api/v1/public/trust/{slug}/items/{item_id}/document": "Public Trust Center document; gated items need the NDA access key.",
    "GET /api/v1/public/q/{token}": "Scoping questionnaire link sent to a prospect; the token identifies it.",
    "PUT /api/v1/public/q/{token}/answers": "Scoping questionnaire link sent to a prospect; the token identifies it.",
    "POST /api/v1/public/q/{token}/forward": "Scoping questionnaire link sent to a prospect; the token identifies it.",
    "POST /api/v1/public/q/{token}/submit": "Scoping questionnaire link sent to a prospect; the token identifies it.",
    "GET /api/v1/public/p/{token}": "Proposal acceptance link sent to a prospect; the token identifies it.",
    "GET /api/v1/public/p/{token}/pdf": "Proposal acceptance link sent to a prospect; the token identifies it.",
    "POST /api/v1/public/p/{token}/accept": "Proposal acceptance link sent to a prospect; the token identifies it.",
    "POST /api/v1/public/p/{token}/changes": "Proposal acceptance link sent to a prospect; the token identifies it.",
    # OAuth callbacks
    "GET /api/v1/mail/oauth/{provider}": "Mail OAuth callback; the signed single-use state identifies the connection.",
    "POST /api/v1/mail/oauth/{provider}/test": "Test-mode stand-in for the provider consent page; 404 outside test mode.",
    "GET /api/v1/mail/test-consent-info": "Test-mode consent page details for a signed state; 404 outside test mode.",
    "GET /api/v1/connectors/oauth/{provider}": "Connector OAuth callback; signed state plus the session that started it, checked in complete_consent.",
    "POST /api/v1/connectors/oauth/{provider}/test": "Test-mode stand-in for the connector consent page; 404 outside test mode.",
    # public API: bearer tokens with their own scopes (app.publicapi.auth.require)
    "POST /api/public/v1/oauth/token": "Public API OAuth client-credentials token endpoint.",
    "GET /api/public/v1/me": "Public API; bearer token, scope checked by publicapi.auth.require.",
    "GET /api/public/v1/inventory/systems": "Public API; bearer token, scope checked by publicapi.auth.require.",
    "GET /api/public/v1/inventory/systems/{system_id}": "Public API; bearer token, scope checked by publicapi.auth.require.",
    "POST /api/public/v1/inventory/systems": "Public API; bearer token, scope checked by publicapi.auth.require.",
    "PATCH /api/public/v1/inventory/systems/{system_id}": "Public API; bearer token, scope checked by publicapi.auth.require.",
    "GET /api/public/v1/inventory/departments": "Public API; bearer token, scope checked by publicapi.auth.require.",
    "GET /api/public/v1/inventory/tools": "Public API; bearer token, scope checked by publicapi.auth.require.",
    "POST /api/public/v1/usecases": "Public API; bearer token, scope checked by publicapi.auth.require.",
    "GET /api/public/v1/attestation/status": "Public API; bearer token, scope checked by publicapi.auth.require.",
    "GET /api/public/v1/findings": "Public API; bearer token, scope checked by publicapi.auth.require.",
    "GET /api/public/v1/findings/{finding_id}": "Public API; bearer token, scope checked by publicapi.auth.require.",
    "GET /api/public/v1/remediation": "Public API; bearer token, scope checked by publicapi.auth.require.",
    "GET /api/public/v1/updates": "Public API; bearer token, scope checked by publicapi.auth.require.",
    "POST /api/public/v1/agents/{system_id}/decisions": "Public API; bearer token, scope checked by publicapi.auth.require.",
}

SIGNED_IN: dict[str, str] = {
    "GET /api/v1/auth/me": "The caller's own profile, roles and allowed actions.",
    "POST /api/v1/auth/terms": "The caller accepts the terms for their own account.",
    "GET /api/v1/me/notifications": "The caller's own notifications (filtered by user_id).",
    "POST /api/v1/notifications/{notification_id}/read": "Marks the caller's own notification read; 404 for anyone else's.",
    "POST /api/v1/notifications/read-all": "Marks the caller's own notifications read.",
    "GET /api/v1/me/mailbox": "The caller's own personal mailbox connection.",
    "POST /api/v1/me/mailbox/connect": "Starts consent for the caller's own mailbox.",
    "POST /api/v1/me/mailbox/decline": "Declines the caller's own mailbox connection.",
    "POST /api/v1/me/mailbox/disconnect": "Disconnects the caller's own mailbox.",
    "GET /api/v1/staff/alerts": "The Futran caller's own refresh alerts (Futran only, filtered by user_id).",
    "POST /api/v1/staff/alerts/{alert_id}/read": "Marks the caller's own staff alert read; 404 for anyone else's.",
    "POST /api/v1/staff/alerts/read-all": "Marks the caller's own staff alerts read.",
    "GET /api/v1/laws": "Published law library: shared reference data with no tenant rows.",
    "GET /api/v1/laws/features": "Static list of law feature labels.",
    "GET /api/v1/laws/{law_id}": "One published law: shared reference data with no tenant rows.",
    "GET /api/v1/jurisdictions": "Jurisdiction reference list: shared data with no tenant rows.",
    "GET /api/v1/jurisdictions/resolve": "Resolves a place to jurisdictions: shared reference data.",
    "GET /api/v1/audit-log": "Matrix-checked through scopes_for(VIEW_AUDIT_LOG); rows filtered to the scope.",
}

ALLOWLIST: dict[str, str] = {**PUBLIC, **SIGNED_IN}

# Routes that neither reach `authorize` nor belong on the allowlist. Each is a finding with a strict xfail.
FINDINGS: dict[str, str] = {}  # Y01 (the mail outbox) was fixed on 25 Nov: it now calls authorize with VIEW_OUTBOX
