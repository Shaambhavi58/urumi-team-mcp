# Urumi Team MCP Gateway

A React dashboard, FastAPI gateway and custom Streamable HTTP MCP servers on Kubernetes. WooCommerce provides real products/orders; Inventory and Shipping are explicitly demo upstreams. An LLM chat and external clients use the same authenticated gateway endpoint. The optional Stores feature provisions independent WooCommerce stores through the Kubernetes API.

## Architecture

Public Ingress exposes dashboard and storefront. The dashboard proxies `/api/` to the gateway, stripping that prefix. Gateway aggregates tools as `<server-slug>__<tool-name>` and calls upstreams internally. All tools require a per-user hashed gateway key; upstream credentials are encrypted server-side and never returned to clients. Chat forwards the connected user's bearer token to the gateway for every tool execution.

PostgreSQL stores users, keys, registry, audit logs and provisioning requests. MariaDB stores WordPress data; WordPress content is persisted separately. The provisioner is a separate trusted controller with Kubernetes API credentials; the public gateway has no mounted ServiceAccount token.

See [system design](docs/system-design.md), [threat model](docs/threat-model.md), [multi-store](docs/multi-store.md) and [demo checklist](docs/demo-runbook.md).

## Existing local deployment: update without resetting data

Use this path for the already-working `urumi-local` cluster. Do not uninstall the release or delete PVCs. Keep the previous source folder for rollback.

```bash
bash scripts/build-kind-images.sh urumi-local final1
bash scripts/upgrade-local.sh
kubectl --context kind-urumi-local get pods -n urumi
```

The upgrade script copies current Helm persistence/credential settings into a private temporary file, switches to the new image tags, and enables provisioning. The chart reuses existing Secret values. All new database schema is additive (`stores` table); existing users/orders/keys are retained. Helm does not create a backup: take DB/content backups before a production upgrade.

Keep a separate terminal running:

```bash
kubectl --context kind-urumi-local port-forward -n ingress-system service/traefik 8088:80
```

Existing local `/etc/hosts` entries: `127.0.0.1 urumi.local shop.urumi.local`. Dashboard: http://urumi.local:8088. Store: http://shop.urumi.local:8088. Gateway MCP: http://urumi.local:8088/api/mcp.

## Fresh local install

Prerequisites: Docker Desktop, Kind, kubectl, Helm, Python/uv and Node. A policy-enforcing network plugin is required for NetworkPolicy isolation. Verify enforcement with the supplied test; a NetworkPolicy object alone is insufficient.

```bash
kind create cluster --name urumi-local
kubectl --context kind-urumi-local wait --for=condition=Ready node --all --timeout=120s
bash scripts/build-kind-images.sh urumi-local final1
helm repo add traefik https://traefik.github.io/charts
helm repo update
helm upgrade --install traefik traefik/traefik --kube-context kind-urumi-local \
  --namespace ingress-system --create-namespace
```

Create the provider Secret without putting the key in shell history (Groq-compatible key for the default values):

```bash
kubectl --context kind-urumi-local create namespace urumi
python3 - <<'PY'
import getpass,json,subprocess
key=getpass.getpass('Paste your Groq API key: ').strip()
secret={'apiVersion':'v1','kind':'Secret','metadata':{'name':'urumi-llm','namespace':'urumi'},'type':'Opaque','stringData':{'OPENAI_API_KEY':key}}
subprocess.run(['kubectl','--context','kind-urumi-local','apply','-f','-'],input=json.dumps(secret),text=True,check=True)
PY
```

Create `urumi-woo` initially with empty consumer fields, then replace them after WordPress initialization. Empty fields cause the WooCommerce MCP to reject calls rather than silently use fake store data.

```bash
kubectl --context kind-urumi-local create secret generic urumi-woo -n urumi \
  --from-literal=WOO_CONSUMER_KEY= --from-literal=WOO_CONSUMER_SECRET=
helm upgrade --install urumi-gateway ./charts/urumi-gateway --kube-context kind-urumi-local \
  -n urumi -f ./charts/urumi-gateway/values-kind.yaml -f ./charts/urumi-gateway/values-bonus.yaml
```

Start the port-forward above; add the hosts entries. Open WordPress admin and complete installation, activate WooCommerce, set INR, COD and a free shipping zone, set Site visibility Live and save Post name permalinks. Generate a Read/Write REST API key owned by an administrator. Store it in `urumi-woo` using a hidden-input Python script analogous to the LLM Secret, with fields `WOO_CONSUMER_KEY` and `WOO_CONSUMER_SECRET`. Restart `deployment/woocommerce-mcp` after updating that Secret. The first manually configured store and automatically provisioned stores use the same custom MCP source.

Bootstrap the dashboard administrator:

```bash
kubectl --context kind-urumi-local exec -n urumi deployment/gateway -- \
  python -m app.bootstrap_admin --email YOUR_EMAIL --name 'Your Name'
```

Copy the one-time key privately and connect the dashboard. For the existing installation use its existing key; do not bootstrap repeatedly.

## Use and demo

- Admin: register/edit/disable/remove MCP servers; create a member and issue a one-time key. Members can generate/revoke their own keys in My API Keys. A bootstrap key is needed for a member's first login.
- Tool Explorer: arguments are a JSON object. `list_orders` accepts `{}` or `{"today":true}`; Inspector's generated `status` field must not contain the text `{}`.
- Chat: ask to create a named product with a price; verify it on the storefront; manually check out with COD; ask for today's orders. `today` uses `STORE_TIMEZONE` (default Asia/Kolkata); WordPress is configured UTC for bonus stores. Chat permits up to eight model rounds and displays tools called.
- Each order response is minimized to operational fields; private order keys, addresses and metadata are not sent to the LLM.
- To provision stores, use Stores and follow [the multi-store demo](docs/multi-store.md).

### External MCP clients

Cursor user-global `~/.cursor/mcp.json` (do not commit the real token):

```json
{"mcpServers":{"urumi-member":{"url":"http://urumi.local:8088/api/mcp","headers":{"Authorization":"Bearer YOUR_MEMBER_KEY"}}}}
```

MCP Inspector: `npx @modelcontextprotocol/inspector`, Streamable HTTP URL above, Custom Header `Authorization` with `Bearer ` plus member key. No upstream credential is needed.

External prompt: "Use only urumi-member tools. Check SKU-MUG stock and estimate shipping to 122001 at 1 kg. Call both Inventory and Shipping, then summarize. Do not modify data." Verify both successful audit entries under the member user. Also ask for today's WooCommerce orders.

Revoke that key in the admin dashboard: its next request must return HTTP 401. Issue a fresh key before further tests. Disable Shipping and refresh tools: its three tools disappear from chat and clients. Temporarily scale Shipping to zero, discover tools, call Inventory, observe Unreachable, then restore one replica. To show a literal pod kill as requested in the assignment, delete a Shipping pod while another upstream is being used; a Deployment recreates it, so the failure window may be brief. Do not treat scale-to-zero as identical to a literal pod-deletion demonstration.

## Production-like k3s

Build/push the same four images to a registry accessible to the VPS. Edit `values-k3s.yaml` for image tags, domains, ingress class/namespace and storage class. Use persistent disks and a Delete-reclaim class for disposable bonus stores. Point dashboard/store DNS records and `*.stores.example.com` at the VPS. Set public ports empty. Create provider/WooCommerce Secrets securely in the target namespace; use a secrets manager or sealed secrets for GitOps. Enable k3s NetworkPolicy enforcement and test it. TLS is optional for the assignment, but use HTTPS and appropriate per-namespace certificates for production.

```bash
helm upgrade --install urumi-gateway ./charts/urumi-gateway -n urumi --create-namespace \
  -f ./charts/urumi-gateway/values-k3s.yaml --wait --timeout 10m
```

Use the fresh-install WordPress/bootstrap flow, now at production domains. There are no separate production manifests: chart and controller code are the same, configuration changes only. Single-node local-path storage is not highly available. A VPS deployment has not been executed by this bundle's local test run.

### Upgrade / rollback

Back up PostgreSQL, each MariaDB and content PVC first. Use immutable versioned image tags and `helm upgrade --wait`. Inspect `helm history urumi-gateway -n urumi`; roll back with `helm rollback urumi-gateway REVISION -n urumi --wait`. Rollback changes workload templates, not database state or store resources already created by the controller. Stop new provisioning before rollback; preserve the additive stores table. Restore a compatible backup for destructive schema/application changes.

## Tests

```bash
cd backend
uv sync --extra dev
uv run ruff check app tests
uv run --with jsonschema pytest -q tests ../services/mcp-service/tests
cd ../dashboard
npm ci
npm run build
cd ..
helm lint ./charts/urumi-gateway -f ./charts/urumi-gateway/values-bonus.yaml
helm lint ./charts/urumi-gateway -f ./charts/urumi-gateway/values-k3s.yaml
```

Automated tests cover access/revocation, registry/audits, store ownership/quota/idempotency, mocked controller recovery/cleanup, resource boundaries, MCP auth/argument validation/date filters. Live validation performed on the Kind cluster is recorded separately in [verification status](docs/current-status.md). Unit tests are not a substitute for live behavior; the status note separates demonstrated behavior from limitations.


## Attempted bonus and differentiators

- Multi-store provisioning: `backend/app/stores.py`, `provisioner.py`, `store_resources.py`, `dashboard/src/Stores.jsx`; live evidence in `docs/current-status.md`.
- Encrypted upstream credentials, separate controller identity, gateway-only MCP network access, per-store isolation and quotas: see `docs/threat-model.md` and chart templates.
- Upgrade/rollback procedures: this README and `scripts/upgrade-local.sh`.
- Not implemented/demonstrated: actual VPS deployment, gateway OAuth, per-tool permissions, tool-search routing, image-based upstream hosting, multi-replica load testing, rate limits or a metrics backend.

API documentation is available at `http://urumi.local:8088/api/docs`; its relative schema/server URLs also support direct gateway port forwarding. Use the unprefixed routes (`/stores`, `/mcp`, `/audit`) shown there; `/api/...` gateway aliases exist for compatibility and are not needed through the dashboard proxy.

Before publishing, rotate any API key previously displayed in terminal captures or chat. Never record the Connect field, Authorization header, one-time key screen or Kubernetes Secret contents in the demo.
