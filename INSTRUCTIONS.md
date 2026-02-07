# Working on the Amplifier Distro

Instructions for anyone contributing to this project, human or AI.

---

## What This Repo Is

An opinionated distribution of the Amplifier AI agent framework. Think
"Linux distro" - we don't build the kernel, we compose existing pieces
into a reliable, well-tested whole and add the glue that makes everything
work together.

**Read first:**
- `OPINIONS.md` - The shared conventions (the "why")
- `ROADMAP.md` - The build plan (the "what" and "when")
- `IMPLEMENTATION.md` - Technical design (the "how")
- `context/DISTRO-PROJECT-CONTEXT.md` - Session resumption context

---

## Repo Layout

This repo contains two kinds of files: **distro code** (what ships)
and **working files** (development infrastructure, docs, planning).

```
amplifier-distro/
  src/                      # DISTRO CODE - what ships
    amplifier_distro/       #   Python package
      __init__.py
      schema.py             #   distro.yaml schema
      cli.py                #   amp-distro CLI
      preflight.py          #   Pre-flight checks
      ...
    bundles/                #   Bundle definitions
      distro-base.md        #   The base bundle
    behaviors/              #   Distro-specific behaviors
      preflight.yaml
      handoff.yaml
      health.yaml

  # ── Working files (NOT part of the distro) ──────────
  planning/                 # Design docs, analysis
  notes/                    # Research, meeting notes
  context/                  # Amplifier session context
  .amplifier/               # Agent notes (AGENTS.md)
  Dockerfile.dev            # Test environment
  docker-compose.yml        # Test profiles
  .env.test                 # Fake API keys for testing
  INSTRUCTIONS.md           # This file
  OPINIONS.md               # Design decisions
  ROADMAP.md                # Build plan
  IMPLEMENTATION.md         # Technical design
```

**The rule:** Everything under `src/` is the distro. Everything else
is working files that support development but don't ship.

The `pyproject.toml` enforces this boundary - only `src/` is packaged.
If you're adding a file, ask: "Does this ship to users?" If yes, it
goes in `src/`. If no, it goes at the root level.

---

## Development Environment

We use Docker to isolate testing from your real machine. Your local
`~/.amplifier/` is never touched by test activities.

### Quick Start

```bash
cd ~/dev/ANext/amplifier-distro

# Build the test image (first time only, ~2 min)
docker compose --profile cli build

# Start the CLI test environment
docker compose --profile cli up -d

# Enter the container
docker compose exec cli bash

# Inside: Amplifier is ready
amplifier --version

# Tear down (clean slate)
docker compose down -v
```

### Available Profiles

| Profile | What It Starts | Use For |
|---------|---------------|---------|
| `cli` | CLI container | Basic testing, amp-distro development |
| `tui` | TUI container | TUI surface testing |
| `gui` | GUI container + ports 8080/3000 | Web interface testing |
| `voice` | Voice container + port 8443 | Voice bridge testing |
| `all` | All surfaces | Full integration testing |
| `agent-test` | CLI + automation tools | Automated testing |
| `human-test` | noVNC desktop (port 6901) | Interactive GUI/voice testing |

### API Keys for Testing

- `.env.test` (committed) - Fake keys for tests that don't hit APIs
- `.env.local` (gitignored) - Your real keys for integration testing

Create `.env.local` if you need real API calls:
```bash
echo 'ANTHROPIC_API_KEY=sk-ant-your-key' >> .env.local
echo 'OPENAI_API_KEY=sk-your-key' >> .env.local
```

### Insulation Model

| What | Where | Lifecycle |
|------|-------|-----------|
| Source code | Bind-mounted at `/workspace/` | Live - edits are instant |
| `~/.amplifier/` | Docker named volume | Wiped with `docker compose down -v` |
| API keys | `.env.test` + `.env.local` | Committed / gitignored |

Your real `~/.amplifier/` is never visible inside the container.

---

## Testing Tools

### Browser Automation: amplifier-bundle-browser

Token-efficient browser automation (93% reduction vs raw Playwright).
Use for GUI surface testing.

```bash
# Inside container
npm install -g agent-browser
agent-browser install --with-deps
agent-browser open http://localhost:8080
agent-browser snapshot -i --json   # Compact interactive elements
```

Repo: https://github.com/ramparte/amplifier-bundle-browser

### UX Analysis: amplifier-ux-analyzer

Screenshot analysis via computer vision. Use for visual regression.

```bash
agent-browser screenshot app.png
python ux-analyzer.py app.png -o analysis.json -v annotated.png
```

Repo: https://github.com/ramparte/amplifier-ux-analyzer

### Combined Workflow

```
1. CAPTURE  -> agent-browser screenshot app.png
2. ANALYZE  -> python ux-analyzer.py app.png -o analysis.json
3. VALIDATE -> compare analysis.json against expected-spec.json
4. INTERACT -> agent-browser click @e1 (fix/retry)
```

---

## Working Conventions

### Commits

Standard format with Amplifier attribution:
```
type: short description

Longer explanation if needed.

Co-Authored-By: Amplifier <240397093+microsoft-amplifier@users.noreply.github.com>
```

Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`

### Branches

- `main` - Current state, always working
- `feat/description` - New features
- `fix/description` - Bug fixes

### For AI Agents

If you're an AI agent working on this repo:

1. **Read `context/DISTRO-PROJECT-CONTEXT.md` first** - it has the
   full project state and key decisions.
2. **Read `.amplifier/AGENTS.md`** - it has environment details and
   build order notes.
3. **Test in Docker, not on the host.** Use `docker compose exec cli`
   to run commands in the isolated environment.
4. **The `src/` boundary is real.** Don't put working files in `src/`
   and don't put distro code outside it.

---

## Infrastructure

| Machine | Role | Access |
|---------|------|--------|
| WIN-DLPODL2CIJB (WSL2) | Primary dev, Docker host | Local |
| spark-1 (DGX) | Headless CI/integration | SSH, no monitor |
| spark-2 (DGX) | Overflow testing | SSH, no monitor |
| Win32 test tenant | Windows-native testing | Admin, Phase 2+ |
