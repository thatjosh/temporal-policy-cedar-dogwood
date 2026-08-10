# temporal-policy-cedar-dogwood

[![ci](https://github.com/thatjosh/temporal-policy-cedar-dogwood/actions/workflows/ci.yml/badge.svg)](https://github.com/thatjosh/temporal-policy-cedar-dogwood/actions/workflows/ci.yml)

An experiment in writing **temporal constraints**, meaning authorization rules
about what has already happened, in two engines:
[Cedar](https://www.cedarpolicy.com/) and
[Dogwood](https://github.com/dogwood-policy/dogwood), the temporal superset of
Cedar that AWS open-sourced in August 2026.

One rule, implemented twice, tested by the same cases, so the difference between
the two is the measurement.

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

## What this repo shows

### Cedar keeps the engine stateless, so you hold the state yourself

v1 is a single short policy, and that ease is why Cedar is the default answer
when someone asks what should sit in front of an agent's tools. v2 stops being
easy, and not because the syntax is hard: you cannot write the rule. Part of it
goes in the policy and part in your application code, and from then on it holds
only while both halves agree.

The reason is one property. A Cedar decision is a pure function of three inputs,
the request, the policies and the entity store, and none of them is history. It
cannot look anything up, and it has no count or sum.

That is deliberate rather than an omission. Statelessness is what lets a policy
set be checked by an SMT solver without running it, and Cedar names that
analysis as a design goal. The datetime extension shows how far the commitment
goes: it was accepted and shipped, and a `currentTime()` function was still
turned down inside it, on exactly this ground.

> However, `currentTime()` is stateful, i.e. not pure, and cannot be modeled in
> SMT.
>
> Cedar RFC 0080, datetime extension

So a temporal constraint in Cedar is possible; it just stops living in one
place. You keep the engine stateless and make the input stateful. Your code
queries the ledger, sums what this order paid in the last hour, and hands Cedar
that number as a fact on the request. The policy compares it to the cap.

![Two boxes. On the left, your own code holds the ledger, filters it to this
order and the last sixty minutes, and produces a total of $60. A single arrow
carries that number across into the policy engine on the right, which verifies
the window is for the right order and starts sixty minutes before the request,
but trusts that the total itself is correct.](docs/img/cedar-counts-outside.png)

The engine can check where the number came from. It cannot check the number.
Everything to the left of that arrow is inside the trust boundary, and in Cedar
that is your code.

### Dogwood moves the state into the engine

[Dogwood](https://github.com/dogwood-policy/dogwood) is a temporal superset of
Cedar, open-sourced on 6 August 2026: the same language, plus a kind of clause
that can read an event log. The rolling cap becomes something the policy states
by itself, as one clause appended to the per-payment rule. No new module, and the sixty minutes written once, because
nothing else needs to know it.

The difference is not brevity. There is no second half to keep in sync.

![The same two boxes with the counting relocated. On the left, your event log
holds one record per executed payment. An arrow carries the raw events into the
policy engine, which now computes the total itself, but trusts that every
payment reached the log and that each event carries the fields the rule
names.](docs/img/dogwood-counts-inside.png)

The counting moved inside the boundary, and one line of trust became two. Cedar
trusts one number. Dogwood trusts the entire log it is given.

## Setup

    uv sync         # Python, dependencies, virtualenv
    make dogwood    # fetch and compile the Dogwood engine into .tools/
    make check      # lint, types, and the full suite

You need [uv](https://docs.astral.sh/uv/) and a Rust toolchain. `make dogwood`
clones the pinned revision into `.tools/` and builds it there, which takes about
a minute. Without a Rust toolchain, `make test-cedar` runs the half that needs
no engine.

**Why Dogwood needs its own step.** Cedar is a Python library, so `uv sync`
installs it. [Dogwood](https://github.com/dogwood-policy/dogwood) ships no
Python binding and publishes no release binaries, so it must be compiled from
source and driven as a subprocess. That asymmetry is the first thing this
experiment turns up, and you meet it before reading any code.

The Dogwood tests fail loudly when the engine is missing, rather than skipping.
A suite that reports success having never asked the engine anything is worse
than a red one.

## Where the code is

    src/temporal_policy/
      spec.py            the case table both engines are judged by
      cedar/             gate; v1/ and v2/ hold the policies and v2's ledger
      dogwood/           gate, CLI wrapper, trace writer, ledger; v1/ and v2/
                         hold the policies and schemas

`spec.py` is the place to start: it is the specification, and both engines are
held to it.

## Notes

**There is no LLM here.** No API calls, no model, no `anthropic` dependency. The
behaviour under test, an agent splitting one payment into several legal ones, is
fixed sequences of payments in the tests. Both engines are real, running the
policy files in this repo, and every result comes from a run.

**Pinning the revision does not pin the build.** Upstream commits no
`Cargo.lock`, so `cargo` re-resolves Dogwood's dependency tree on every cold
build and `--locked` has nothing to work with. The same revision can compile
into a different binary months from now.

Every result here came from Dogwood 1.0.0, built with `rustc 1.97.1` from
[dogwood-policy/dogwood@5063bcc](https://github.com/dogwood-policy/dogwood/commit/5063bcc2d6d6cf5024d1b0498e6cc8ef52cbcf0c),
the upstream commit `make dogwood` and CI both build.

## Licence

MIT.
