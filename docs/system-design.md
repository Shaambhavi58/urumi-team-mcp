# System design and tradeoffs

## Components and routing

Ingress -> dashboard Nginx -> FastAPI gateway -> enabled MCP upstream -> WooCommerce REST API -> MariaDB. Browser/client credentials terminate at the gateway. Upstream credentials are decrypted only for server-side calls. Chat uses an OpenAI-compatible LLM endpoint; every selected tool returns through the gateway with the user's token. The controller never calls upstream MCP tools.

Tools use `slug__name`, preventing collisions across servers. New store tools use generated store IDs, so repeated product/order IDs cannot be mistaken for the same store. Discovery runs concurrently, with bounded upstream HTTP timeouts. Calls are additionally wrapped in an overall deadline. Each upstream call negotiates MCP initialization, sends the initialized notification, then requests tools or executes a tool; optional upstream session IDs are retained within that exchange and closed afterwards. JSON and buffered SSE responses are supported. Persistent upstream SSE notifications, unsolicited sampling and long-lived session resumption are not implemented.

The gateway itself is stateless for MCP: JSON replies, no allocated client session. Unknown methods return JSON-RPC errors; initialized notifications return 202. Upstream list failures omit that server's tools and mark it unavailable; errors on one server do not remove other servers. Registry status updates on discovery/calls, not a separate background health monitor. External clients must refresh tool lists after registry changes.

## Persistence and provisioning

PostgreSQL contains API users/hashed keys, encrypted static credentials, registry/audit rows and durable store requests. Stores use independent namespaces, database and content volumes, Secrets and Ingress. The reconciler uses PostgreSQL advisory locks and server-side apply. Its resource definitions are in `backend/app/store_resources.py`; the shared Helm chart deploys the platform/controller configuration in local and production environments. Dynamic resources are generated through the Kubernetes API, an allowed bonus provisioning option.

Records progress through Provisioning -> Ready/Failed and Deleting -> Deleted. Retries preserve namespace/credentials; deletion wins over registration races. Bootstrap runs in a retry-safe Job. Owner quota changes are serialized with a user row lock. Concurrency/deadline/owner limits are values-driven. Deletion waits for namespace/PV absence rather than treating a delete request as completion.

## Intentional choices and limits

- WooCommerce REST API keeps store authorization/business rules in WooCommerce. Internal HTTP uses OAuth1 HMAC-SHA256 signing against WordPress's canonical public URL, while routing to the internal Service. Bonus stores use `rest_route` query routing to avoid Apache rewrite dependencies; the route participates in the signature. HTTPS uses basic authentication over TLS.
- Dedicated worker separates Kubernetes privilege from the public gateway. Dynamic namespace operations require broad controller RBAC; admission restriction is recommended before multi-tenant production.
- NetworkPolicy denies store traffic by default, permits MCP only from gateway and MCP egress only to its own WordPress/DNS. A NetworkPolicy-capable CNI is required and must be tested.
- One gateway replica is the tested reference topology. Sessionless design supports independent requests, but scaling/load/rate limits are not demonstrated.
- Inventory/Shipping are demonstrative independent MCP sources, not real stock/carrier integrations. Their mutable data is process-local.
- Team membership grants access to enabled tools, including mutations with shared store authority. Per-tool permissions are a separate optional enhancement.
- The database uses additive schema creation for this prototype. Production upgrades need migrations, backups and compatibility testing.

## Local to VPS

Same Helm chart; configure images, domains, ingress, provider model/base URL, Secrets, storage class and controller domain/limits. Local Mac uses Traefik port-forward + hosts entries and wildcard loopback store DNS. VPS uses public DNS and port 80/443, no port-forward. Use TLS, encrypted disks/etcd secrets, monitoring and storage backups in production. See README for upgrade/rollback behavior.
