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
| Web UI | unassigned | Candidate: @samueljklee or @samschillace |
| UI flows (onboarding, wizards, config) | @samschillace (interim) | Needs stub mode for fast iteration |
| Bundle structure | @samueljklee | Currently active |
| Teams integration | @marklicata | |
| M365 integration | @robotdad | |
| Containers/Cloud/Azure | @marklicata + @robotdad | Co-owned |
| Bridges (Slack, Voice) | @robotdad | Could involve @dluc |
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

- [ ] **DISTRO-002**: Build UI stub mode for fast flow preview without real installs
  - Priority: high
  - Added: 2026-02-10
  - Tags: ui-flows, onboarding, developer-experience
  - Notes: Allow quick iteration on onboarding/wizard/config UI without spinning up real services. Mock backends, fake config, skip preflight.

- [ ] **DISTRO-003**: Polish and own the Web UI surface
  - Priority: medium
  - Added: 2026-02-10
  - Tags: web-ui, surfaces
  - Notes: Needs an owner. Candidates: @samueljklee, @samschillace

- [ ] **DISTRO-004**: Bundle structure finalization
  - Assigned: @samueljklee
  - Priority: high
  - Added: 2026-02-10
  - Tags: phase-1, bundle, core

- [ ] **DISTRO-005**: Desktop GUI continued development
  - Assigned: @michaeljabbour
  - Priority: medium
  - Added: 2026-02-10
  - Tags: phase-2, gui, surfaces

- [ ] **DISTRO-006**: Containers and cloud deployment (Azure, Docker)
  - Assigned: @marklicata, @robotdad
  - Priority: medium
  - Added: 2026-02-10
  - Tags: phase-4, containers, cloud, azure

- [ ] **DISTRO-007**: Teams integration
  - Assigned: @marklicata
  - Priority: medium
  - Added: 2026-02-10
  - Tags: phase-2, teams, surfaces

- [ ] **DISTRO-018**: M365 integration
  - Assigned: @robotdad
  - Priority: medium
  - Added: 2026-02-10
  - Tags: phase-2, m365, surfaces
  - Notes: Split from DISTRO-007. M365 integration beyond Teams (Outlook, SharePoint, etc.).

- [ ] **DISTRO-008**: Slack bridge hardening and production readiness
  - Assigned: @robotdad
  - Priority: medium
  - Added: 2026-02-10
  - Tags: phase-2, bridges, slack

- [ ] **DISTRO-009**: Voice bridge hardening and production readiness
  - Assigned: @robotdad
  - Priority: medium
  - Added: 2026-02-10
  - Tags: phase-2, bridges, voice, webrtc

- [ ] **DISTRO-010**: Onboarding and wizard flow design
  - Assigned: @samschillace
  - Priority: high
  - Added: 2026-02-10
  - Tags: ui-flows, onboarding, install-wizard

- [ ] **DISTRO-011**: CLI surface ownership and review
  - Priority: medium
  - Added: 2026-02-10
  - Tags: cli, surfaces
  - Notes: Tentatively @dluc. CLI needs to be robust and well-structured.

## Backlog

- [ ] **DISTRO-012**: Testing/QA strategy and ownership
  - Priority: medium
  - Added: 2026-02-10
  - Tags: testing, qa, infrastructure
  - Notes: 755 tests exist. Need strategy for DGX CI, Docker test profiles, coverage gaps. Suggested owner: @dluc.

- [ ] **DISTRO-013**: Documentation plan (user-facing docs, install guides)
  - Priority: low
  - Added: 2026-02-10
  - Tags: docs, phase-3
  - Notes: As surfaces multiply, docs become critical. Suggested owner: @marklicata or @samueljklee.

- [ ] **DISTRO-014**: Security review (auth, keys, API exposure across surfaces)
  - Priority: medium
  - Added: 2026-02-10
  - Tags: security, review
  - Notes: Suggested owner: @dluc.

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

