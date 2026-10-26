# Two-user live demo and recording guide

Use a fresh demo product/order created on recording day. Yesterday's orders must not be presented as today's orders. Keep keys/Authorization/Secret values out of every recorded frame. Enter credentials before recording, or crop/pause for those steps.

## 1. Architecture and Kubernetes

Explain: browser → Ingress/dashboard proxy → gateway → custom MCP → WooCommerce REST API → MariaDB. PostgreSQL persists users, hashed keys, encrypted credentials, audit events and store requests. The separate provisioner uses Kubernetes API credentials; the public gateway has no mounted token.

Show namespaces and workload status, PVCs, Ingress, requests/limits and probes. Show Secret names only, never `-o yaml`/decoded data. Explain the same Helm chart with local versus k3s values, registry images, DNS, storage class and Secrets. No actual VPS deployment is claimed.

## 2. User A: real store, chat, checkout

1. Connect the admin dashboard privately before recording.
2. Show registered WooCommerce, Inventory and Shipping with their tools and statuses.
3. Ask AI Chat to create a uniquely named product with a price (and an existing same-store media attachment ID if demonstrating images). Note the tool name and product ID.
4. Open the real storefront, add that product to cart and check out using COD. Show order confirmation and the same order in WooCommerce admin. For provisioned stores use operator-held admin access; do not reveal its Secret.
5. Ask the chat for today's orders from the exact store prefix. Verify the newly placed order and its total. Show User A audit attribution.

## 3. User B: keys and external client

1. In a private browser session connect as Demo Member, generate a key in My API Keys and use it; hide the one-time key screen.
2. Cursor configuration uses only one gateway URL and that member key. Refresh/reconnect tools after registrations change; start a fresh chat if the catalog is stale.
3. Ask for today's orders using the exact store-prefixed tool; confirm order/store identity.
4. One prompt: “Check stock for SKU-MUG and estimate shipping to 122001 at 1 kg. Use inventory__check_stock and shipping__estimate_shipping. Do not modify data.” Explain that these are demo inventory/carrier services.
5. Show both User #2 audit entries.
6. Admin revokes the key; the next external request must fail with 401. Issue/update a replacement privately to continue.

## 4. Controls and failure isolation

Disable Shipping in the dashboard, refresh external and chat catalogs and show its three tools disappear; re-enable and refresh.

For a reproducible pod-deletion outage on the single-node Kind demo, temporarily cordon the node, delete the Shipping pod, refresh tool discovery and the MCP Servers page, and call Inventory. Explain that cordon delays only replacement scheduling; existing unrelated pods remain running. Capture the actual Unreachable badge, not merely the absent tool list. Immediately uncordon even if a check fails, wait for Shipping rollout and verify its tools/calls return.

```bash
kubectl --context kind-urumi-local cordon urumi-local-control-plane
kubectl --context kind-urumi-local delete pod -n urumi -l app=shipping-mcp
# Capture dashboard Unreachable and successful Inventory call now.
kubectl --context kind-urumi-local uncordon urumi-local-control-plane
kubectl --context kind-urumi-local rollout status deployment/shipping-mcp -n urumi --timeout=120s
```

Do not confuse this controlled scheduling delay with a spontaneous long outage; normal replacement may recover too fast to capture. Tool-call audits cover authenticated routed tool calls; authentication rejection and discovery are not tool-call audit rows.

## 5. Multi-store bonus

Create two disposable stores close together; show Provisioning → Ready, separate namespaces, bootstrap Jobs, Secrets names, quotas, PVCs and Ingress hosts. For concurrency capture overlapping Job start/completion times. Do not leave the controller stopped while manually queuing for more than the configured deadline: queued time counts toward timeout.

Create one product in each through chat, manually place orders, then ask “Compare today's orders across these two store prefixes; call each list_orders with today=true and show counts/totals.” IDs may repeat across stores. Show both audit entries.

Run `scripts/verify-store-isolation.sh` in both directions with both stores Ready. Delete only one disposable store in the dashboard. Show namespace/PVs/registration/tools disappear while the surviving store still responds. Preserve the main demo stores.

Explain guardrails and show saved/live evidence: three stores per owner, quota rejection, timeout → Failed → Retry preserving ID, duplicate request returning same ID and conflict returning 409, and completion after provisioner restart. See `current-status.md` for exactly what was verified.

## 6. Internals, tradeoffs and submission

Walk through `gateway.py` (initialize/notification/tools exchange, slug routing, deadlines, audit and eight-round LLM loop), `auth.py`/`secret_store.py` (hashed user keys and encrypted static upstream credentials), and `provisioner.py`/`store_resources.py` (durable reconciliation, advisory locks, ownership, isolation and observed deletion).

Explain shared tool authority: members cannot administer registry/users but can invoke enabled write tools; upstream credentials never need to reach them. Describe untrusted tool descriptions/results, prompt-injection limits, incomplete SSRF defenses and the trusted controller's broad RBAC honestly. Show Helm upgrade/rollback instructions and backup limitations.

Before submission, verify repository clone/build instructions, remove secrets from all frames/files, check video/repo access in a private browser, and submit both links through the assignment form. Recording is not complete until it contains the mandatory real two-user flow, Kubernetes/MCP/security explanation and local-to-VPS story.
