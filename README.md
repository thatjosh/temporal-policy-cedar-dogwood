# temporal-policy-cedar-dogwood

An experiment in writing **temporal constraints**, meaning authorization rules
about what has already happened, in two engines:
[Cedar](https://www.cedarpolicy.com/) and
[Dogwood](https://github.com/dogwood-policy/dogwood), the temporal superset of
Cedar that AWS open-sourced in August 2026.

One rule, implemented twice, tested by the same cases, so the difference between
the two is the measurement.

> **Under construction.** The Cedar v1 implementation and the shared case table
> have landed. Dogwood v1 is next, then the temporal rule in both.

## The problem

Imagine an agent whose job is to approve customer refunds automatically. You are
cautious about what it can do unsupervised, so you add a rule: anything over
$100 escalates to a human. The payment tool enforces it, and any single payment
above $100 is denied.

That feels like a good control, and it is, right up until the agent becomes
overeager. Handed a $500 refund it cannot pay in one go, it splits the claim
into five payments of $100 and pays each one. Every payment is inside the limit.
Every payment is approved. The escalation never happens.

![A $500 claim is split by the agent into five payments of $100. Each is checked
against the $100 rule and approved. The running total climbs to $500, crossing
the $100 escalation threshold, which never fires because no single payment
exceeded it.](docs/img/salami-slice.png)

Why the agent behaved that way is a separate investigation, and not the one that
fixes this. What matters is how you design a policy that an overeager agent
cannot get through.

The engine was asked, five times, whether a $100 payment was allowed, and five
times it answered correctly. It was never asked whether $500 had already gone
out. That is not a question about a payment. It is a question about the payments
before it, and a rule that sees one request at a time cannot bound what a
sequence of them adds up to.

So the control has to change shape. Not *is this payment allowed*, but *is this
payment allowed given everything already paid*. That second rule is temporal,
and it needs something a policy engine is usually built not to have: memory.

## The two versions

|  | The rule | Kind |
|---|---|---|
| **v1** | A single payment may not exceed **$100.00** | ordinary |
| **v2** | v1, **plus**: payments on one order may not exceed **$100.00 in any rolling 60 minutes** | **temporal** |

v1 needs only the request in front of it. v2 needs to know what was paid before,
and most policy engines remember nothing at all. That is deliberate: an engine
with no memory is easy to test, and gives the same answer every time you ask it
the same question.

## What this repo sets out to show

Dogwood states v2 in the policy file, because its policies read an event log.
Cedar cannot. A Cedar decision is a pure function of the request, the policies
and the entity store, and none of those is history. So the rule splits in two.
Your code computes the rolling total, the policy compares it to the cap, and
from then on the rule holds only while both halves agree.

![Two boxes. On the left, your own code holds the ledger, filters it to this
order and the last sixty minutes, and produces a total of $60. A single arrow
carries that number across into the policy engine on the right, which verifies
the window is for the right order and starts sixty minutes before the request,
but trusts that the total itself is correct.](docs/img/cedar-counts-outside.png)

![The same two boxes with the counting relocated. On the left, your event log
holds one record per executed payment. An arrow carries the raw events into the
policy engine, which now computes the total itself, but trusts that every
payment reached the log and that each event carries the fields the rule
names.](docs/img/dogwood-counts-inside.png)

Neither engine escapes trust. They place it differently: Cedar trusts a number
you computed, Dogwood trusts the log you kept. What the split costs Cedar, in
files and in what can be unit tested, is the measurement.

## Setup

    uv sync         # Python, dependencies, virtualenv
    make dogwood    # fetch and compile the Dogwood engine into .tools/
    make check      # lint, types, and the full suite

You need [uv](https://docs.astral.sh/uv/) and a Rust toolchain; Python is pinned
and uv fetches it. `make dogwood` builds the pinned revision into `.tools/`
(gitignored) in about a minute, installing nothing system-wide, leaving no
`PATH` to edit, and a second run is a no-op. If `cargo` is missing it says how
to get it. If rustup installed it but your shell never exported it, `make` looks
in `~/.cargo/bin` anyway.

The suite finds the engine in `.tools/` before `PATH`. `DOGWOOD_BIN` overrides
both and is then authoritative, so you always know which engine produced a
result. No Rust toolchain and don't want one? `make test-cedar`.

**Why Dogwood needs its own step.** Cedar is a Python library, so `uv sync`
installs it. Dogwood ships no Python binding and publishes no release binaries,
so it must be compiled and then driven as a subprocess. That asymmetry is the
first thing this experiment turns up, and you meet it before reading any code.

## Commands

| Command | What it does |
|---|---|
| `make check` | lint, types, full suite; run before a PR |
| `make test` | the whole suite; **requires** the engine |
| `make test-cedar` | only the half that needs no engine |
| `make lint` / `make types` / `make fmt` | `ruff` · `mypy --strict` · apply fixes |
| `make dogwood` / `make clean` | build the pinned engine · drop it, keep the build cache |
| `make distclean` | remove `.tools/` entirely, including the source clone |

Dogwood tests **fail loudly** when the engine is missing rather than skipping. A
suite that reports success having never asked the engine anything is worse than
a red one.

## Notes

**There is no LLM here.** No API calls, no model, no `anthropic` dependency. The
behaviour under test, an agent splitting one payment into several legal ones, is
fixed sequences of payments in the tests. Everything else is real: both engines
run the actual policy files in this repo, and every result comes from a run.

**What is pinned, and what is not.** Pinned: the Dogwood revision
(`DOGWOOD_REV` in the `Makefile`, read by CI so there is one copy), the Rust
toolchain, Python, and every Python dependency via `uv.lock`. Not pinned:
Dogwood's own Rust dependencies, because upstream commits no `Cargo.lock`, so
`cargo` re-resolves the tree on every cold build and `--locked` has nothing to
work with. The same revision can compile into a different binary months from
now. Results here came from `dogwood 1.0.0` at `5063bcc`, built with
`rustc 1.97.1`.

**Tooling.** `uv`, `ruff`, `mypy --strict`, `pytest`, and GitHub Actions, with
one job that needs no Rust and one that builds Dogwood from the pin. Two `ruff`
groups are load-bearing rather than stylistic. `DTZ` bans naive datetimes, since
a window whose meaning depends on the machine's timezone is not a window. `S`
flags every `subprocess` call, which is where the Dogwood engine lives, and each
is silenced individually with a reason so the boundary is annotated instead of
hidden.

## Licence

MIT.
