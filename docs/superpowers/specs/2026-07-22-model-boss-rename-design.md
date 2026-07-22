# Model Boss Rename Design

**Date:** 2026-07-22  
**Status:** Approved for implementation planning

## Goal

Rename Token Saver to **Model Boss** and make the new identity consistent across the
repository, install paths, runtime package, CLI, configuration, generated skill bundle,
documentation, tests, social artwork, GitHub repository, Git branch, and local checkout.

Model Boss keeps the existing cross-model orchestration protocol unchanged. The host
still chooses the conversation's main-loop model before Model Boss runs. Model Boss
places planning, implementation, evidence gates, review, and integration around that
inherited main loop; it does not dynamically replace the main loop.

## Audience and positioning

The primary audience is global developers using Claude Code, Codex, or compatible
local model CLIs. The product name should be memorable in conversation and immediately
suggest a hierarchy of models doing different jobs.

- **Product name:** Model Boss
- **Canonical slug:** `model-boss`
- **Primary slogan:** **Big models think. Small models ship.**
- **Technical subtitle:** **Cross-model coding orchestration**

The slogan is the marketing shorthand. The documentation must retain the precise
capability language: model roles are relative to the selected workflow, and the system
does not claim a universal provider-independent ranking of model quality.

## User-facing model

Lite and Max remain because they represent different authority placements:

- **Lite:** the inherited main loop is the Boss. It plans, reasons, reviews, and
  integrates. An optional secondary worker performs bounded implementation.
- **Max:** a distinct verified authority reviewer is the Boss. The inherited main loop
  coordinates and audits, and it may implement directly or delegate to another worker.

“Boss” is the concise product metaphor for the authority holder. Protocol code and
security documentation continue to use the exact terms `authority`, `main loop`,
`reviewer`, and `worker` where precision matters.

## Canonical identifiers

All active product surfaces move to the new identity:

| Surface | Canonical value |
|---|---|
| GitHub repository | `vincemakes/model-boss` |
| Local checkout | `/Users/vinve/Desktop/devv/model-boss` |
| Git branch | `codex/model-boss` |
| Skill frontmatter | `name: model-boss` |
| Python package | `runtime/model_boss` and imports under `model_boss` |
| CLI entry script | `scripts/model-boss.py` |
| Config files | `config/model-boss.example.json`, `config/model-boss.schema.json` |
| Environment prefix | `MODEL_BOSS_` |
| State and task paths | `.model-boss`, `model-boss-runs`, and equivalent platform paths |
| Agent declarations | `model-boss-<role>` |
| Release artifact | `dist/model-boss.skill` |

Internal JSON schema IDs, user-agent strings, temporary-directory prefixes, help text,
errors, examples, and test fixtures follow the same canonical naming. Existing generic
protocol field names such as `authority_mode`, `main_loop`, and `reviewer` do not change.

## Migration boundary

This is a clean product rename, not a permanent dual-brand release.

- Active commands, installation examples, generated files, and package contents use
  only `model-boss`.
- The former names `token-saver` and `fable-token-saver` may remain only in an explicit
  migration note, skill trigger wording for users asking to migrate, Git history, or
  dated benchmark provenance where changing the label would falsify the record.
- No duplicate Python package or long-lived legacy CLI shim is shipped. The migration
  note provides the old-to-new command, config, and installation-path mapping.
- GitHub's repository rename redirect covers old clone URLs, while canonical docs and
  the local `origin` use the new URL.

## Documentation and artwork

README files, SKILL instructions, references, agent prompts, examples, developer notes,
benchmarks, and generated help must introduce Model Boss consistently. The first screen
of each README explains the Boss metaphor, then immediately states that the main loop is
host-selected and immutable.

The social card is regenerated around the Model Boss name and the Lite/Max hierarchy.
It must avoid provider-specific branding and remain readable at GitHub social-preview
size.

## Verification and release

Implementation is complete only when all of the following hold:

1. Tests are changed first to assert the new package, CLI, paths, metadata, and artifact.
2. A repository-wide old-name audit finds former names only in the approved migration
   and provenance allowlist.
3. Unit, integration, sandbox, documentation, skill-validation, packaging,
   reproducibility, and extracted-bundle smoke tests pass.
4. The new social card is visually inspected.
5. The GitHub repository is renamed to `vincemakes/model-boss`, the local remote is
   updated, `codex/model-boss` is pushed, a pull request is created and merged, and the
   merged default branch is verified.
6. The local checkout is renamed to `/Users/vinve/Desktop/devv/model-boss` only after
   all commands that depend on the old working directory have finished.

Any failed verification stops release. Repository renaming, pushing, merging, and local
directory renaming are release steps and must not conceal an uncommitted or failing
tree.

## Non-goals

- Dynamically selecting or replacing the host-selected main-loop model.
- Changing the Lite/Max state machine, evidence contract, sandbox model, or authority
  separation rules.
- Merging the separate generic `model-router` skill into this repository.
- Introducing a hosted service, UI, billing system, or provider-specific control plane.
