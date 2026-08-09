// Payment guardrails, v1. Every rule about money is in this file, and the file
// is the complete answer to "what is this agent allowed to do?".
//
// Cedar is default-deny and a forbid always beats a permit, so the shape is one
// narrow permit that opens the door and one forbid per guardrail, each of which
// no later permit can defeat.

// The support agent may pay against this customer's orders.
//
// Scoping the resource to `in Customer::"cus-100"` does real work. An order the
// system has never heard of belongs to no customer, so it matches no permit and
// is denied by default. A bare `resource` here would authorise payments against
// order ids that do not exist.
@id("agent-may-pay")
permit (
  principal == Agent::"support-bot",
  action == Action::"pay",
  resource in Customer::"cus-100"
);

// A payment moves money to the customer. Zero moves nothing, and a negative
// amount is a charge against them, so neither is a payment this agent may make.
//
// The `context has amount_cents` guard is load-bearing rather than defensive
// noise. Cedar skips any policy whose condition raises an error, so reading
// `context.amount_cents` from a request that omits it would make this guardrail
// silently vanish, and the payment would be ALLOWED. With the guard, a missing
// amount makes the `unless` body false, the forbid fires, and we deny.
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

// Finance's cap on what the agent may pay without a human. Inclusive, so
// $100.00 exactly is allowed.
//
// The limit is written here as a literal and read from nothing, so there is no
// input an agent could supply that raises its own ceiling.
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
