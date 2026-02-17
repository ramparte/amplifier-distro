"""Deploy Configuration Tests

Validates the deploy target data structures and generator functions
used for multi-cloud deployment groundwork.

Exit criteria verified:
1. DEPLOY_TARGETS has all four entries (local, gcp, aws, azure)
2. Each target is a DeployTarget with required fields
3. generate_dockerfile() returns valid Dockerfile content
4. generate_deploy_config() returns cloud-specific config
5. Invalid target IDs raise ValueError
6. Dockerfile has HEALTHCHECK, non-root USER, exec-form CMD
7. docker-entrypoint.sh exists and is executable
"""

import stat
from pathlib import Path

import pytest

from amplifier_distro.conventions import SERVER_DEFAULT_PORT
from amplifier_distro.deploy import (
    DEPLOY_TARGETS,
    DeployTarget,
    generate_deploy_config,
    generate_dockerfile,
)


class TestDeployTargets:
    """Verify DEPLOY_TARGETS dict has correct entries and structure."""

    EXPECTED_IDS = {"local", "gcp", "aws", "azure"}

    def test_has_all_expected_targets(self):
        assert set(DEPLOY_TARGETS.keys()) == self.EXPECTED_IDS

    def test_count_is_four(self):
        assert len(DEPLOY_TARGETS) == 4

    def test_each_target_is_deploy_target_type(self):
        for tid, target in DEPLOY_TARGETS.items():
            assert isinstance(target, DeployTarget), f"{tid} should be DeployTarget"

    def test_each_target_has_required_fields(self):
        for tid, target in DEPLOY_TARGETS.items():
            assert isinstance(target.id, str) and target.id == tid
            assert isinstance(target.name, str) and len(target.name) > 0
            assert isinstance(target.description, str) and len(target.description) > 0
            assert isinstance(target.container_registry, str)
            assert isinstance(target.container_command, list)
            assert len(target.container_command) > 0
            assert isinstance(target.env_vars_needed, list)
            assert len(target.env_vars_needed) > 0
            assert isinstance(target.estimated_cost, str)
            assert isinstance(target.cloud_config, dict)

    def test_all_targets_need_api_key(self):
        """Every target should require at least one API key."""
        for tid, target in DEPLOY_TARGETS.items():
            assert "ANTHROPIC_API_KEY" in target.env_vars_needed, (
                f"{tid} should require ANTHROPIC_API_KEY"
            )

    def test_local_target_is_free(self):
        assert "Free" in DEPLOY_TARGETS["local"].estimated_cost

    def test_each_target_has_port_in_config(self):
        for tid, target in DEPLOY_TARGETS.items():
            assert "port" in target.cloud_config, (
                f"{tid} cloud_config should include port"
            )
            assert target.cloud_config["port"] == SERVER_DEFAULT_PORT

    def test_targets_are_frozen(self):
        """DeployTarget is frozen — no accidental mutation."""
        with pytest.raises(AttributeError):
            DEPLOY_TARGETS["local"].name = "Changed"  # type: ignore[misc]


class TestGenerateDockerfile:
    """Verify generate_dockerfile() produces valid Dockerfile content."""

    def test_local_dockerfile(self):
        result = generate_dockerfile("local")
        assert "FROM python:3.12-slim" in result
        assert "EXPOSE" in result
        assert "CMD" in result

    def test_gcp_dockerfile(self):
        result = generate_dockerfile("gcp")
        assert "FROM python:3.12-slim" in result

    def test_aws_dockerfile(self):
        result = generate_dockerfile("aws")
        assert "FROM python:3.12-slim" in result

    def test_azure_dockerfile(self):
        result = generate_dockerfile("azure")
        assert "FROM python:3.12-slim" in result

    def test_dockerfile_has_multistage_build(self):
        result = generate_dockerfile("local")
        assert "AS builder" in result
        assert "COPY --from=builder" in result

    def test_dockerfile_exposes_correct_port(self):
        result = generate_dockerfile("local")
        assert f"EXPOSE {SERVER_DEFAULT_PORT}" in result

    def test_invalid_target_raises_error(self):
        with pytest.raises(ValueError, match="Unknown deploy target"):
            generate_dockerfile("nonexistent")


class TestGenerateDeployConfig:
    """Verify generate_deploy_config() produces cloud-specific config."""

    def test_local_generates_docker_compose(self):
        result = generate_deploy_config("local")
        assert "docker-compose" in result.lower() or "services:" in result

    def test_gcp_generates_cloud_run_yaml(self):
        result = generate_deploy_config("gcp")
        assert "knative" in result.lower() or "Cloud Run" in result

    def test_aws_generates_apprunner_yaml(self):
        result = generate_deploy_config("aws")
        assert "App Runner" in result or "apprunner" in result.lower()

    def test_azure_generates_container_apps_yaml(self):
        result = generate_deploy_config("azure")
        assert "Container Apps" in result or "container" in result.lower()

    def test_configs_are_non_empty_strings(self):
        for tid in DEPLOY_TARGETS:
            result = generate_deploy_config(tid)
            assert isinstance(result, str)
            assert len(result) > 50, f"{tid} config should be substantial"

    def test_invalid_target_raises_error(self):
        with pytest.raises(ValueError, match="Unknown deploy target"):
            generate_deploy_config("nonexistent")


# ── Project root for file-based tests ────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


class TestDockerContainerPolish:
    """Validate Docker production artifacts for T8 container polish."""

    def test_dockerfile_has_healthcheck(self):
        """Dockerfile must include a HEALTHCHECK instruction."""
        content = (_PROJECT_ROOT / "Dockerfile").read_text()
        assert "HEALTHCHECK" in content

    def test_dockerfile_has_nonroot_user(self):
        """Dockerfile must switch to a non-root USER."""
        content = (_PROJECT_ROOT / "Dockerfile").read_text()
        lines = [
            ln.strip() for ln in content.splitlines() if ln.strip().startswith("USER ")
        ]
        assert len(lines) >= 1, "Dockerfile should have a USER instruction"
        for line in lines:
            user = line.split()[1]
            assert user != "root", "USER should not be root"

    def test_dockerfile_uses_exec_form_cmd(self):
        """CMD must use exec form (JSON array), not shell form."""
        content = (_PROJECT_ROOT / "Dockerfile").read_text()
        found_cmd = False
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("CMD ") and not line[0].isspace():
                found_cmd = True
                cmd_arg = stripped[len("CMD ") :].strip()
                assert cmd_arg.startswith("["), (
                    f"CMD should use exec form (JSON array), got: {stripped}"
                )
        assert found_cmd, "Dockerfile should have a CMD instruction"

    def test_docker_entrypoint_exists_and_executable(self):
        """scripts/docker-entrypoint.sh must exist and have execute permission."""
        entrypoint = _PROJECT_ROOT / "scripts" / "docker-entrypoint.sh"
        assert entrypoint.exists(), "docker-entrypoint.sh not found"
        mode = entrypoint.stat().st_mode
        assert mode & stat.S_IXUSR, "docker-entrypoint.sh should be executable by owner"
