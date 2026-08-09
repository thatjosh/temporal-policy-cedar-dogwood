// Payment guardrails, v1. Every rule about money is in this file.
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
// The `has` guard is load-bearing. Cedar skips any policy whose condition
// raises, so an unguarded read of a missing attribute makes this guardrail
// vanish and the payment is ALLOWED. Guarded, the forbid fires and we deny.
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
