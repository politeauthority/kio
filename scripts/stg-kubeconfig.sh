#!/usr/bin/env bash
# Build the kubeconfig the STG workflow uses (GitHub secret STG_KUBECONFIG, base64).
#
# Identity: ServiceAccount kio-stg-ci in namespace kio-stg, with a namespace-scoped
# Role — both GitOps-owned in private-ops (kio/stg/ci-rbac.yaml). The long-lived
# token lives in Secret kio-stg-ci-token. Run with cluster-admin kubectl access:
#
#   scripts/stg-kubeconfig.sh | gh secret set STG_KUBECONFIG -R politeauthority/kio
#
# The API server address must be reachable from the ARC runner pods (in-cluster),
# so the in-cluster service URL is used by default; override with KUBE_API_SERVER.
set -euo pipefail
NS=kio-stg
SA_SECRET=kio-stg-ci-token
SERVER="${KUBE_API_SERVER:-https://kubernetes.default.svc}"

TOKEN=$(kubectl -n "$NS" get secret "$SA_SECRET" -o jsonpath='{.data.token}' | base64 -d)
CA=$(kubectl -n "$NS" get secret "$SA_SECRET" -o jsonpath='{.data.ca\.crt}')
[ -n "$TOKEN" ] && [ -n "$CA" ] || { echo "token secret $NS/$SA_SECRET not populated yet" >&2; exit 1; }

cat <<KC | base64 | tr -d '\n'
apiVersion: v1
kind: Config
clusters:
  - name: colfax
    cluster:
      server: ${SERVER}
      certificate-authority-data: ${CA}
users:
  - name: kio-stg-ci
    user:
      token: ${TOKEN}
contexts:
  - name: kio-stg
    context:
      cluster: colfax
      user: kio-stg-ci
      namespace: ${NS}
current-context: kio-stg
KC
echo >&2 "kubeconfig (base64) written to stdout — pipe into: gh secret set STG_KUBECONFIG -R politeauthority/kio"
