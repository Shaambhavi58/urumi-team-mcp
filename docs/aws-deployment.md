# AWS deployment verification

Deployed on AWS EC2 using Ubuntu, single-node k3s and the same
Helm chart used for the local Kind deployment.

## Configuration

Use values-k3s.yaml followed by values-aws-demo.yaml.
The AWS override contains no credentials.

- Ingress: Traefik.
- Storage: local-path persistent volumes.
- TLS: cert-manager with a Let's Encrypt ClusterIssuer.
- Certificate Secret: urumi-public-tls.
- WooCommerce credential Secret: urumi-woo.
- LLM credential Secret: urumi-llm.
- Application images are built for amd64 and imported into k3s.
- IfNotPresent uses these preloaded images; additional nodes require
  image distribution or a container registry.

Create the referenced Secrets and TLS certificate before installing
with this configuration. Never commit their values.

Example after those prerequisites and image imports:

```bash
helm upgrade --install urumi-gateway ./charts/urumi-gateway \
  --namespace urumi --create-namespace \
  -f charts/urumi-gateway/values-k3s.yaml \
  -f charts/urumi-gateway/values-aws-demo.yaml \
  --wait --timeout=10m

The first WooCommerce store was configured through WordPress admin:
WooCommerce activation, read/write REST credentials, COD enabled and
site visibility set to Live.
Verified on 26 October 2026
- Dashboard and storefront accessible through HTTPS.
- Dashboard agent created WooCommerce products.
- Manual COD checkout created order 15 for INR 349.
- Order 15 visible in WooCommerce admin and dashboard chat.
- External Cursor member retrieved the same order.
- One Cursor prompt called Inventory and Shipping successfully.
- Those member calls appeared as SUCCESS in the audit log.
The MCP service preserves the public Host and forwarded scheme when
calling WordPress internally so WooCommerce OAuth signatures match.
Limits
This is a single-node production-like demonstration, not an HA setup.
The EC2 public IP can change after stopping and starting the instance.
DNS and certificates must be updated if it changes.

Multi-store provisioning, isolation, teardown, concurrency and recovery
were verified locally; equivalent AWS bonus checks are not claimed.
Dynamic store HTTPS is not configured by this override.

Helm rollback restores release resources, not database contents.
Back up persistent data before changes requiring data migration.
