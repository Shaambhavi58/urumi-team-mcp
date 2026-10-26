"""Kubernetes resources for one store; no shared database or cross-store access."""

import os
from urllib.parse import urlparse


def env_secret(name, key=None):
    return {
        "name": name,
        "valueFrom": {"secretKeyRef": {"name": "store-secrets", "key": key or name}},
    }


def resources(store):
    ns = store.namespace

    def obj(kind, name, spec, api="v1"):
        return {
            "apiVersion": api,
            "kind": kind,
            "metadata": {"name": name, "namespace": ns},
            "spec": spec,
        }

    def peer(app, namespace=None):
        p = {"podSelector": {"matchLabels": {"app": app}}}
        if namespace:
            p["namespaceSelector"] = {"matchLabels": {"kubernetes.io/metadata.name": namespace}}
        return p

    def policy(name, app, incoming, outgoing):
        return obj(
            "NetworkPolicy",
            name,
            {
                "podSelector": {"matchLabels": {"app": app}} if app else {},
                "policyTypes": ["Ingress", "Egress"],
                "ingress": incoming,
                "egress": outgoing,
            },
            "networking.k8s.io/v1",
        )

    def port(p, protocol="TCP"):
        return {"port": p, "protocol": protocol}

    dns = {
        "to": [
            {
                "namespaceSelector": {
                    "matchLabels": {"kubernetes.io/metadata.name": "kube-system"}
                },
                "podSelector": {"matchLabels": {"k8s-app": "kube-dns"}},
            }
        ],
        "ports": [port(53), port(53, "UDP")],
    }
    wp_image = os.environ["STORE_WORDPRESS_IMAGE"]
    mcp_image = os.environ["STORE_MCP_IMAGE"]
    pull = os.getenv("STORE_IMAGE_PULL_POLICY", "IfNotPresent")
    gateway_ns = os.getenv("GATEWAY_NAMESPACE", "urumi")
    ingress_ns = os.getenv("INGRESS_NAMESPACE", "ingress-system")
    wp_env = [
        {"name": "WORDPRESS_DB_HOST", "value": "database:3306"},
        {"name": "WORDPRESS_DB_NAME", "value": "wordpress"},
        {"name": "WORDPRESS_DB_USER", "value": "wp"},
        env_secret("WORDPRESS_DB_PASSWORD", "DB_PASSWORD"),
        {"name": "WORDPRESS_CONFIG_EXTRA", "value": "define('DISABLE_WP_CRON', true);"},
    ]
    limits = {
        "requests": {"cpu": "100m", "memory": "128Mi"},
        "limits": {"cpu": "700m", "memory": "512Mi"},
    }
    yield obj(
        "ResourceQuota",
        "store-budget",
        {
            "hard": {
                "requests.cpu": "2",
                "limits.cpu": "4",
                "requests.memory": "2Gi",
                "limits.memory": "4Gi",
                "persistentvolumeclaims": "3",
                "requests.storage": "8Gi",
                "pods": "8",
                "services": "4",
                "secrets": "4",
            }
        },
    )
    yield obj(
        "LimitRange",
        "store-defaults",
        {
            "limits": [
                {
                    "type": "Container",
                    "defaultRequest": {"cpu": "100m", "memory": "128Mi"},
                    "default": {"cpu": "700m", "memory": "512Mi"},
                    "max": {"cpu": "2", "memory": "1Gi"},
                }
            ]
        },
    )
    yield policy("default-deny", None, [], [])
    yield policy(
        "database-only-wordpress",
        "database",
        [{"from": [peer("wordpress"), peer("bootstrap")], "ports": [port(3306)]}],
        [],
    )
    yield policy(
        "wordpress-access",
        "wordpress",
        [
            {
                "from": [
                    peer("mcp"),
                    {
                        "namespaceSelector": {
                            "matchLabels": {"kubernetes.io/metadata.name": ingress_ns}
                        }
                    },
                ],
                "ports": [port(80)],
            }
        ],
        [dns, {"to": [peer("database")], "ports": [port(3306)]}],
    )
    yield policy(
        "bootstrap-access",
        "bootstrap",
        [],
        [dns, {"to": [peer("database")], "ports": [port(3306)]}],
    )
    yield policy(
        "mcp-only-gateway",
        "mcp",
        [{"from": [peer("gateway", gateway_ns)], "ports": [port(8010)]}],
        [dns, {"to": [peer("wordpress")], "ports": [port(80)]}],
    )
    storage = os.getenv("STORE_STORAGE_CLASS", "")
    for name in ("database", "content"):
        spec = {"accessModes": ["ReadWriteOnce"], "resources": {"requests": {"storage": "2Gi"}}}
        if storage:
            spec["storageClassName"] = storage
        yield obj("PersistentVolumeClaim", name, spec)
    for app, service_port in (("database", 3306), ("wordpress", 80), ("mcp", 8010)):
        yield obj(
            "Service",
            app,
            {
                "type": "ClusterIP",
                "selector": {"app": app},
                "ports": [{"port": service_port, "targetPort": service_port}],
            },
        )

    def deployment(app, container, volumes=None):
        return obj(
            "Deployment",
            app,
            {
                "replicas": 1,
                "strategy": {"type": "Recreate"},
                "selector": {"matchLabels": {"app": app}},
                "template": {
                    "metadata": {"labels": {"app": app}},
                    "spec": {
                        "automountServiceAccountToken": False,
                        "containers": [container],
                        "volumes": volumes or [],
                    },
                },
            },
            "apps/v1",
        )

    db_probe = {
        "exec": {"command": ["healthcheck.sh", "--connect", "--innodb_initialized"]},
        "timeoutSeconds": 5,
        "periodSeconds": 10,
    }
    yield deployment(
        "database",
        {
            "name": "database",
            "image": os.getenv("STORE_DB_IMAGE", "mariadb:11.4"),
            "imagePullPolicy": pull,
            "env": [
                {"name": "MARIADB_DATABASE", "value": "wordpress"},
                {"name": "MARIADB_USER", "value": "wp"},
                env_secret("MARIADB_PASSWORD", "DB_PASSWORD"),
                env_secret("MARIADB_ROOT_PASSWORD", "DB_ROOT_PASSWORD"),
            ],
            "resources": limits,
            "startupProbe": {**db_probe, "failureThreshold": 30},
            "readinessProbe": db_probe,
            "livenessProbe": {**db_probe, "failureThreshold": 6},
            "volumeMounts": [{"name": "data", "mountPath": "/var/lib/mysql"}],
        },
        [{"name": "data", "persistentVolumeClaim": {"claimName": "database"}}],
    )
    wp_probe = {
        "httpGet": {"path": "/wp-login.php", "port": 80},
        "timeoutSeconds": 10,
        "periodSeconds": 10,
    }
    yield deployment(
        "wordpress",
        {
            "name": "wordpress",
            "image": wp_image,
            "imagePullPolicy": pull,
            "env": wp_env,
            "resources": limits,
            "startupProbe": {**wp_probe, "failureThreshold": 30},
            "readinessProbe": wp_probe,
            "livenessProbe": {"tcpSocket": {"port": 80}, "timeoutSeconds": 3, "periodSeconds": 20},
            "volumeMounts": [{"name": "content", "mountPath": "/var/www/html/wp-content"}],
        },
        [{"name": "content", "persistentVolumeClaim": {"claimName": "content"}}],
    )
    mcp_probe = {
        "httpGet": {"path": "/health/live", "port": 8010},
        "timeoutSeconds": 3,
        "periodSeconds": 10,
    }
    yield deployment(
        "mcp",
        {
            "name": "mcp",
            "image": mcp_image,
            "imagePullPolicy": pull,
            "env": [
                {"name": "SERVICE_NAME", "value": "woocommerce"},
                {"name": "WOO_URL", "value": "http://wordpress"},
                {"name": "WOO_PUBLIC_URL", "value": store.url},
                {"name": "WOO_QUERY_ROUTE", "value": "true"},
                env_secret("WOO_CONSUMER_KEY"),
                env_secret("WOO_CONSUMER_SECRET"),
                env_secret("MCP_AUTH_TOKEN"),
            ],
            "resources": limits,
            "readinessProbe": mcp_probe,
            "livenessProbe": mcp_probe,
            "securityContext": {
                "runAsNonRoot": True,
                "runAsUser": 10001,
                "allowPrivilegeEscalation": False,
                "capabilities": {"drop": ["ALL"]},
            },
        },
    )
    yield obj(
        "Ingress",
        "store",
        {
            "ingressClassName": os.getenv("STORE_INGRESS_CLASS", "traefik"),
            "rules": [
                {
                    "host": urlparse(store.url).hostname,
                    "http": {
                        "paths": [
                            {
                                "path": "/",
                                "pathType": "Prefix",
                                "backend": {
                                    "service": {"name": "wordpress", "port": {"number": 80}}
                                },
                            }
                        ]
                    },
                }
            ],
        },
        "networking.k8s.io/v1",
    )


def bootstrap_job(store):
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {"name": "bootstrap", "namespace": store.namespace},
        "spec": {
            "backoffLimit": 4,
            "activeDeadlineSeconds": 600,
            "template": {
                "metadata": {"labels": {"app": "bootstrap"}},
                "spec": {
                    "restartPolicy": "OnFailure",
                    "automountServiceAccountToken": False,
                    "containers": [
                        {
                            "name": "bootstrap",
                            "image": os.environ["STORE_WORDPRESS_IMAGE"],
                            "imagePullPolicy": os.getenv("STORE_IMAGE_PULL_POLICY", "IfNotPresent"),
                            "command": [
                                "bash",
                                "-ec",
                                "cp -a /usr/src/wordpress /tmp/site; rm -rf /tmp/site/wp-content; ln -s /content /tmp/site/wp-content; cd /tmp/site; php /usr/local/bin/urumi-bootstrap.php",
                            ],
                            "env": [
                                {"name": "STORE_URL", "value": store.url},
                                {"name": "STORE_TITLE", "value": store.name},
                                *[
                                    env_secret(k)
                                    for k in (
                                        "DB_PASSWORD",
                                        "ADMIN_PASSWORD",
                                        "WOO_CONSUMER_KEY",
                                        "WOO_CONSUMER_SECRET",
                                    )
                                ],
                            ],
                            "resources": {
                                "requests": {"cpu": "100m", "memory": "128Mi"},
                                "limits": {"cpu": "700m", "memory": "512Mi"},
                            },
                            "volumeMounts": [{"name": "content", "mountPath": "/content"}],
                        }
                    ],
                    "volumes": [
                        {"name": "content", "persistentVolumeClaim": {"claimName": "content"}}
                    ],
                },
            },
        },
    }
