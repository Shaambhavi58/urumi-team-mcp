#!/usr/bin/env bash
set -euo pipefail
if [[ $# != 2 ]]; then echo 'Usage: verify-store-isolation.sh <store-a-namespace> <store-b-namespace>' >&2; exit 2; fi
for STORE_NS in "$1" "$2"; do
  if [[ ! "$STORE_NS" =~ ^urumi-store-[a-f0-9]{12}$ ]]; then echo 'Invalid store namespace' >&2; exit 2; fi
done
for STORE_NS in "$1" "$2"; do
  kubectl --context "${KUBE_CONTEXT:-kind-urumi-local}" wait -n "$STORE_NS" --for=condition=Available deployment/wordpress deployment/database deployment/mcp --timeout=120s
done
kubectl --context "${KUBE_CONTEXT:-kind-urumi-local}" exec -n "$1" deployment/mcp -- python -c '
import socket,sys,httpx
other=sys.argv[1]
r=httpx.get("http://wordpress/wp-login.php",timeout=10)
assert r.status_code < 400, "Own WordPress must remain reachable"
print("PASS: own WordPress reachable")
for host,port in [("wordpress."+other+".svc.cluster.local",80),("database."+other+".svc.cluster.local",3306),("database",3306)]:
    try:
        s=socket.create_connection((host,port),timeout=3)
    except socket.gaierror:
        raise SystemExit("FAIL: DNS did not resolve; this does not prove isolation")
    except (TimeoutError,ConnectionRefusedError):
        print("BLOCKED:",host,port)
    else:
        s.close()
        raise SystemExit("FAIL: forbidden connection succeeded; install a NetworkPolicy-capable CNI")
print("PASS: forbidden destinations blocked. Confirm both destination workloads are Ready before recording this evidence.")
' "$2"
