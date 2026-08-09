# A task menu, not a build system.
#
# Most targets here are `.PHONY`, names for commands you would otherwise type
# by hand. It is a build tool used as a command menu, which is worth saying out
# loud rather than implying. The exception is the Dogwood engine, which hangs
# off a genuine file target: built once, then left alone until the pin moves.
#
# `make check` is the reason this file exists: one command that a contributor
# and CI both run, so nobody verifies three things out of four and calls it
# green. `lint`, `types` and `test` are its parts, split out so CI can run the
# Cedar half on a runner with no Rust toolchain. The rest build the engine or
# clean up after it.
#
# A `justfile` or `[tool.poe.tasks]` would each read better and each cost more,
# one an extra install and the other an extra dependency. See the README.

UV ?= uv

# Python invalidates a .pyc by timestamp plus size, and this repo holds tables
# where swapping two strings changes neither. A stale cache then hides a real
# edit from a test run, which has already produced one wrong conclusion here.
export PYTHONDONTWRITEBYTECODE = 1

# --------------------------------------------------------------------------
# The Dogwood engine
#
# Dogwood publishes no release binaries, so the engine has to be compiled. The
# repo does it rather than asking the reader to: see the README on why only one
# of the two engines needs this.
#
# CI runs this same target, so the engine you build locally is the one CI
# measures.
# --------------------------------------------------------------------------

DOGWOOD_REV  ?= 5063bcc2d6d6cf5024d1b0498e6cc8ef52cbcf0c
DOGWOOD_REPO ?= https://github.com/dogwood-policy/dogwood
DOGWOOD      := .tools/bin/dogwood   # tests/conftest.py looks here first

# rustup installs to ~/.cargo/bin but puts it on PATH only via a line in a shell
# profile, which a non-interactive shell (make, an IDE task, a CI step) often
# never reads. Looking there before concluding Rust is absent is the difference
# between "install Rust" and "your Rust is fine, your PATH is not".
CARGO := $(shell command -v cargo 2>/dev/null || echo $(HOME)/.cargo/bin/cargo)

# The stamp carries the revision in its name, so bumping DOGWOOD_REV asks for a
# file that does not exist yet and the engine is rebuilt. Keying on the binary
# alone would make a pin bump a silent no-op locally. CI would rebuild, having
# a revision-sensitive cache key, and only your machine would keep testing the
# old engine.
STAMP := .tools/.built-$(DOGWOOD_REV)

.PHONY: dogwood
dogwood: $(STAMP)

$(STAMP):
	@test -x "$(CARGO)" || { \
	  echo "cargo not found (looked on PATH and in $(HOME)/.cargo/bin)."; \
	  echo "Dogwood publishes no release binaries, so its engine must be compiled."; \
	  echo "Install Rust, then re-run \`make dogwood\`:"; \
	  echo "  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh"; \
	  exit 1; }
	@mkdir -p .tools/bin
	@# Testing for `.git` rather than for the directory, and clearing it first:
	@# a clone interrupted partway leaves .tools/src populated but without a
	@# repository in it, and plain `git clone` then refuses forever because the
	@# destination is non-empty.
	@test -d .tools/src/.git || { rm -rf .tools/src; git clone --quiet $(DOGWOOD_REPO) .tools/src; }
	@# Fetch before checkout, or a pin moved forward names a commit this clone
	@# has never heard of and the bump is impossible without deleting the clone.
	@git -C .tools/src fetch --quiet origin
	@git -C .tools/src checkout --quiet --detach $(DOGWOOD_REV)
	"$(CARGO)" build --release --manifest-path .tools/src/Cargo.toml
	@cp .tools/src/target/release/dogwood $(DOGWOOD)
	@rm -f .tools/.built-*
	@touch $@
	@echo "built $(DOGWOOD) from $(DOGWOOD_REPO) at $(DOGWOOD_REV)"

# --------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------

# Everything CI runs. The one command to type before opening a pull request.
.PHONY: check
check: lint types test

.PHONY: lint
lint:
	$(UV) run ruff check .
	$(UV) run ruff format --check .

.PHONY: types
types:
	$(UV) run mypy

# The whole suite. Needs the engine, and fails loudly without it rather than
# skipping. See tests/conftest.py for why.
#
# Deliberately not declared to depend on the engine: a `make test` that quietly
# spends a minute compiling Rust is a surprise, and it would compile even for
# someone who set DOGWOOD_BIN to a build they already have. Missing engine, you
# get told to run `make dogwood`.
.PHONY: test
test:
	$(UV) run pytest

# The half that needs no engine, for a machine with no Rust toolchain.
.PHONY: test-cedar
test-cedar:
	$(UV) run pytest -m "not dogwood"

.PHONY: fmt
fmt:
	$(UV) run ruff check --fix .
	$(UV) run ruff format .

# CI reads the pin from here rather than keeping a second copy. The README
# quotes it for the reader and is the one place updated by hand.
.PHONY: print-dogwood-rev
print-dogwood-rev:
	@echo $(DOGWOOD_REV)

# Drops the built engine but keeps the clone and its object cache, so the next
# build is incremental rather than a fresh clone and a cold compile.
.PHONY: clean
clean:
	rm -rf .tools/bin .tools/.built-*

.PHONY: distclean
distclean:
	rm -rf .tools
