#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CLUSTER_NAME="${1:-urumi-local}"
TAG="${2:-final1}"
docker build -t "urumi-gateway:$TAG" "$ROOT/backend"
docker build -t "urumi-dashboard:$TAG" "$ROOT/dashboard"
docker build -t "urumi-mcp-service:$TAG" "$ROOT/services/mcp-service"
docker build -t "urumi-woocommerce:$TAG" "$ROOT/woocommerce"
kind load docker-image "urumi-gateway:$TAG" "urumi-dashboard:$TAG" "urumi-mcp-service:$TAG" "urumi-woocommerce:$TAG" --name "$CLUSTER_NAME"
