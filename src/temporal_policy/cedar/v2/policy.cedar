// Payment guardrails, v2: everything v1 forbids, plus a cap on the rolling
// total. Every rule about money is here, but the temporal one is only half
// here: its total is summed in v2/ledger.py, because a Cedar decision is a
// function of the request, the policies and the entity store, and history is
// none of those.
//
// Cedar is default-deny and forbid beats permit, so the shape is one narrow
// permit and one forbid per guardrail that no later permit can defeat.

// Scoping to `in Customer::"cus-100"` does real work: an order the system has
// never heard of belongs to no customer, matches no permit, and is denied. A
// bare `resource` would authorise payments against order ids that do not exist.
@id("agent-may-pay")
permit (
  principal == Agent::"support-bot",
  action == Action::"pay",
  resource in Customer::"cus-100"
);

// Zero moves nothing and a negative amount is a charge against the customer.
//
// Cedar skips any policy whose condition raises, so an unguarded read of a
// missing attribute deletes the guardrail and the payment is ALLOWED. Belt and
// braces here, since the schema makes `amount_cents` required; on the optional
// `window` below it is Cedar that refuses to validate an unguarded read.
@id("amount-must-be-positive")
forbid (
  principal,
  action == Action::"pay",
  resource
)
unless {
  context has amount_cents &&
  context.amount_cents > 0
};

// Finance's cap, inclusive, so $100.00 exactly is allowed. A literal read from
// nothing, so no input an agent supplies can raise its own ceiling.
@id("per-payment-cap")
forbid (
  principal,
  action == Action::"pay",
  resource
)
unless {
  context has amount_cents &&
  context.amount_cents <= 10000
};

// A window is usable only if it answers the question being asked: this order,
// and a span as long as the one the ledger filters by. Cedar exposes no `now`,
// so its shape is checkable here but never that the window ends at this payment.
//
// `unless` rather than `when`, as everywhere above: written with `when`, an
// absent window leaves the condition false, the forbid silent, and the payment
// allowed.
@id("rolling-window-must-be-known")
forbid (
  principal,
  action == Action::"pay",
  resource
)
unless {
  context has window &&
  context.window.order == resource &&
  context.window.end.durationSince(context.window.start) == duration("60m")
};

// The cap again, over everything already paid plus this payment, stated as a
// remaining budget rather than a sum so that only 10000 and the ledger's own
// total are in the arithmetic. Adding would put the agent's number there
// instead. Either form can overflow, and an overflowing forbid is skipped,
// which is why `_explain` refuses a verdict reached with errors.
@id("rolling-window-cap")
forbid (
  principal,
  action == Action::"pay",
  resource
)
unless {
  context has window &&
  context.amount_cents <= 10000 - context.window.total_cents
};
