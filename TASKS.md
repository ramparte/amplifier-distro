# Tasks: amplifier-distro

<!-- project-id: DISTRO -->
<!-- repo: ramparte/amplifier-distro -->
<!-- managed with amplifier project-mgmt skill -->

## Ownership Map

| Area | Owner | Notes |
|------|-------|-------|
| Distro overall | @samschillace | Architect, lead |
| Desktop GUI | @michaeljabbour | Built it, owns it |
| TUI | @samschillace (interim) | Candidate: @samueljklee |
| CLI | @dluc (tentative) | |
| Web UI | @robotdad | Session list, resume, LLM context (#65) |
| UI flows (onboarding, wizards, config) | @samschillace (interim) | Install wizard built |
| Bundle structure | @samueljklee | |
| Teams integration | @marklicata | In progress (local branch) |
| M365 integration | @robotdad | |
| Containers/Cloud/Azure | @marklicata + @robotdad | Co-owned |
| Bridges (Slack, Voice) | @robotdad | Major hardening done |
| Testing/QA strategy | unassigned | Suggested: @dluc |
| Documentation | unassigned | Suggested: @marklicata or @samueljklee |
| Security review | unassigned | Suggested: @dluc |
| Memory/backup subsystem | @samschillace | Already built, needs ongoing owner |

## Active

- [ ] **DISTRO-001**: Designate surface owners and confirm with team
  - Assigned: @samschillace
  - Priority: high
  - Added: 2026-02-10
  - Tags: meta, team
  - Notes: Ownership map above is draft. Need team confirmation.

- [ ] **DISTRO-005**: Desktop GUI continued development
  - Assigned: @michaeljabbour
  - Priority: medium
  - Added: 2026-02-10
  - Tags: phase-2, gui, surfaces

- [ ] **DISTRO-009**: Voice bridge hardening and production readiness
  - Assigned: @robotdad
  - Priority: medium
  - Added: 2026-02-10
  - Tags: phase-2, bridges, voice, webrtc
  - Notes: Voice transcript controls added (PR #40). Further hardening needed.

- [ ] **DISTRO-011**: CLI surface ownership and review
  - Priority: medium
  - Added: 2026-02-10
  - Tags: cli, surfaces
  - Notes: Tentatively @dluc. CLI needs to be robust and well-structured. Update check improvements merged.

- [ ] **DISTRO-018**: M365 integration
  - Assigned: @robotdad
  - Priority: medium
  - Added: 2026-02-10
  - Tags: phase-2, m365, surfaces
  - Notes: Split from DISTRO-007. M365 integration beyond Teams (Outlook, SharePoint, etc.).

## Backlog

- [ ] **DISTRO-012**: Testing/QA strategy and ownership
  - Priority: medium
  - Added: 2026-02-10
  - Tags: testing, qa, infrastructure
  - Notes: Test count growing significantly with team PRs. Need strategy for DGX CI, Docker test profiles, coverage gaps. Suggested owner: @dluc.

- [ ] **DISTRO-013**: Documentation plan (user-facing docs, install guides)
  - Priority: low
  - Added: 2026-02-10
  - Tags: docs, phase-3
  - Notes: Install script now exists. As surfaces multiply, docs become critical. Suggested owner: @marklicata or @samueljklee.

- [ ] **DISTRO-014**: Security review (auth, keys, API exposure across surfaces)
  - Priority: medium
  - Added: 2026-02-10
  - Tags: security, review
  - Notes: Email bridge removed for security reasons (open ingestion = prompt injection). Suggested owner: @dluc.

- [ ] **DISTRO-015**: TUI surface development
  - Priority: low
  - Added: 2026-02-10
  - Tags: phase-2, tui, surfaces
  - Notes: @samschillace interim. Candidate to hand off to @samueljklee once bundle work settles.

- [ ] **DISTRO-016**: DGX cluster CI pipeline setup (spark-1, spark-2)
  - Priority: low
  - Added: 2026-02-10
  - Tags: ci, infrastructure, testing, dgx

- [ ] **DISTRO-017**: Handoff hooks implementation (needs core PR)
  - Priority: medium
  - Added: 2026-02-10
  - Tags: phase-1, core, bridges
  - Notes: Blocked on amplifier-core PR for handoff hook support.

## Completed

- [x] **DISTRO-002**: Build UI stub mode for fast flow preview without real installs
  - Priority: high
  - Completed: 2026-02-10
  - Tags: ui-flows, onboarding, developer-experience
  - Resolution: `--stub` mode implemented (commit 68dd1df)

- [x] **DISTRO-004**: Bundle structure finalization
  - Assigned: @samueljklee
  - Priority: high
  - Completed: 2026-02-13
  - Tags: phase-1, bundle, core
  - Resolution: Convention-path bundle loading replaced name-based resolution (PR #12)

- [x] **DISTRO-008**: Slack bridge hardening and production readiness
  - Assigned: @robotdad
  - Priority: medium
  - Completed: 2026-02-19
  - Tags: phase-2, bridges, slack
  - Resolution: Major hardening across 10+ PRs. Zombie session deactivation (#31), CWD support (#34/#58), cross-contamination fix (#54), concurrency fix (#57/#63), session resume (#64/#67), max_sessions cap removed (#66). Transcript persistence (#52). Session info persistence (#53/#56).

- [x] **DISTRO-003**: Web UI surface - session list, resume, and LLM context
  - Priority: medium
  - Completed: 2026-02-19
  - Tags: web-ui, surfaces
  - Resolution: Web chat session list, resume, and LLM context restoration (PR #65). Session store added.

- [x] **DISTRO-010**: Onboarding and wizard flow design
  - Assigned: @samschillace
  - Priority: high
  - Completed: 2026-02-12
  - Tags: ui-flows, onboarding, install-wizard
  - Resolution: Install wizard and Slack setup UI implemented (PR #16, #17). Install script added. Landing page created (PR #18).

- [x] **DISTRO-006**: Containers and cloud deployment (Azure, Docker)
  - Assigned: @marklicata, @robotdad
  - Priority: medium
  - Completed: 2026-02-14
  - Tags: phase-4, containers, cloud, azure
  - Resolution: Dockerfile consolidated (prod+dev merged), devcontainer.json added, docker-entrypoint.sh updated. One-click setup (PR #39).

## Blocked

- [ ] **DISTRO-007**: Teams integration
  - Assigned: @marklicata
  - Priority: medium
  - Added: 2026-02-10
  - Tags: phase-2, teams, surfaces
  - Notes: In progress on local branch `fix/bundle-resolution-precedence` (teams/ dir + test). Blocked on server stability.
