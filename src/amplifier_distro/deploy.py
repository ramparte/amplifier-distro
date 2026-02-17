"""Cloud deployment configuration for Amplifier Distro.

Defines deploy targets (local Docker, GCP, AWS, Azure) with the
container registry, runtime command, required environment variables,
and cloud-specific configuration each target needs.

This is foundational groundwork — the config structure that makes
multi-cloud deployment possible. Actual deploy scripts come later.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from textwrap import dedent

from amplifier_distro.conventions import SERVER_DEFAULT_PORT


@dataclass(frozen=True)
class DeployTarget:
    id: str
    name: str
    description: str
    container_registry: str
    container_command: list[str]
    env_vars_needed: list[str]
    estimated_cost: str
    cloud_config: dict[str, str | int | float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
#  Targets
# ---------------------------------------------------------------------------

DEPLOY_TARGETS: dict[str, DeployTarget] = {
    "local": DeployTarget(
        id="local",
        name="Local Docker",
        description="Run locally with Docker — no cloud account needed",
        container_registry="local",
        container_command=[
            "uvicorn",
            "amplifier_distro.server:app",
            "--host",
            "0.0.0.0",
            "--port",
            str(SERVER_DEFAULT_PORT),
        ],
        env_vars_needed=["ANTHROPIC_API_KEY"],
        estimated_cost="Free",
        cloud_config={
            "memory_mb": 512,
            "cpu": 1,
            "port": SERVER_DEFAULT_PORT,
        },
    ),
    "gcp": DeployTarget(
        id="gcp",
        name="Google Cloud Run",
        description="Serverless containers on GCP — scales to zero",
        container_registry="gcr.io/{project_id}/amplifier-distro",
        container_command=[
            "uvicorn",
            "amplifier_distro.server:app",
            "--host",
            "0.0.0.0",
            "--port",
            str(SERVER_DEFAULT_PORT),
        ],
        env_vars_needed=[
            "ANTHROPIC_API_KEY",
            "GCP_PROJECT_ID",
        ],
        estimated_cost="~$0 at low usage (scales to zero)",
        cloud_config={
            "memory_mb": 512,
            "cpu": 1,
            "port": SERVER_DEFAULT_PORT,
            "max_instances": 3,
            "min_instances": 0,
            "timeout_seconds": 300,
        },
    ),
    "aws": DeployTarget(
        id="aws",
        name="AWS App Runner",
        description="Managed containers on AWS — simple deploy from image",
        container_registry="{account_id}.dkr.ecr.{region}.amazonaws.com/amplifier-distro",
        container_command=[
            "uvicorn",
            "amplifier_distro.server:app",
            "--host",
            "0.0.0.0",
            "--port",
            str(SERVER_DEFAULT_PORT),
        ],
        env_vars_needed=[
            "ANTHROPIC_API_KEY",
            "AWS_REGION",
        ],
        estimated_cost="~$5/mo minimum (1 vCPU, 2 GB)",
        cloud_config={
            "memory_mb": 2048,
            "cpu": 1,
            "port": SERVER_DEFAULT_PORT,
            "max_instances": 3,
            "min_instances": 1,
        },
    ),
    "azure": DeployTarget(
        id="azure",
        name="Azure Container Apps",
        description="Serverless containers on Azure — scales to zero",
        container_registry="{registry_name}.azurecr.io/amplifier-distro",
        container_command=[
            "uvicorn",
            "amplifier_distro.server:app",
            "--host",
            "0.0.0.0",
            "--port",
            str(SERVER_DEFAULT_PORT),
        ],
        env_vars_needed=[
            "ANTHROPIC_API_KEY",
            "AZURE_RESOURCE_GROUP",
        ],
        estimated_cost="~$0 at low usage (scales to zero)",
        cloud_config={
            "memory_gb": 1,
            "cpu": 0.5,
            "port": SERVER_DEFAULT_PORT,
            "max_replicas": 3,
            "min_replicas": 0,
        },
    ),
}


# ---------------------------------------------------------------------------
#  Generators
# ---------------------------------------------------------------------------


def generate_dockerfile(target_id: str) -> str:
    """Generate a production Dockerfile for the given deploy target.

    Returns the Dockerfile content as a string.
    """
    if target_id not in DEPLOY_TARGETS:
        msg = f"Unknown deploy target: {target_id}"
        raise ValueError(msg)

    target = DEPLOY_TARGETS[target_id]
    port = target.cloud_config.get("port", SERVER_DEFAULT_PORT)
    cmd_json = ", ".join(f'"{c}"' for c in target.container_command)

    return dedent(f"""\
        # ---- Build stage ----
        FROM python:3.12-slim AS builder

        WORKDIR /build
        COPY pyproject.toml .
        COPY src/ src/

        RUN pip install --no-cache-dir --prefix=/install .

        # ---- Runtime stage ----
        FROM python:3.12-slim

        COPY --from=builder /install /usr/local
        COPY src/ /app/src/

        WORKDIR /app
        ENV PYTHONPATH=/app/src
        EXPOSE {port}

        CMD [{cmd_json}]
    """)


def generate_deploy_config(target_id: str) -> str:
    """Generate cloud-specific deployment config for the given target.

    Returns YAML/JSON config as a string.
    """
    if target_id not in DEPLOY_TARGETS:
        msg = f"Unknown deploy target: {target_id}"
        raise ValueError(msg)

    target = DEPLOY_TARGETS[target_id]

    if target_id == "local":
        return _generate_docker_compose(target)
    if target_id == "gcp":
        return _generate_cloud_run_yaml(target)
    if target_id == "aws":
        return _generate_apprunner_yaml(target)
    if target_id == "azure":
        return _generate_container_apps_yaml(target)

    msg = f"No config generator for target: {target_id}"
    raise ValueError(msg)


# ---------------------------------------------------------------------------
#  Private helpers
# ---------------------------------------------------------------------------


def _generate_docker_compose(target: DeployTarget) -> str:
    port = target.cloud_config.get("port", SERVER_DEFAULT_PORT)
    env_lines = "\n".join(
        f"      - {var}=${{{{{{var}}}}}}" for var in target.env_vars_needed
    )
    return dedent(f"""\
        # docker-compose.yaml — Local Amplifier Distro
        version: "3.9"
        services:
          amplifier:
            build:
              context: .
              dockerfile: Dockerfile
            ports:
              - "{port}:{port}"
            environment:
        {env_lines}
    """)


def _generate_cloud_run_yaml(target: DeployTarget) -> str:
    cfg = target.cloud_config
    return dedent(f"""\
        # cloud-run-service.yaml — GCP Cloud Run
        apiVersion: serving.knative.dev/v1
        kind: Service
        metadata:
          name: amplifier-distro
        spec:
          template:
            metadata:
              annotations:
                autoscaling.knative.dev/minScale: "{cfg.get("min_instances", 0)}"
                autoscaling.knative.dev/maxScale: "{cfg.get("max_instances", 3)}"
            spec:
              containerConcurrency: 80
              timeoutSeconds: {cfg.get("timeout_seconds", 300)}
              containers:
                - image: gcr.io/PROJECT_ID/amplifier-distro:latest
                  ports:
                    - containerPort: {cfg.get("port", SERVER_DEFAULT_PORT)}
                  resources:
                    limits:
                      memory: {cfg.get("memory_mb", 512)}Mi
                      cpu: "{cfg.get("cpu", 1)}"
    """)


def _generate_apprunner_yaml(target: DeployTarget) -> str:
    cfg = target.cloud_config
    port = cfg.get("port", SERVER_DEFAULT_PORT)
    return dedent(f"""\
        # apprunner.yaml — AWS App Runner
        version: 1.0
        runtime: python312
        build:
          commands:
            build:
              - pip install .
        run:
          command: >-
            uvicorn amplifier_distro.server:app
            --host 0.0.0.0 --port {port}
          network:
            port: {port}
        instance:
          cpu: {cfg.get("cpu", 1)}
          memory: {cfg.get("memory_mb", 2048)}
          max: {cfg.get("max_instances", 3)}
          min: {cfg.get("min_instances", 1)}
    """)


def _generate_container_apps_yaml(target: DeployTarget) -> str:
    cfg = target.cloud_config
    return dedent(f"""\
        # container-app.yaml — Azure Container Apps
        properties:
          configuration:
            ingress:
              targetPort: {cfg.get("port", SERVER_DEFAULT_PORT)}
              external: true
          template:
            containers:
              - name: amplifier-distro
                image: REGISTRY.azurecr.io/amplifier-distro:latest
                resources:
                  cpu: {cfg.get("cpu", 0.5)}
                  memory: {cfg.get("memory_gb", 1)}Gi
            scale:
              minReplicas: {cfg.get("min_replicas", 0)}
              maxReplicas: {cfg.get("max_replicas", 3)}
    """)
