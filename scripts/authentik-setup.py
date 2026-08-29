#!/usr/bin/env python3
"""
Create the kio OAuth2/OIDC application in Authentik and print the client ID.

Usage:
    python3 scripts/authentik-setup.py --token <admin-api-token>

Get your API token: Authentik admin UI → Admin Interface → Directory → Tokens
Create one with intent "API" for your admin user.

Environment:
    AUTHENTIK_URL      Base URL of Authentik (default https://auth.example.com)
    AUTHENTIK_SIGNING_KEY
                       Name of the certificate-key pair the provider signs tokens
                       with (default "authentik Self-signed Certificate"). Must
                       have a private key. Without a signing key Authentik issues
                       HS256 tokens, which the kio API rejects — it only accepts
                       RS*/ES* from Authentik so a dev HS256 token can never be
                       confused with one.
    KIO_REDIRECT_URIS  Comma-separated allowed redirect URIs, one per kio
                       environment, e.g.
                       https://kio.example.com/callback,https://stg.kio.example.com/callback
                       (default http://kio.example.local/callback)

After running, set the printed AUTHENTIK_ISSUER / AUTHENTIK_CLIENT_ID on the
kio API (kubernetes-manifests/envs/<env>/api-configmap-patch.yaml) and
re-apply: kubectl apply -k kubernetes-manifests/envs/<env>/

Re-running is safe: an existing provider has its redirect URIs, scopes and
signing key brought up to date; nothing else is changed.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

AUTHENTIK_URL = os.environ.get("AUTHENTIK_URL", "https://auth.example.com")
SIGNING_KEY_NAME = os.environ.get("AUTHENTIK_SIGNING_KEY", "authentik Self-signed Certificate")
APP_SLUG = "kio"
APP_NAME = "kio Kiosk Manager"
REDIRECT_URIS = [
    u.strip()
    for u in os.environ.get(
        "KIO_REDIRECT_URIS", os.environ.get("KIO_REDIRECT_URI", "http://kio.example.local/callback")
    ).split(",")
    if u.strip()
]
# offline_access lets the UI obtain a refresh token so sessions renew silently
# instead of redirecting through Authentik every time the access token expires.
SCOPES = ["openid", "profile", "email", "offline_access"]


def api(token, method, path, body=None, params=None):
    qs = ("?" + urllib.parse.urlencode(params)) if params else ""
    url = f"{AUTHENTIK_URL}/api/v3{path}{qs}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"  HTTP {e.code} {method} {path}: {body}", file=sys.stderr)
        raise


def _find_scope_pks(token):
    managed_prefixes = [f"goauthentik.io/providers/oauth2/scope-{scope}" for scope in SCOPES]
    try:
        r = api(token, "GET", "/propertymappings/all/")
        pks = [
            m["pk"] for m in _results(r)
            if any(m.get("managed", "").startswith(p) for p in managed_prefixes)
        ]
        if pks:
            return pks
    except urllib.error.HTTPError:
        pass
    return None


def _find_signing_key(token):
    """Return the pk of the certificate-key pair the provider should sign with.

    Prefers the pair named by AUTHENTIK_SIGNING_KEY; falls back to any pair
    that has a private key. Returns None (with a warning) if there is none —
    the provider would then issue HS256 tokens the kio API refuses.
    """
    try:
        r = api(token, "GET", "/crypto/certificatekeypairs/", params={"has_key": "true"})
    except urllib.error.HTTPError:
        return None
    pairs = _results(r)
    for pair in pairs:
        if pair.get("name") == SIGNING_KEY_NAME:
            return pair["pk"]
    if pairs:
        print(
            f"  WARNING: no certificate named {SIGNING_KEY_NAME!r}; signing with {pairs[0]['name']!r} instead",
            file=sys.stderr,
        )
        return pairs[0]["pk"]
    print(
        "  WARNING: Authentik has no certificate-key pair with a private key — the "
        "provider will sign HS256 tokens, which the kio API does not accept. Create "
        "one under Admin → System → Certificates and re-run.",
        file=sys.stderr,
    )
    return None


def _existing_provider(token):
    """The provider already attached to the kio application, else one matching
    APP_NAME. Looking through the application first means a provider that was
    created by hand under a different name is updated rather than duplicated."""
    result = api(token, "GET", "/core/applications/", params={"slug": APP_SLUG})
    hits = _results(result)
    if hits and hits[0].get("provider"):
        try:
            return api(token, "GET", f"/providers/oauth2/{hits[0]['provider']}/")
        except urllib.error.HTTPError:
            pass  # attached provider isn't OAuth2 — fall through to a name match
    result = api(token, "GET", "/providers/oauth2/", params={"name": APP_NAME})
    hits = _results(result)
    return hits[0] if hits else None


def find_or_create_provider(token):
    signing_key = _find_signing_key(token)
    p = _existing_provider(token)
    if p:
        print(f"  Provider already exists (pk={p['pk']}, {p.get('name')!r}) — syncing redirect URIs, scopes and signing key")
        patch = {"redirect_uris": _redirect_uris()}
        scope_pks = _find_scope_pks(token)
        if scope_pks is not None:
            patch["property_mappings"] = scope_pks
        if signing_key is not None:
            patch["signing_key"] = signing_key
        return api(token, "PATCH", f"/providers/oauth2/{p['pk']}/", patch)

    invalidation_flow = _get_default_invalidation_flow(token)
    body = {
        "name": APP_NAME,
        "client_type": "public",
        "redirect_uris": _redirect_uris(),
        "authorization_flow": _get_default_auth_flow(token),
        "access_token_validity": "hours=24",
    }
    if signing_key is not None:
        body["signing_key"] = signing_key
    if invalidation_flow:
        body["invalidation_flow"] = invalidation_flow
    scope_pks = _find_scope_pks(token)
    if scope_pks is not None:
        body["property_mappings"] = scope_pks

    provider = api(token, "POST", "/providers/oauth2/", body)
    print(f"  Created provider (pk={provider['pk']})")
    return provider


def _redirect_uris():
    return [{"url": uri, "matching_mode": "strict"} for uri in REDIRECT_URIS]


def _results(r):
    """Extract results list from a paginated or plain-list response."""
    if isinstance(r, dict):
        return r.get("results", [])
    if isinstance(r, list):
        return r
    return []


def _get_default_auth_flow(token):
    result = api(token, "GET", "/flows/instances/", params={"slug": "default-authentication-flow"})
    hits = _results(result)
    if hits:
        return hits[0]["pk"]
    result = api(token, "GET", "/flows/instances/", params={"designation": "authentication"})
    hits = _results(result)
    if not hits:
        print(f"  DEBUG flows response: {json.dumps(result)[:400]}", file=sys.stderr)
        raise RuntimeError("Could not find any authentication flow in Authentik")
    return hits[0]["pk"]


def _get_default_invalidation_flow(token):
    result = api(token, "GET", "/flows/instances/", params={"slug": "default-provider-invalidation-flow"})
    hits = _results(result)
    if hits:
        return hits[0]["pk"]
    result = api(token, "GET", "/flows/instances/", params={"designation": "invalidation"})
    hits = _results(result)
    return hits[0]["pk"] if hits else None


def find_or_create_application(token, provider_pk):
    result = api(token, "GET", "/core/applications/", params={"slug": APP_SLUG})
    hits = _results(result)
    if hits:
        app = hits[0]
        print(f"  Application already exists (slug={app['slug']})")
        return app

    app = api(token, "POST", "/core/applications/", {
        "name": APP_NAME,
        "slug": APP_SLUG,
        "provider": provider_pk,
        "meta_description": "kio kiosk management dashboard",
    })
    print(f"  Created application (slug={app['slug']})")
    return app


def main():
    parser = argparse.ArgumentParser(description="Set up kio in Authentik")
    parser.add_argument("--token", required=True, help="Authentik admin API token")
    args = parser.parse_args()

    token = args.token

    print("Setting up Authentik for kio...")
    print(f"  Authentik: {AUTHENTIK_URL}")
    print(f"  App slug:  {APP_SLUG}")
    for uri in REDIRECT_URIS:
        print(f"  Redirect:  {uri}")
    print()

    print("1. Finding/creating OIDC provider...")
    provider = find_or_create_provider(token)

    print("2. Finding/creating application...")
    find_or_create_application(token, provider["pk"])

    client_id = provider["client_id"]
    issuer = f"{AUTHENTIK_URL}/application/o/{APP_SLUG}/"

    print()
    print("=" * 60)
    print("Authentik setup complete. Set these on the kio API:")
    print()
    print(f"  AUTHENTIK_ISSUER     = {issuer}")
    print(f"  AUTHENTIK_CLIENT_ID  = {client_id}")
    print(f"  AUTHENTIK_DISPLAY_NAME = Authentik   # optional, login button label")
    print()
    print("Verify the provider signs asymmetrically (must NOT be HS256):")
    print(f"  curl -s {issuer}.well-known/openid-configuration | grep id_token_signing_alg")
    print()
    print("Edit kubernetes-manifests/envs/<env>/api-configmap-patch.yaml, then:")
    print("  kubectl apply -k kubernetes-manifests/envs/<env>/")
    print("  kubectl rollout restart deployment/kio-api -n <namespace>")
    print()
    print("Reminder: bind an Authentik policy/group to the application to")
    print("control WHO may sign in — kio accepts any user Authentik lets through.")
    print("=" * 60)


if __name__ == "__main__":
    main()
