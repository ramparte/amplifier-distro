# Amplifier Distro — E2E Test Recipes

This directory contains Amplifier-native end-to-end tests for distro surfaces.
These complement the pytest unit tests in `tests/` — they test things pytest
cannot: real browsers, live Slack interactions, and full session flows.

## The pattern

```
recipe (.yaml)
  └── stage 1: server-check          (bash — fast fail if server is down)
  └── stage 2: web-chat-tests        (browser-tester:browser-operator)
        └── approval gate            (human confirms Slack login)
  └── stage 3: slack-tests           (browser-tester:browser-operator)
  └── stage 4: validate              (recipes:result-validator → PASS/FAIL table)
```

Each surface gets its own stage. Each stage uses `browser-tester:browser-operator`
with `--headed` (visible browser) and `--session <name>` (isolated context).
An approval gate handles any step that needs human action (e.g. Slack login).
`result-validator` produces the final structured verdict.

## Recipes

| File | What it tests | Scenarios |
|---|---|---|
| `e2e-browser-tests.yaml` | Web-chat + Slack bridge | 5 web-chat + 6 Slack = 11 total |

## Prerequisites

```bash
# 1. Server must be running
amp-distro-server start --port 8400

# 2. agent-browser must be installed
npm install -g agent-browser && agent-browser install
```

## Run the full suite

```bash
# From the amplifier-distro project directory
amplifier tool invoke recipes \
  operation=execute \
  recipe_path=".amplifier/recipes/e2e-browser-tests.yaml"
```

Or from within an Amplifier session:

```
run the e2e-browser-tests recipe
```

### Override defaults

```bash
amplifier tool invoke recipes \
  operation=execute \
  recipe_path=".amplifier/recipes/e2e-browser-tests.yaml" \
  context='{"server_url": "http://127.0.0.1:9000", "slack_channel": "my-channel"}'
```

## Approval gate (Slack login)

The recipe pauses after web-chat tests. When you see the approval prompt:

1. Open a browser and log into `amplifiercrew.slack.com`
2. Confirm you can see the `#amplifier` channel
3. Then approve:

```bash
# See pending approvals
amplifier tool invoke recipes operation=approvals

# Approve
amplifier tool invoke recipes operation=approve \
  session_id=<session-id> \
  stage_name="web-chat-tests"

# Resume
amplifier tool invoke recipes operation=resume \
  session_id=<session-id>
```

## Tail logs while tests run

```bash
tail -f ~/.amplifier/server/server.log \
  | jq -r '[.timestamp[11:19], .level, .message] | join(" | ")'
```

## Adding new test scenarios

**Adding a scenario to an existing surface:**
Edit the `prompt:` block in the relevant stage. Follow the existing format:

```
================================================================
SCENARIO N — Short Name
================================================================
Action  : What the browser operator should do
Verify  : What constitutes a pass
Screenshots: sc-N-name.png
PASS → evidence of success
FAIL → evidence of failure (include actual value)
```

Add the new scenario to the `FINAL REPORT` block and to the acceptance
criteria in the `validate` stage prompt.

**Adding a new surface (e.g. voice, install-wizard):**

1. Add a new stage to the recipe following the same structure
2. Add an approval gate if the surface requires any manual setup
3. Add acceptance criteria to the `validate` stage
4. Update the summary table in this README
