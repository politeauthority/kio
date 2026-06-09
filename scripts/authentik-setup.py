#!/usr/bin/env python3
"""
Create the kio OAuth2/OIDC application in Authentik and print the client ID.

Usage:
    python3 scripts/authentik-setup.py --token <admin-api-token>

Get your API token: Authentik admin UI → Admin Interface → Directory → Tokens
Create one with intent "API" for your admin user.

After running, paste the printed client ID into:
  kubernetes-manifests/envs/prd/auth-patch.yaml  (OIDC_CLIENT_ID value)
Then re-apply: kubectl apply -k kubernetes-manifests/envs/prd/
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

AUTHENTIK_URL = os.environ.get("AUTHENTIK_URL", "https://auth.example.com")
APP_SLUG = "kio"
APP_NAME = "kio Kiosk Manager"
REDIRECT_URI = os.environ.get("KIO_REDIRECT_URI", "http://kio.example.local/callback")
SCOPES = ["openid", "profile", "email"]


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
    managed_prefixes = [
        "goauthentik.io/providers/oauth2/scope-openid",
        "goauthentik.io/providers/oauth2/scope-profile",
        "goauthentik.io/providers/oauth2/scope-email",
    ]
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


def find_or_create_provider(token):
    result = api(token, "GET", "/providers/oauth2/", params={"name": APP_NAME})
    hits = _results(result)
    if hits:
        p = hits[0]
        print(f"  Provider already exists (pk={p['pk']})")
        return p

    invalidation_flow = _get_default_invalidation_flow(token)
    body = {
        "name": APP_NAME,
        "client_type": "public",
        "redirect_uris": [{"url": REDIRECT_URI, "matching_mode": "strict"}],
        "authorization_flow": _get_default_auth_flow(token),
        "access_token_validity": "hours=24",
    }
    if invalidation_flow:
        body["invalidation_flow"] = invalidation_flow
    scope_pks = _find_scope_pks(token)
    if scope_pks is not None:
        body["property_mappings"] = scope_pks

    provider = api(token, "POST", "/providers/oauth2/", body)
    print(f"  Created provider (pk={provider['pk']})")
    return provider


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
    print(f"  Redirect:  {REDIRECT_URI}")
    print()

    print("1. Finding/creating OIDC provider...")
    provider = find_or_create_provider(token)

    print("2. Finding/creating application...")
    find_or_create_application(token, provider["pk"])

    client_id = provider["client_id"]
    issuer = f"{AUTHENTIK_URL}/application/o/{APP_SLUG}/"

    print()
    print("=" * 60)
    print("Authentik setup complete. Add these values to k8s:")
    print()
    print(f"  OIDC_AUTHORITY  = {issuer}")
    print(f"  OIDC_CLIENT_ID  = {client_id}")
    print()
    print("Edit kubernetes-manifests/envs/prd/auth-patch.yaml")
    print("Set OIDC_CLIENT_ID value, then:")
    print("  kubectl apply -k kubernetes-manifests/envs/prd/")
    print("=" * 60)


if __name__ == "__main__":
    main()
