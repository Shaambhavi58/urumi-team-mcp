# Multi-store provisioning

The dashboard writes provisioning requests to PostgreSQL. A separate controller reconciles those records through the Kubernetes API (not shell commands). The gateway itself has no Kubernetes ServiceAccount token. There is one shared gateway; a store does not duplicate it.

## What is implemented

- Stores dashboard: name, status, phase, created time, storefront URL, retry and delete.
- Every store: generated namespace `urumi-store-<id>`, MariaDB deployment and PVC, WordPress deployment and content PVC, create-once Secrets, Ingress, custom WooCommerce MCP deployment.
- ResourceQuota and LimitRange before workloads; configurable owner limit and provisioning deadline. Two stores can progress concurrently by default.
- WordPress Job installs the site, activates bundled WooCommerce, configures INR/COD/free shipping, creates shop/cart/checkout pages and a read/write WooCommerce key. Secrets are never returned by the Stores API.
- Automatic registration uses `store-<id>__tool_name`. Gateway-side encrypted static bearer credentials protect new MCP servers. Only gateway pods are allowed to reach them under NetworkPolicy.
- Existing requests are safe to resume: PostgreSQL advisory locks prevent two controllers reconciling the same store; namespace ownership is checked, Secrets are not regenerated, resources are applied declaratively, completed bootstrap Jobs are reused, registration is an upsert. Failed jobs can be retried with the same stable credentials.
- Deletion disables MCP registration immediately, then requests namespace deletion. Registration and the record are finalized only after the namespace and all referencing PVs are gone. Failed provisioning counts toward quota until deleted. Only Delete-reclaim storage classes are accepted.

## Local update of the existing demo

Do not delete the existing cluster, database PVCs or release. Keep the old project as a rollback source. Extract this bundle into a separate folder.

1. `bash scripts/build-kind-images.sh urumi-local final1`
2. `bash scripts/upgrade-local.sh`
3. Keep the Traefik port forward running: `kubectl --context kind-urumi-local port-forward -n ingress-system service/traefik 8088:80`
4. Open dashboard, connect the existing admin key, choose Stores, create North Store and South Store.
5. Wait for Ready. First bootstrap may take minutes. New hosts use wildcard DNS `shop-<id>.127.0.0.1.nip.io:8088`; they resolve to localhost. If local DNS blocks this, add the exact hosts to `/etc/hosts` with `127.0.0.1`, or change `provisioning.baseDomain` and document it.

`upgrade-local.sh` preserves live Helm storage/credential settings and uses new image tags. It does not recreate the release. It removes temporary values files at exit. Do not paste its intermediate values or any Secret into a chat or commit them.

## Demo

1. In AI Chat identify the two store prefixes and ask it to create a product in each store.
2. Open each storefront and place a COD order manually. Note IDs can repeat across stores; always show store prefix as well.
3. Ask: "Compare today's orders across North Store and South Store. Use each store's list_orders with today=true. Show order IDs, totals and tool names."
4. Verify calls in Audit Log, attributed to the logged-in user.
5. Run `bash scripts/verify-store-isolation.sh <north-namespace> <south-namespace>` and repeat in reverse. Both target deployments must be Ready. Verify own-store WordPress access and cross-store WordPress/database denial.
6. Delete one disposable store in the dashboard. This permanently deletes its orders/content. Observe Deleting then disappearance. Refresh gateway tools in dashboard and external client: its prefix must disappear.
7. `kubectl get ns,pv` and confirm the deleted namespace and its PVs are gone. The other storefront and tools must still work.
8. Recovery: create a disposable store and restart `deployment/provisioner` during provisioning; it must finish once or show a safe failure reason. Retry uses the same namespace and secrets.

## NetworkPolicy is a deployment prerequisite

Policy objects alone do not prove enforcement. Default Kind networking may not enforce NetworkPolicies. Run the isolation test before claiming the bonus is complete. Install a compatible policy engine if it fails; do not delete the existing data to change CNI. Calico supports policy-only installations alongside compatible networking: consult https://docs.tigera.io/calico/latest/getting-started/kubernetes/helm and select a version compatible with the cluster. k3s normally includes a network-policy controller unless explicitly disabled; still run the tests there.

## Operations

- `kubectl logs -n urumi deployment/provisioner --tail=100`
- `kubectl get pods,jobs,pvc,ingress,networkpolicy,resourcequota,limitrange -n <store-namespace>`
- `kubectl logs -n <store-namespace> job/bootstrap`
- Owner API: POST /stores `{name, request_id}` (stable UUID for retries), GET /stores, POST /stores/{id}/retry, DELETE /stores/{id}.
- Admin sees all stores; member sees/manages their own. Tool access is team-wide, as in the base assignment; provisioning ownership is not per-store tool authorization.
- A namespace stuck Terminating remains Deleting. Inspect finalizers/storage provisioner; do not force-remove finalizers to fake cleanup.
- The bootstrap Job has a finite lifetime and reports failures. Readiness does not prove public DNS/Ingress reachability: test the storefront manually.

## Privilege boundary and limitations

The controller needs namespace create/delete and selected namespaced resource permissions cluster-wide because namespaces are dynamic. Kubernetes RBAC cannot constrain those verbs by a name prefix. Controller code checks ownership before every namespace mutation. This is a trusted control-plane component, not tenant code. A compromised controller can still affect other namespaces; production should add admission policies restricting its ServiceAccount to managed store namespaces. No cluster-admin role, pod exec, RBAC mutation or host access is granted.

The controller checks Delete reclaim policy and waits for PV deletion; storage backend failures can delay teardown. WordPress is the official Apache image and starts with its normal entrypoint permissions. Database and content are persistent; inventory/shipping demo data remain in memory. There is no per-store login/password UI: WordPress admin credentials are in the store Secret and are available only to cluster operators.

Local-only unit/mocked tests do not replace the live create/checkout/compare/isolation/delete/recovery demonstration. See `current-status.md` for completed live checks and remaining submission limitations.

The 900-second provisioning deadline begins at request creation (or Retry), so time spent queued while the worker is stopped also counts. This bounds total request latency and avoids indefinitely queued requests. Retry resets the attempt deadline.
