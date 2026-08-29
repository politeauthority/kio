#!/usr/bin/env bash
# Build the kubeconfig the release workflow uses to nudge ArgoCD (GitHub secret
# ARGOCD_KUBECONFIG, base64).
#
# Identity: ServiceAccount kio-ci in namespace argocd, whose Role allows only
# get/patch on the Application named `kio` — GitOps-owned in colfax-ops
# (cluster/argocd/overlays/kio-ci-rbac.yaml). Run with cluster-admin kubectl access:
#
#   scripts/argocd-kubeconfig.sh | gh secret set ARGOCD_KUBECONFIG -R politeauthority/kio
#
# The ARC runner pods are in-cluster, so the in-cluster API server URL is used by
# default; override with KUBE_API_SERVER for a laptop kubeconfig.
set -euo pipefail
NS=argocd
SA_SECRET=kio-ci-token
SERVER="${KUBE_API_SERVER:-https://kubernetes.default.svc}"

TOKEN=$(kubectl -n "$NS" get secret "$SA_SECRET" -o jsonpath='{.data.token}' | base64 -d)
CA=$(kubectl -n "$NS" get secret "$SA_SECRET" -o jsonpath='{.data.ca\.crt}')
[ -n "$TOKEN" ] && [ -n "$CA" ] || { echo "token secret $NS/$SA_SECRET not populated yet (has colfax-ops synced?)" >&2; exit 1; }

cat <<KC | base64 | tr -d '\n'
apiVersion: v1
kind: Config
clusters:
  - name: colfax
    cluster:
      server: ${SERVER}
      certificate-authority-data: ${CA}
users:
  - name: kio-ci
    user:
      token: ${TOKEN}
contexts:
  - name: argocd
    context:
      cluster: colfax
      user: kio-ci
      namespace: ${NS}
current-context: argocd
KC
echo >&2 "kubeconfig (base64) written to stdout — pipe into: gh secret set ARGOCD_KUBECONFIG -R politeauthority/kio"
