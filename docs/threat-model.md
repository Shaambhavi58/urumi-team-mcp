# Threat model and controls

## Assets

API keys, upstream credentials, WooCommerce customer/order data, product inventory, user roles, and audit events.

## Trust boundaries

External MCP clients and browsers enter through the ingress. The gateway is the only intended caller of upstream MCP Services. The WooCommerce MCP process accesses the store REST API; PostgreSQL and MariaDB hold persistent application/store data.

## Main threats and controls

- **Stolen/replayed API key:** high-entropy one-time keys, SHA-256 hashes at rest, user/key revocation, Bearer authentication on gateway routes. Serve ingress over TLS, avoid logging Authorization headers, and rotate keys after exposure.
- **Member privilege escalation:** role checks on admin routes; each MCP call is attributed to the authenticated user. Re-test admin routes with a member key before a demo.
- **Upstream credential disclosure:** upstream credential JSON is Fernet-encrypted in the registry. `APP_ENCRYPTION_KEY` must be stored in a secret manager and backed up separately; loss of the key makes saved credentials unreadable. Do not use example secrets in a real deployment.
- **Malicious or compromised upstream:** tool calls have an 8-second timeout, failures are sanitized, tools are namespaced by server slug, and services are namespace-internal with an ingress policy allowing gateway-only MCP traffic. Review upstream URLs and network egress policies before allowing admin changes.
- **Audit tampering/data loss:** events are stored in PostgreSQL and returned read-only. Production deployments should forward logs and database backups to a separate protected system and define retention.
- **LLM prompt injection/data exfiltration:** chat tools are restricted to registered MCP tools; never send secrets or unrelated customer data in system prompts. Use least-privilege WooCommerce credentials and review write actions. The demo LLM integration is optional and should be disabled when unused.
- **Secret/volume exposure:** Checked-in credential values are empty; the chart generates or retains database/encryption credentials, and provider/store credentials are supplied through Secrets. Enable encryption at rest for Secrets, RBAC, TLS, restricted ingress, persistent volume backups, and non-default passwords in production.

## Known demo limitations

The sample inventory/shipping services use process memory; use a durable service database for production. The simple dashboard stores the entered key in browser local storage; use a secure session-cookie/OIDC flow for a public production dashboard. The chat client supports an OpenAI-compatible Chat Completions endpoint and permits up to eight model rounds and caps each completion at 512 tokens. Model/provider rate limits can still interrupt a chat.

## Multi-store controller boundary

The gateway never has Kubernetes API credentials. Only the separate worker ServiceAccount can create namespaces and specific application resources. Its RBAC has no pod exec or RBAC mutation, but dynamic namespaces mean core permissions are cluster-wide; a compromised worker is therefore powerful. Code ownership checks protect against accidental namespace adoption/deletion, not against arbitrary controller code execution. Production should enforce the managed namespace boundary with admission policy and restrict network access to the control plane.

Each new store has unique Secret values and encrypted gateway-side upstream bearer credentials. Default-deny ingress/egress plus explicit same-namespace peers prevent a compromised store MCP from accessing a different store's WordPress/database. This requires CNI enforcement. Controller readiness is not proof of that isolation; run the supplied positive/negative checks. Delete-reclaim storage classes and observed namespace/PV deletion implement clean teardown.

Store API ownership controls provisioning/deletion, while MCP tools remain shared with all team members by design. A member can use the WooCommerce read/write authority without seeing its credential; do not describe this as per-store tool authorization. Full order addresses, order keys and metadata are omitted from read responses to reduce LLM exposure. Mutating upstreams still run with shared service authority. Tool descriptions/results are untrusted, and a system prompt instructs the agent not to treat them as instructions; this is a mitigation, not a guarantee against prompt injection.

Registry URLs reject embedded username/password credentials. They are not a complete SSRF defense: authenticated admins can still target reachable internal endpoints. Constrain admin trust and upstream network egress in production. Do not expose arbitrary registration to members.

Client gateway tokens are never forwarded to upstream MCP servers: the gateway authenticates the caller, then supplies only that upstream’s configured static credential. A stolen member key can invoke all enabled team tools, including writes, but cannot administer users/servers, read another user’s private audit list, revoke another user’s keys, or manage another owner’s stores. Members can intentionally or accidentally change shared business data; this prototype has no per-tool approval or permission layer.
