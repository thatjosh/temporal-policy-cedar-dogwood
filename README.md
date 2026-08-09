# temporal-policy-cedar-dogwood

An experiment in writing **temporal constraints** — authorization rules about
what has already happened — in two engines: [Cedar](https://www.cedarpolicy.com/)
and [Dogwood](https://github.com/dogwood-policy/dogwood), the temporal superset
of Cedar that AWS open-sourced in August 2026.

One rule, implemented twice, tested by the same cases, so the difference between
the two is the measurement.

> **Under construction.** The workspace is in place and both engines are wired
> up; the two implementations land next.

## What is being tested

A support agent can issue refunds. Finance caps what it may do unsupervised, and
the cap is enforced by a policy engine rather than by application code.

|  | The rule | Kind |
|---|---|---|
| **v1** | A single payment may not exceed **$100.00** | ordinary |
| **v2** | v1, **plus**: payments on one order may not exceed **$100.00 in any rolling 60 minutes** | **temporal** |

v1 is the rule most policy engines are built for: everything it needs is in the
request in front of it. v2 is not. Answering it means knowing what was paid
before, and a policy engine is usually built to have no memory at all — you hand
it a request, it judges that request, nothing carries over.

That gap matters because agents split work into steps. An agent handed a $500
refund it cannot pay at once can pay $100 five times, and every single payment
is inside the cap. The rule is never broken; it is satisfied five times, and
$500 goes out. Only a temporal rule catches it.

**The finding this repo exists to demonstrate:** Dogwood can state v2 in the
policy file, because its policies read an event log. Cedar cannot — a Cedar
decision is a pure function of the request, the policies and the entity store,
and none of those is history. So the rule splits: your code computes the rolling
total, the policy compares it to the cap, and from then on the rule only holds
if both halves agree. What that costs, in files and in what can be tested, is
what gets measured here.

## Setup

Three commands from a fresh clone:

    uv sync         # Python, dependencies, virtualenv
    make dogwood    # fetch and compile the Dogwood engine into .tools/
    make check      # lint, types, and the full suite

You need [uv](https://docs.astral.sh/uv/) and a Rust toolchain. Python is pinned
in `.python-version` and uv fetches it for you; if `cargo` is missing, `make
dogwood` says how to get it and stops. If you have rustup but `cargo` is not on
your `PATH` — common, since rustup adds it through a shell profile that
non-interactive shells never read — `make` finds it in `~/.cargo/bin` anyway.

`make dogwood` clones the pinned revision into `.tools/` (gitignored) and builds
it there. Clone and release build together take about a minute on an M-series
Mac. Nothing is installed system-wide, there is no `PATH` to edit, and a second
run is a no-op. The suite looks in `.tools/` before `PATH`; setting
`DOGWOOD_BIN` overrides both and is then authoritative, so you always know which
engine produced a result.

No Rust toolchain and don't want one? `make test-cedar` runs the half that needs
no engine.

### Why Dogwood needs a second command

Cedar is a Python library: `uv sync` installs it and there is nothing else to
do. Dogwood ships **no Python binding** and publishes **no release binaries**,
so the engine must be compiled from source before it can be asked anything, and
it is driven as a subprocess rather than called.

That asymmetry is the first thing this experiment turns up, and you meet it in
the setup instructions before reading a line of code: Cedar is a line in
`pyproject.toml`; Dogwood cannot be one.

## Commands

| Command | What it does |
|---|---|
| `make check` | lint, types, and the full test suite — run this before a PR |
| `make test` | the whole suite; **requires** the Dogwood engine |
| `make test-cedar` | only the half that needs no engine |
| `make lint` | `ruff check` and `ruff format --check` |
| `make types` | `mypy --strict` |
| `make fmt` | apply `ruff` fixes and formatting |
| `make dogwood` | build the pinned engine into `.tools/` |
| `make clean` | drop the built engine, keep the clone and build cache |

The Dogwood tests **fail loudly** when the engine is missing rather than
skipping. A suite that reports success having never asked the engine anything is
worse than a red one. Use `make test-cedar` when you knowingly want the other
half.

## Notes

### There is no LLM here

No API calls, no model, no `anthropic` dependency. The agent behaviour this repo
exists to police — splitting one large payment into several small legal ones —
is represented by fixed sequences of payments in the tests. Everything else is
real: Cedar and Dogwood are the actual engines, running the actual policy files
in this repo, and every result comes from a run.

### What is pinned, and what is not

`make dogwood` and CI build one fixed Dogwood revision, and the compiler version
is pinned alongside it. That is as far as it goes, and the gap is worth stating
rather than implying a repeatability this repo does not have:

- **Pinned** — the Dogwood revision (`DOGWOOD_REV` in the `Makefile`, read by CI
  so there is only one copy), the Rust toolchain, the Python version, and every
  Python dependency via `uv.lock`.
- **Not pinned** — Dogwood's own Rust dependencies. Upstream commits no
  `Cargo.lock`, so `cargo` re-resolves the transitive tree on every cold build
  and `--locked` has nothing to lock against. The same revision can therefore
  compile into a materially different binary months from now.

Results here were produced against `dogwood 1.0.0` at revision `5063bcc`, built
with `rustc 1.97.1`. If you reproduce them and get something else, that gap is
the first place to look.

### Tooling

`uv` for packaging, `ruff` for lint and format, `mypy --strict` for types,
`pytest` for tests, GitHub Actions for CI — one job without Rust, one that
builds Dogwood from the pinned revision.

Two `ruff` rule groups are load-bearing rather than stylistic. **`DTZ`** bans
naive datetimes: a rolling window whose meaning depends on the machine's
timezone is not a rolling window. **`S`** flags every `subprocess` call, which is
exactly where the Dogwood engine lives — each is silenced individually with a
written reason, so the subprocess boundary ends up annotated instead of hidden.

The `Makefile` is mostly a task menu rather than a build system: most targets are
`.PHONY`, names for commands you would otherwise type. The exception is the
Dogwood engine, a genuine file target — built once, rebuilt when the pin
changes, otherwise left alone.

## Licence

MIT.
