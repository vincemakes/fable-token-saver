# fable-token-saver

**English** | [简体中文](README.zh-CN.md)

**Tiered model orchestration for Claude Code.** Keep your most expensive model (Fable, Opus — whatever tops the lineup) on judgment work only — decomposing, spec-writing, reviewing — while cheaper models (Sonnet/Haiku tiers) do the implementation. Objective gates (typecheck/tests) filter out everything a machine can catch before an expensive token is spent reviewing.

Measured effect on a real 1,100-line task: **−34% strongest-tier quota in lite mode, −88% in max mode**, identical output quality. Full data in [BENCHMARKS.md](BENCHMARKS.md).

## How it works

Every Claude Code session has a **main loop** — the model you pick with `/model`. The main loop pays for everything it touches: every tool result, every file read, every turn of bookkeeping. That "main-loop tax" is most of what a session costs, and a skill cannot change which model runs it — only you can, via `/model`. What a skill *can* do is decide which model runs each **subagent** (the Agent tool takes a per-spawn `model` parameter, using version-agnostic aliases).

This skill exploits both facts:

```
 lite mode  (/model = Fable)              max mode  (/model = Opus 4.8)
 ┌───────────────────────────┐            ┌───────────────────────────┐
 │ FABLE · main loop         │            │ OPUS · main loop          │
 │ classify → spec → review  │            │ classify → spec → review  │
 └─────┬─────────────────────┘            └─────┬───────────────┬─────┘
       │ task packets                           │ task packets  │ 2 briefs only
       ▼                                        ▼               ▼
 ┌──────────┐  ┌──────────┐              ┌──────────┐   ┌──────────────┐
 │ SONNET   │  │ HAIKU    │              │ SONNET   │   │ FABLE        │
 │implement │  │ mechanic │              │implement │   │ consultant:  │
 └────┬─────┘  └────┬─────┘              └────┬─────┘   │ plan verdict │
      │  gate: tsc+tests green ──┐            │  gate   │ final review │
      ▼                          ▼            ▼         └──────────────┘
     diff-only review by the main loop       diff review → consultant approves
```

- **Task packets**, never conversation history: workers get GOAL / CONTEXT (≤5 lines) / ALLOWED FILES / SPEC / GATE / DO-NOT-fence.
- **Gates before review**: the worker runs `tsc && tests` in *its own* context and self-fixes until green (max 3 attempts). Ungated code is never reviewed.
- **Diff-only review** for design and intent — the gate owns syntax, types, and test truth.
- **In max mode**, the strongest model is a stateless consultant: the mid-tier main loop *drafts* the plan (drafting is long-form and belongs on the cheap tier), Fable only *rules* on it, then approves or revises the final diff. Two brief-in/verdict-out calls, zero session context carried (measured: 0 cache-read tokens).

## Two modes — pick by picking your session model

No config file: the skill detects your main-loop model and adapts. Mode names describe **saving intensity** (lite saves less, max saves most) — not model strength.

| | **lite** | **max** |
|---|---|---|
| Main loop (`/model`) | strongest tier (Fable) | mid tier (**Opus recommended**) |
| Code written by | Sonnet / Haiku workers | Sonnet / Haiku workers |
| Strongest tier's job | steers every step | consultant at 2 checkpoints only |
| Strongest-tier quota | **−34% (measured)** | **−88% (measured, Opus loop)** |
| Total dollar cost | lowest orchestrated config | **+86% vs baseline** — trades dollars for quota |
| Use when | top-tier judgment on every turn | strongest-tier quota is your binding constraint |

## Benchmarks (the elevator version)

Same 1,100-line greenfield task, four configurations, all gates green, quality assertions identical:

- **lite**: strongest-tier quota **−34%**, lowest total cost of any orchestrated config, most tests produced
- **max (Opus loop)**: strongest-tier quota **−88%**, fastest (116s vs 335s baseline), but total cost +86%
- **Capability parity verified by a blind bug-hunt**: 6 planted production-grade bugs, symptom-only reports, hidden test suite — baseline Fable **6/6**, max mode **6/6**. Root-cause reasoning survives the consultant architecture intact.
- **Small tasks (< ~300 lines) and debugging: negative returns** (+34~66% strongest-tier on small tasks; on the bug hunt max mode cost 2.2× for identical quality) — the skill detects both and steps aside

Full four-way tables, the itemized quota bill, per-model pricing, methodology, and honest findings (including why a Sonnet main loop loses on both metrics): **[BENCHMARKS.md](BENCHMARKS.md)**.

## Install

```bash
git clone https://github.com/<you>/fable-token-saver ~/.claude/skills/fable-token-saver
```

That's it for harnesses whose Agent tool supports per-subagent model override (current Claude Code does). Optionally, install the pinned worker agents for automatic routing:

```bash
mkdir -p .claude/agents
cp ~/.claude/skills/fable-token-saver/assets/agents/*.md .claude/agents/
```

## Use

Three ways to start it, in any mode:

1. **Explicit** — `/fable-token-saver refactor the payments module`
2. **Natural language** — "delegate this to cheaper models and review the result", "token-saver this task", "省token模式做这个", "用 token saver 走一下"
3. **Proactive** — on sizable well-specified tasks (roughly 300+ lines or 6+ files) the skill triggers itself; below that delegation floor it deliberately stays out of the way.

## When not to use it

One-liners, pure analysis, design-heavy cores, and anything under the delegation floor. The benchmarks show why: below ~300 lines, packet-writing plus review costs more than just typing the change. The skill says so itself and steps aside.

## License

MIT
