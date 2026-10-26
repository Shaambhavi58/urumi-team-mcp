#!/usr/bin/env bash
# Upgrade an EXISTING release, preserving its current storage and credentials.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
TASK_TMP="$(mktemp -d)"
chmod 700 "$TASK_TMP"
trap 'rm -rf "$TASK_TMP"' EXIT
helm --kube-context kind-urumi-local get values urumi-gateway -n urumi --all -o json > "$TASK_TMP/old.json"
chmod 600 "$TASK_TMP/old.json"
# JSON is valid Helm values. Save only compatibility fields, keeping all new defaults.
python3 - "$TASK_TMP" <<'PY'
import json, sys
from pathlib import Path
root=Path(sys.argv[1])
old=json.loads((root/'old.json').read_text())
keep={k:old[k] for k in ('namespace','persistence','resources','secrets','woocommercePublicUrl','llm','wooSecretName','provisioning') if k in old}
keep['ingress']={**old.get('ingress',{}),'className':'traefik'}
keep['provisioning']={**old.get('provisioning',{}),'enabled':True}
keep['images']={'gateway':'urumi-gateway:final1','dashboard':'urumi-dashboard:final1','mcp':'urumi-mcp-service:final1','wordpress':'urumi-woocommerce:final1'}
(root/'preserve.json').write_text(json.dumps(keep))
(root/'preserve.json').chmod(0o600)
PY
helm upgrade urumi-gateway ./charts/urumi-gateway \
  --kube-context kind-urumi-local -n urumi \
  -f ./charts/urumi-gateway/values-kind.yaml \
  -f ./charts/urumi-gateway/values-bonus.yaml \
  -f "$TASK_TMP/preserve.json" --wait --timeout 10m
kubectl --context kind-urumi-local get pods -n urumi
