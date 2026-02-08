"""Install Wizard Acceptance Tests

These tests validate the install wizard server app which guides
new users through Amplifier setup.

Exit criteria verified:
1. Manifest has correct name, description, and router
2. WizardState initializes with correct defaults
3. WIZARD_STEPS has 7 entries with required fields
4. AVAILABLE_MODULES has valid entries with required fields
5. Default modules include essential tools and providers
6. All API endpoints return expected responses
7. Step sequencing advances state correctly
8. Reset returns wizard to initial state
"""

from typing import Any

import pytest
from fastapi import APIRouter
from starlette.testclient import TestClient

from amplifier_distro.server.app import AppManifest, DistroServer


@pytest.fixture(autouse=True)
def reset_wizard():
    """Reset wizard state before each test."""
    import amplifier_distro.server.apps.install_wizard as wizard_mod
    from amplifier_distro.server.apps.install_wizard import WizardState

    wizard_mod._wizard_state = WizardState()
    yield


@pytest.fixture
def wizard_client() -> TestClient:
    """Create a TestClient with the install wizard registered."""
    from amplifier_distro.server.apps.install_wizard import manifest

    server = DistroServer()
    server.register_app(manifest)
    return TestClient(server.app)


class TestInstallWizardManifest:
    """Verify the install wizard manifest has correct structure.

    Antagonist note: The manifest is the contract between the wizard
    app and the distro server. Name, description, and router are
    required for proper registration and route mounting.
    """

    def test_manifest_name_is_install_wizard(self):
        from amplifier_distro.server.apps.install_wizard import manifest

        assert manifest.name == "install-wizard"

    def test_manifest_has_router(self):
        from amplifier_distro.server.apps.install_wizard import manifest

        assert manifest.router is not None
        assert isinstance(manifest.router, APIRouter)

    def test_manifest_has_description(self):
        from amplifier_distro.server.apps.install_wizard import manifest

        assert isinstance(manifest.description, str)
        assert len(manifest.description) > 0

    def test_manifest_is_app_manifest_type(self):
        from amplifier_distro.server.apps.install_wizard import manifest

        assert isinstance(manifest, AppManifest)


class TestWizardState:
    """Verify WizardState model initializes with correct defaults.

    Antagonist note: The wizard state drives the entire setup flow.
    Initial state must be pristine so the wizard starts from step 0
    with nothing completed.
    """

    def test_initial_current_step_is_zero(self):
        from amplifier_distro.server.apps.install_wizard import WizardState

        state = WizardState()
        assert state.current_step == 0

    def test_initial_setup_complete_is_false(self):
        from amplifier_distro.server.apps.install_wizard import WizardState

        state = WizardState()
        assert state.setup_complete is False

    def test_initial_completed_steps_is_empty(self):
        from amplifier_distro.server.apps.install_wizard import WizardState

        state = WizardState()
        assert state.completed_steps == []

    def test_state_is_valid_pydantic_model(self):
        from pydantic import BaseModel

        from amplifier_distro.server.apps.install_wizard import WizardState

        state = WizardState()
        assert isinstance(state, BaseModel)
        # model_dump should work without error
        dumped = state.model_dump()
        assert isinstance(dumped, dict)


class TestWizardSteps:
    """Verify WIZARD_STEPS has correct structure and count.

    Antagonist note: The wizard defines exactly 7 steps. Each step
    must have id, name, and description for the UI to render them.
    """

    def test_wizard_steps_has_seven_entries(self):
        from amplifier_distro.server.apps.install_wizard import WIZARD_STEPS

        assert len(WIZARD_STEPS) == 7

    def test_each_step_has_id(self):
        from amplifier_distro.server.apps.install_wizard import WIZARD_STEPS

        for step in WIZARD_STEPS:
            assert "id" in step, f"Step missing 'id': {step}"

    def test_each_step_has_name(self):
        from amplifier_distro.server.apps.install_wizard import WIZARD_STEPS

        for step in WIZARD_STEPS:
            assert "name" in step, f"Step missing 'name': {step}"

    def test_each_step_has_description(self):
        from amplifier_distro.server.apps.install_wizard import WIZARD_STEPS

        for step in WIZARD_STEPS:
            assert "description" in step, f"Step missing 'description': {step}"

    def test_step_ids_are_unique(self):
        from amplifier_distro.server.apps.install_wizard import WIZARD_STEPS

        ids = [step["id"] for step in WIZARD_STEPS]
        assert len(ids) == len(set(ids)), "Step IDs must be unique"

    def test_expected_step_ids_present(self):
        from amplifier_distro.server.apps.install_wizard import WIZARD_STEPS

        ids = {step["id"] for step in WIZARD_STEPS}
        expected = {
            "welcome",
            "config",
            "modules",
            "interfaces",
            "network",
            "provider",
            "verify",
        }
        assert ids == expected


class TestAvailableModules:
    """Verify AVAILABLE_MODULES has valid entries.

    Antagonist note: Available modules are presented to users during
    setup. Each must have all required fields and valid categories.
    Default modules must include the essentials for a working system.
    """

    def test_available_modules_is_non_empty(self):
        from amplifier_distro.server.apps.install_wizard import AVAILABLE_MODULES

        assert len(AVAILABLE_MODULES) > 0

    def test_each_module_has_required_fields(self):
        from amplifier_distro.server.apps.install_wizard import AVAILABLE_MODULES

        required_fields = {"id", "name", "description", "category", "default", "repo"}
        for mod in AVAILABLE_MODULES:
            for field in required_fields:
                assert field in mod, f"Module {mod.get('id', '?')} missing '{field}'"

    def test_categories_are_valid(self):
        from amplifier_distro.server.apps.install_wizard import AVAILABLE_MODULES

        valid_categories = {"provider", "tool", "bundle"}
        for mod in AVAILABLE_MODULES:
            assert mod["category"] in valid_categories, (
                f"Module {mod['id']} has invalid category: {mod['category']}"
            )

    def test_default_modules_include_provider_anthropic(self):
        from amplifier_distro.server.apps.install_wizard import AVAILABLE_MODULES

        defaults = [m["id"] for m in AVAILABLE_MODULES if m["default"]]
        assert "provider-anthropic" in defaults

    def test_default_modules_include_tool_bash(self):
        from amplifier_distro.server.apps.install_wizard import AVAILABLE_MODULES

        defaults = [m["id"] for m in AVAILABLE_MODULES if m["default"]]
        assert "tool-bash" in defaults

    def test_default_modules_include_tool_filesystem(self):
        from amplifier_distro.server.apps.install_wizard import AVAILABLE_MODULES

        defaults = [m["id"] for m in AVAILABLE_MODULES if m["default"]]
        assert "tool-filesystem" in defaults


class TestWizardIndexEndpoint:
    """Verify GET /apps/install-wizard/ returns wizard status."""

    def test_index_returns_200(self, wizard_client: TestClient):
        response = wizard_client.get("/apps/install-wizard/")
        assert response.status_code == 200

    def test_index_returns_app_name(self, wizard_client: TestClient):
        data = wizard_client.get("/apps/install-wizard/").json()
        assert data["app"] == "install-wizard"

    def test_index_returns_setup_complete(self, wizard_client: TestClient):
        data = wizard_client.get("/apps/install-wizard/").json()
        assert data["setup_complete"] is False

    def test_index_returns_total_steps(self, wizard_client: TestClient):
        data = wizard_client.get("/apps/install-wizard/").json()
        assert data["total_steps"] == 7


class TestWizardStepsEndpoint:
    """Verify GET /apps/install-wizard/steps returns step list."""

    def test_steps_returns_200(self, wizard_client: TestClient):
        response = wizard_client.get("/apps/install-wizard/steps")
        assert response.status_code == 200

    def test_steps_returns_seven_steps(self, wizard_client: TestClient):
        data = wizard_client.get("/apps/install-wizard/steps").json()
        assert len(data) == 7

    def test_steps_include_completion_status(self, wizard_client: TestClient):
        data = wizard_client.get("/apps/install-wizard/steps").json()
        for step in data:
            assert "completed" in step
            assert "current" in step

    def test_first_step_is_current(self, wizard_client: TestClient):
        data = wizard_client.get("/apps/install-wizard/steps").json()
        assert data[0]["current"] is True
        assert data[1]["current"] is False


class TestWizardModulesEndpoint:
    """Verify GET /apps/install-wizard/modules returns module list."""

    def test_modules_returns_200(self, wizard_client: TestClient):
        response = wizard_client.get("/apps/install-wizard/modules")
        assert response.status_code == 200

    def test_modules_returns_modules_list(self, wizard_client: TestClient):
        data = wizard_client.get("/apps/install-wizard/modules").json()
        assert "modules" in data
        assert len(data["modules"]) > 0

    def test_modules_returns_selected_list(self, wizard_client: TestClient):
        data = wizard_client.get("/apps/install-wizard/modules").json()
        assert "selected" in data
        assert data["selected"] == []


class TestWizardStateEndpoint:
    """Verify GET /apps/install-wizard/state returns full state."""

    def test_state_returns_200(self, wizard_client: TestClient):
        response = wizard_client.get("/apps/install-wizard/state")
        assert response.status_code == 200

    def test_state_returns_initial_values(self, wizard_client: TestClient):
        data = wizard_client.get("/apps/install-wizard/state").json()
        assert data["current_step"] == 0
        assert data["setup_complete"] is False
        assert data["completed_steps"] == []

    def test_state_returns_all_fields(self, wizard_client: TestClient):
        data = wizard_client.get("/apps/install-wizard/state").json()
        expected_keys = {
            "current_step",
            "completed_steps",
            "workspace_root",
            "github_handle",
            "git_email",
            "selected_modules",
            "installed_interfaces",
            "tailscale_enabled",
            "tailscale_hostname",
            "provider",
            "provider_key_set",
            "setup_complete",
        }
        assert set(data.keys()) == expected_keys


class TestWizardDetectEndpoint:
    """Verify GET /apps/install-wizard/detect returns detection results."""

    def test_detect_returns_200(self, wizard_client: TestClient):
        response = wizard_client.get("/apps/install-wizard/detect")
        assert response.status_code == 200

    def test_detect_returns_tools_dict(self, wizard_client: TestClient):
        data = wizard_client.get("/apps/install-wizard/detect").json()
        assert "tools" in data
        assert isinstance(data["tools"], dict)

    def test_detect_returns_api_keys_dict(self, wizard_client: TestClient):
        data = wizard_client.get("/apps/install-wizard/detect").json()
        assert "api_keys" in data
        assert "anthropic" in data["api_keys"]
        assert "openai" in data["api_keys"]

    def test_detect_returns_tailscale_info(self, wizard_client: TestClient):
        data = wizard_client.get("/apps/install-wizard/detect").json()
        assert "tailscale" in data

    def test_detect_returns_workspace_candidates(self, wizard_client: TestClient):
        data = wizard_client.get("/apps/install-wizard/detect").json()
        assert "workspace_candidates" in data
        assert isinstance(data["workspace_candidates"], list)


class TestStepWelcome:
    """Verify POST /apps/install-wizard/steps/welcome."""

    def test_welcome_step_succeeds(self, wizard_client: TestClient, tmp_path: Any):
        response = wizard_client.post(
            "/apps/install-wizard/steps/welcome",
            json={
                "workspace_root": str(tmp_path / "test_workspace"),
                "github_handle": "testuser",
                "git_email": "test@example.com",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["workspace_created"] is True

    def test_welcome_step_advances_state(
        self, wizard_client: TestClient, tmp_path: Any
    ):
        wizard_client.post(
            "/apps/install-wizard/steps/welcome",
            json={"workspace_root": str(tmp_path / "ws")},
        )
        state = wizard_client.get("/apps/install-wizard/state").json()
        assert state["current_step"] == 1
        assert "welcome" in state["completed_steps"]


class TestStepModules:
    """Verify POST /apps/install-wizard/steps/modules."""

    def test_modules_step_succeeds(self, wizard_client: TestClient):
        response = wizard_client.post(
            "/apps/install-wizard/steps/modules",
            json={"modules": ["provider-anthropic", "tool-bash"]},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["count"] == 2

    def test_modules_step_updates_selected(self, wizard_client: TestClient):
        wizard_client.post(
            "/apps/install-wizard/steps/modules",
            json={"modules": ["tool-bash", "tool-filesystem"]},
        )
        state = wizard_client.get("/apps/install-wizard/state").json()
        assert "tool-bash" in state["selected_modules"]
        assert "tool-filesystem" in state["selected_modules"]


class TestStepNetwork:
    """Verify POST /apps/install-wizard/steps/network."""

    def test_network_step_with_tailscale_disabled(self, wizard_client: TestClient):
        response = wizard_client.post(
            "/apps/install-wizard/steps/network",
            json={"tailscale_enabled": False},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["tailscale_enabled"] is False

    def test_network_step_advances_state(self, wizard_client: TestClient):
        wizard_client.post(
            "/apps/install-wizard/steps/network",
            json={"tailscale_enabled": False},
        )
        state = wizard_client.get("/apps/install-wizard/state").json()
        assert "network" in state["completed_steps"]
        assert state["current_step"] == 5


class TestStepVerify:
    """Verify POST /apps/install-wizard/steps/verify."""

    def test_verify_step_runs_checks(self, wizard_client: TestClient):
        response = wizard_client.post("/apps/install-wizard/steps/verify")
        assert response.status_code == 200
        data = response.json()
        assert "checks" in data
        assert isinstance(data["checks"], list)
        assert len(data["checks"]) > 0

    def test_verify_checks_have_name_and_passed(self, wizard_client: TestClient):
        data = wizard_client.post("/apps/install-wizard/steps/verify").json()
        for check in data["checks"]:
            assert "name" in check
            assert "passed" in check


class TestResetWizard:
    """Verify POST /apps/install-wizard/reset."""

    def test_reset_returns_ok(self, wizard_client: TestClient):
        response = wizard_client.post("/apps/install-wizard/reset")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_reset_clears_state_after_step(self, wizard_client: TestClient):
        # Advance state
        wizard_client.post(
            "/apps/install-wizard/steps/modules",
            json={"modules": ["tool-bash"]},
        )
        state = wizard_client.get("/apps/install-wizard/state").json()
        assert state["current_step"] != 0

        # Reset
        wizard_client.post("/apps/install-wizard/reset")
        state = wizard_client.get("/apps/install-wizard/state").json()
        assert state["current_step"] == 0
        assert state["completed_steps"] == []
        assert state["setup_complete"] is False


class TestStepSequencing:
    """Verify wizard state progresses through steps correctly.

    Antagonist note: The wizard is a sequential flow. Each step
    must advance current_step and record itself in completed_steps.
    After reset, everything returns to initial state.
    """

    def test_welcome_advances_to_step_1(self, wizard_client: TestClient, tmp_path: Any):
        wizard_client.post(
            "/apps/install-wizard/steps/welcome",
            json={"workspace_root": str(tmp_path / "ws")},
        )
        state = wizard_client.get("/apps/install-wizard/state").json()
        assert state["current_step"] == 1

    def test_modules_advances_to_step_3(self, wizard_client: TestClient):
        wizard_client.post(
            "/apps/install-wizard/steps/modules",
            json={"modules": ["tool-bash"]},
        )
        state = wizard_client.get("/apps/install-wizard/state").json()
        assert state["current_step"] == 3

    def test_network_advances_to_step_5(self, wizard_client: TestClient):
        wizard_client.post(
            "/apps/install-wizard/steps/network",
            json={"tailscale_enabled": False},
        )
        state = wizard_client.get("/apps/install-wizard/state").json()
        assert state["current_step"] == 5

    def test_multiple_steps_accumulate_completed(
        self, wizard_client: TestClient, tmp_path: Any
    ):
        wizard_client.post(
            "/apps/install-wizard/steps/welcome",
            json={"workspace_root": str(tmp_path / "ws")},
        )
        wizard_client.post(
            "/apps/install-wizard/steps/modules",
            json={"modules": ["tool-bash"]},
        )
        wizard_client.post(
            "/apps/install-wizard/steps/network",
            json={"tailscale_enabled": False},
        )
        state = wizard_client.get("/apps/install-wizard/state").json()
        assert "welcome" in state["completed_steps"]
        assert "modules" in state["completed_steps"]
        assert "network" in state["completed_steps"]

    def test_reset_returns_to_initial_state(
        self, wizard_client: TestClient, tmp_path: Any
    ):
        # Run through some steps
        wizard_client.post(
            "/apps/install-wizard/steps/welcome",
            json={"workspace_root": str(tmp_path / "ws")},
        )
        wizard_client.post(
            "/apps/install-wizard/steps/modules",
            json={"modules": ["tool-bash"]},
        )

        # Reset
        wizard_client.post("/apps/install-wizard/reset")
        state = wizard_client.get("/apps/install-wizard/state").json()
        assert state["current_step"] == 0
        assert state["completed_steps"] == []
        assert state["selected_modules"] == []
        assert state["setup_complete"] is False
