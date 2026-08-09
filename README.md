# temporal-policy-cedar-dogwood

One authorization rule, expressed twice — once in [Cedar](https://www.cedarpolicy.com/)
and once in [Dogwood](https://github.com/dogwood-policy/dogwood) — to show what a
*temporal* constraint costs you in each.

> **Status: under construction.** Phase 1 of 4 (workspace). The Cedar and Dogwood
> implementations land next; this README is completed at the end.

## There is no LLM here

No API calls, no model, no `anthropic` dependency. The agentic behaviour this repo
exists to police — an agent splitting one large payment into several small legal
ones — is represented by fixed sequences of payments in the test suite.

Everything else is real. Cedar and Dogwood are the actual engines, running the
actual policy files in this repo, and every result comes from a run.

## Getting set up

Three commands, from a fresh clone:

    uv sync         # Python, dependencies, virtualenv
    make dogwood    # fetch and compile the Dogwood engine into .tools/
    make check      # lint, types, and the full suite

You need [uv](https://docs.astral.sh/uv/) and a Rust toolchain. Python is pinned
in `.python-version` and uv fetches it for you; if `cargo` is missing, `make
dogwood` tells you how to get it and stops.

`make dogwood` clones the pinned revision into `.tools/` (gitignored) and
compiles it there — clone and release build together take about a minute on an
M-series Mac. Nothing is installed system-wide, there is no `PATH` to edit, and
a second run is a no-op rather than a rebuild. The test suite looks in `.tools/`
before it looks at `PATH`; `export DOGWOOD_BIN=/path/to/dogwood` overrides both.

If you have rustup but `cargo` is not on your `PATH` — common, since rustup adds
it through a shell profile that non-interactive shells never read — `make` finds
it in `~/.cargo/bin` anyway.

### Why the second command exists

Cedar is a Python library: `uv sync` installs it and there is nothing else to do.
Dogwood ships **no Python binding**, and publishes **no release binaries**, so
the engine has to be compiled from source before it can be asked anything.

That asymmetry is this repo's first finding, and you meet it in the setup
instructions before you read a line of code — Cedar is a line in
`pyproject.toml`; Dogwood cannot be one.

No Rust toolchain and don't want one? `make test-cedar` runs the half that needs
no engine.

## Commands

| Command | What it does |
|---|---|
| `make check` | lint, types, and the full test suite — run this before a PR |
| `make test` | the whole suite; **requires** the `dogwood` binary |
| `make test-cedar` | only the half that needs no engine build |
| `make lint` | `ruff check` and `ruff format --check` |
| `make types` | `mypy --strict` |
| `make fmt` | apply `ruff` fixes and formatting |

The Dogwood tests **fail loudly** when the binary is missing rather than skipping.
A suite that reports success having never asked the engine anything is worse than
a red one. Use `make test-cedar` when you knowingly want the other half.

### Why a Makefile

Mostly a task menu rather than a build system: most targets are `.PHONY`, names
for commands you would otherwise type. The exception is the Dogwood engine,
which is a genuine file target — built once, rebuilt when the pinned revision
changes, otherwise left alone.

uv has no task runner, so something has to hold the composite `check` command
that CI and contributors both run; the alternative is everyone verifying three
things out of four and calling it green.

A `justfile` reads better but would add a second "install this first" to a repo
that already asks you to build a Rust binary. `[tool.poe.tasks]` would need no
new file but would add a dependency whose only job is aliasing four commands.
There is no `sync` target because `uv sync` is already one word.

## Tooling

| | |
|---|---|
| Package manager | `uv`, with `uv.lock` committed |
| Lint & format | `ruff` |
| Types | `mypy --strict`, no suppressions |
| Tests | `pytest` |
| CI | GitHub Actions — one job without Rust, one that builds Dogwood from a pinned revision |

Two `ruff` rule groups are load-bearing rather than stylistic. **`DTZ`** bans naive
datetimes: a rolling window whose meaning depends on the machine's timezone is not
a rolling window. **`S`** flags every `subprocess` call, which is exactly where the
Dogwood engine lives — each one is silenced individually with a written reason, so
the subprocess boundary ends up annotated instead of hidden.

### What is pinned, and what is not

`make dogwood` and CI build one fixed Dogwood revision, and the compiler version
is pinned alongside it. That is as far as it goes, and the gap is worth stating
rather than implying repeatability this repo does not have:

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

## Licence

MIT.
