# Verification status — 26 October 2026

Evidence below was observed in the user's running Kind cluster and supplied terminal/UI outputs. It is not a claim that the review environment ran Kubernetes, Docker or a VPS.

## Core live checks

- Real WooCommerce products, product images, COD checkout and orders demonstrated. Dashboard AI created products and read the resulting orders.
- Cursor connected with only gateway URL and member API key. It retrieved Store A order 14 (processing, INR 799) on 25 October, and one prompt called Inventory and Shipping. Correct User #2 attribution appeared in Audit Log.
- Admin key issuance/revocation and rejected next request were demonstrated. Member generated a new key in My API Keys and used it successfully for SKU-MUG stock.
- Shipping disable removed its tools from external discovery and chat; re-enable restored them.
- Shipping pod was deleted. The single node was temporarily cordoned to hold the replacement Pending, keeping a reproducible outage window. During that window Inventory returned 60 and Shipping tools were absent. Node uncordoned and replacement rollout completed; Shipping subsequently showed Ready with all three tools. The specific Unreachable badge was demonstrated in an earlier scale-to-zero check, but not captured during this pod-deletion window. Do not label those as the same observation.
- Core probes/resources, stable Ingress URLs, persistent database/content and Helm deployment are in use.
- Proxy Swagger UI successfully executed `/api/health/live` with HTTP 200 after the relative-URL fix.

## Bonus live checks

- Store A and Store B provisioned with independent namespaces/databases/content/Secrets/Ingress and automatic store-prefixed MCP registration. AI created a T-shirt in A and mug in B, followed by manual COD orders.
- AI compared 25 October orders across both stores: one each, INR 799 + INR 349 = INR 1,148. Order ID 14 was valid independently in both stores.
- Isolation script passed in both directions while destination workloads were Ready: own WordPress reachable, cross-store WordPress/database blocked.
- Store B deletion removed its namespace and PVs, removed its tools and retained Store A's successful order access. Disposable test stores were subsequently deleted too.
- Recovery Demo became usable after a provisioner rolling restart during provisioning. This demonstrates eventual completion across that restart, not a forced process crash at a precisely instrumented step.
- ResourceQuota and LimitRange observed; server-side dry-run pod creation exceeding CPU quota was rejected. No quota-check pod was created.
- Fourth store request rejected with the configured three-store-per-user limit.
- Repeated identical POST request ID returned the same store ID/namespace/creation time; same ID with another name returned HTTP 409.
- Temporarily setting only the worker's timeout to one second produced a clear Failed state. Removing the override restored the 900-second ConfigMap deadline; Retry preserved store ID and reached Ready. The test store was deleted.
- Concurrent A and B accepted together and provisioned successfully. Both bootstrap Jobs ran from 2026-10-26T13:04:23Z to 13:04:28Z; all three deployments in each store were Ready. Both disposable stores were deleted.

## Automated/build checks

- 19 Python unit/mocked tests passed in review and again on the Mac after the docs fix. Review backend lint and shell/Python syntax checks passed.
- Both bonus and k3s Helm lint commands passed on the Mac.
- Vite upgraded to 6.4.5; npm audit reported zero vulnerabilities at that check; production build passed.
- Gateway/dashboard `final1` images built, loaded into Kind and deployed as Helm revision 17. Original MCP image remains the previously tested `images2`; image labels do not change the source snapshot.
- Checked credential fields in values files are empty. A source-pattern scan found no raw gateway/WooCommerce/Groq/OpenAI key patterns or private-key headers in the supplied archive. This is a scoped scan, not a guarantee that arbitrary secrets are absent or that prior exposed credentials are revoked.

## Remaining submission work and limits

- Rotate exposed gateway keys; verify fresh connections before revoking their predecessors. Do not rotate the application encryption key as a substitute: it protects stored upstream credentials.
- Record the required complete live two-user demo and explanatory walkthrough, publish the reviewed repository, and submit video/repository links through the assignment form.
- Inventory/Shipping are demo services with process-memory state; they do not synchronize WooCommerce stock or contact a real carrier.
- Actual VPS deployment, load testing, gateway OAuth, per-tool authorization, rate limiting and complete SSRF protection are not claimed.
- Dynamic provisioning controller has broad cross-namespace application-resource authority; ownership checks are not a security boundary against a compromised controller.

## Final live verification — 26 October 2026

- Dashboard refresh now fetches server status after tool discovery.
- After Shipping pod deletion, Shipping showed UNAVAILABLE with no tools; other upstreams remained READY.
- During the outage, Inventory returned SKU-MUG availability 60 successfully.
- After uncordoning, Shipping rolled out and returned to READY with all three tools.
- Dashboard fix deployed as Helm revision 18, image urumi-dashboard:statusfix1.
- Admin and member replacement keys were tested; exposed predecessor keys were revoked.
