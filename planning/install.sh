
- set amplifier home: AMPLIFIER_HOME="${AMPLIFIER_HOME:-$HOME/.amplifier}"
- create required dirs:
  mkdir -p "$AMPLIFIER_HOME/memory" \
           "$AMPLIFIER_HOME/cache" \
           "$AMPLIFIER_HOME/projects" \
           "$AMPLIFIER_HOME/server" \
           "$AMPLIFIER_HOME/bundles"
- create distro.yaml
- set workplace root: workspace_root: ${WORKSPACE_ROOT:-$HOME/dev}
- configure identity:
  - github_handle: ${GITHUB_HANDLE:-docker}
  - git_email: ${GIT_EMAIL:-docker@amplifier.local}
- setup provider keys in `$AMPLIFIER_HOME/keys.yaml`:
  - ANTHROPIC_API_KEY
  - OPENAI_API_KEY
  - GITHUB_TOKEN
  - SLACK_BOT_TOKEN SLACK_APP_TOKEN SLACK_SIGNING_SECRET
