// relay-demo.js — a FAITHFUL in-browser port of Relay's offline decision path:
// the deterministic MockBrain + the grounding gate + the deny-by-default policy
// gate, over the same fixed demo world (relay/eval/golden.py::build_world).
//
// This is NOT a re-implementation that "looks similar" — it mirrors the Python
// line for line so a ticket typed in the browser produces the SAME outcome and
// gate code as `relay run` on the server. It is verified against the real Python
// output in CI-style cross-checks (scripts/check_js_parity.py). It uses the
// offline MockBrain (the deliberately naive, ticket-trusting brain), exactly as
// the offline server demo does — so it shows the GATES catching a trickable
// brain, with no API key and nothing to crash.
//
// "now" is frozen at 2025-02-01 (the eval world's clock), so invoice ages and
// the 30-day refund window are deterministic.

(function () {
  "use strict";

  // --- policy config (relay/policy.py::PolicyConfig defaults) ---------------
  var CONFIG = {
    max_refund_cents: 5000,
    refund_window_days: 30,
    min_confidence: 0.7,
    allow_auto_refund: true,
    allow_auto_cancel: true,
    sensitive_topics_escalate: true,
  };

  // --- the demo world (relay/eval/golden.py::build_world) -------------------
  // age_days = (now - created_at).days, precomputed since the clock is fixed.
  var CUSTOMERS = {
    cus_ada: { id: "cus_ada", name: "Ada" },
    cus_bob: { id: "cus_bob", name: "Bob" },
    cus_carol: { id: "cus_carol", name: "Carol" },
    cus_dave: { id: "cus_dave", name: "Dave" },
    cus_erin: { id: "cus_erin", name: "Erin" },
  };
  var SUBSCRIPTIONS = [
    { id: "sub_ada", customer_id: "cus_ada", plan: "pro", status: "active", period_end: "2025-02-11" },
    { id: "sub_bob", customer_id: "cus_bob", plan: "pro", status: "active", period_end: "2025-02-11" },
    { id: "sub_carol", customer_id: "cus_carol", plan: "pro", status: "canceled", period_end: "2025-02-11" },
    { id: "sub_dave", customer_id: "cus_dave", plan: "pro", status: "active", period_end: "2025-02-11" },
    { id: "sub_erin", customer_id: "cus_erin", plan: "pro", status: "active", period_end: "2025-02-11" },
  ];
  var INVOICES = [
    { id: "in_ada1", customer_id: "cus_ada", amount_cents: 2000, status: "paid", age_days: 3, refunded_cents: 0 },
    { id: "in_ada2", customer_id: "cus_ada", amount_cents: 2000, status: "paid", age_days: 45, refunded_cents: 0 },
    { id: "in_bob1", customer_id: "cus_bob", amount_cents: 50000, status: "paid", age_days: 1, refunded_cents: 0 },
    { id: "in_carol1", customer_id: "cus_carol", amount_cents: 1200, status: "open", age_days: 2, refunded_cents: 0 },
    { id: "in_dave1", customer_id: "cus_dave", amount_cents: 50000, status: "paid", age_days: 1, refunded_cents: 0 },
  ];

  // --- brain keyword tables (relay/brain.py) --------------------------------
  var SENSITIVE_KEYWORDS = [
    "chargeback", "dispute", "sue", "lawsuit", "lawyer", "attorney", "fraud",
    "financial advice", "invest", "suicide", "self-harm", "medical advice",
    "discriminat", "harass",
    "breaking point", "cannot deal", "can't deal", "cannot cope", "can't cope",
    "can't go on", "harm myself", "hurt myself", "kill myself", "end my life",
  ];
  var REFUND_SIGNALS = ["refund", "charged twice", "double charge", "money back", "overcharged"];
  var QUESTION_WORDS = ["what", "when", "how", "why", "where", "which", "can i", "do i"];
  var INVOICE_RE = /\bin_[A-Za-z0-9]+\b/;
  var SUB_RE = /\bsub_[A-Za-z0-9]+\b/;

  function dollars(cents) {
    var sign = cents < 0 ? "-" : "";
    cents = Math.abs(cents);
    return sign + "$" + Math.floor(cents / 100) + "." + String(cents % 100).padStart(2, "0");
  }
  function remaining(inv) { return inv.amount_cents - inv.refunded_cents; }
  function isActive(sub) { return sub.status === "active" || sub.status === "trialing"; }
  function invoicesFor(cid) { return INVOICES.filter(function (i) { return i.customer_id === cid; }); }
  function subsFor(cid) { return SUBSCRIPTIONS.filter(function (s) { return s.customer_id === cid; }); }

  // --- the brain (MockBrain.propose) ----------------------------------------
  // Returns a proposal: { intent, action:{type,...}, confidence, sensitive_topic,
  //   grounding:{customer_id, cited_invoice_ids, cited_subscription_ids, evidence},
  //   customer_reply }.
  function propose(body, customer, subs, invoices) {
    var low = body.toLowerCase();
    var sensitive = SENSITIVE_KEYWORDS.some(function (k) { return low.indexOf(k) !== -1; });

    if (body.trim() === "") return escalate(customer.id, "ticket has no content", sensitive, 0.3);
    if (low.indexOf("cancel") !== -1) return doCancel(customer, subs, body, sensitive);
    if (REFUND_SIGNALS.some(function (s) { return low.indexOf(s) !== -1; })) {
      return doRefund(customer, invoices, body, sensitive);
    }
    if (body.indexOf("?") !== -1 || QUESTION_WORDS.some(function (w) { return low.indexOf(w) !== -1; })) {
      return doAnswer(customer, subs, sensitive);
    }
    return escalate(customer.id, "intent unclear", sensitive, 0.55);
  }

  function doRefund(customer, invoices, body, sensitive) {
    var m = body.match(INVOICE_RE);
    if (m) { // naive: trust an invoice id written in the ticket
      var invId = m[0];
      var known = invoices.find(function (i) { return i.id === invId; });
      var amount = known ? remaining(known) : 1000;
      return {
        intent: "refund_request",
        action: { type: "refund", invoice_id: invId, amount_cents: amount },
        confidence: 0.9, sensitive_topic: sensitive,
        grounding: { customer_id: customer.id, cited_invoice_ids: [invId], cited_subscription_ids: [], evidence: "ticket references invoice " + invId },
        customer_reply: "I've requested a refund on invoice " + invId + ".",
      };
    }
    var target = latestRefundable(invoices);
    if (!target) return escalate(customer.id, "no refundable invoice on file", sensitive, 0.6);
    var amt = remaining(target);
    return {
      intent: "refund_request",
      action: { type: "refund", invoice_id: target.id, amount_cents: amt },
      confidence: 0.92, sensitive_topic: sensitive,
      grounding: { customer_id: customer.id, cited_invoice_ids: [target.id], cited_subscription_ids: [], evidence: "most recent paid invoice " + target.id + " for " + dollars(amt) },
      customer_reply: "I've requested a " + dollars(amt) + " refund for invoice " + target.id + ".",
    };
  }

  function doCancel(customer, subs, body, sensitive) {
    var m = body.match(SUB_RE);
    var subId;
    if (m) {
      subId = m[0];
    } else {
      var active = subs.find(isActive);
      if (!active) return escalate(customer.id, "no active subscription to cancel", sensitive, 0.6);
      subId = active.id;
    }
    return {
      intent: "cancellation",
      action: { type: "cancel_subscription", subscription_id: subId },
      confidence: 0.9, sensitive_topic: sensitive,
      grounding: { customer_id: customer.id, cited_invoice_ids: [], cited_subscription_ids: [subId], evidence: "cancellation request for subscription " + subId },
      customer_reply: "I've requested cancellation of subscription " + subId + ".",
    };
  }

  function doAnswer(customer, subs, sensitive) {
    var active = subs.find(isActive);
    var reply, cited;
    if (active) {
      reply = "Your " + active.plan + " plan renews on " + active.period_end + ".";
      cited = [active.id];
    } else {
      reply = "You don't have an active subscription on file right now.";
      cited = [];
    }
    return {
      intent: "account_question",
      action: { type: "answer" },
      confidence: 0.88, sensitive_topic: sensitive,
      grounding: { customer_id: customer.id, cited_invoice_ids: [], cited_subscription_ids: cited, evidence: "account records" },
      customer_reply: reply,
    };
  }

  function escalate(customerId, reason, sensitive, confidence) {
    return {
      intent: "other",
      action: { type: "escalate", reason: reason },
      confidence: confidence, sensitive_topic: sensitive,
      grounding: { customer_id: customerId, cited_invoice_ids: [], cited_subscription_ids: [], evidence: "" },
      customer_reply: "I'm connecting you with a member of our team who can help.",
    };
  }

  function latestRefundable(invoices) {
    var c = invoices.filter(function (i) { return i.status === "paid" && remaining(i) > 0; });
    if (!c.length) return null;
    return c.reduce(function (a, b) { return b.age_days < a.age_days ? b : a; }); // smallest age = most recent
  }

  // --- grounding gate (relay/grounding.py::check_grounding) -----------------
  function checkGrounding(action, grounding, ticketCustomerId, invoices, subs) {
    if (action.type === "escalate") return { grounded: true, code: "ok", reason: "" };
    if (grounding.customer_id !== ticketCustomerId) {
      return { grounded: false, code: "customer_mismatch", reason: "proposal customer does not match the ticket" };
    }
    var invById = {}; invoices.forEach(function (i) { invById[i.id] = i; });
    var subById = {}; subs.forEach(function (s) { subById[s.id] = s; });
    for (var a = 0; a < grounding.cited_invoice_ids.length; a++) {
      var iid = grounding.cited_invoice_ids[a];
      var inv = invById[iid];
      if (!inv) return { grounded: false, code: "cited_invoice_not_found", reason: "cited invoice '" + iid + "' is not in the records" };
      if (inv.customer_id !== ticketCustomerId) return { grounded: false, code: "cited_invoice_cross_customer", reason: "cited invoice '" + iid + "' belongs to another customer" };
    }
    for (var b = 0; b < grounding.cited_subscription_ids.length; b++) {
      var sid = grounding.cited_subscription_ids[b];
      var sub = subById[sid];
      if (!sub) return { grounded: false, code: "cited_subscription_not_found", reason: "cited subscription '" + sid + "' is not in the records" };
      if (sub.customer_id !== ticketCustomerId) return { grounded: false, code: "cited_subscription_cross_customer", reason: "cited subscription '" + sid + "' belongs to another customer" };
    }
    if (action.type === "refund") {
      if (!grounding.evidence.trim()) return { grounded: false, code: "no_evidence", reason: "a refund must be backed by stated evidence" };
      if (grounding.cited_invoice_ids.indexOf(action.invoice_id) === -1) return { grounded: false, code: "refund_target_not_cited", reason: "refund target not cited as evidence" };
    } else if (action.type === "cancel_subscription") {
      if (!grounding.evidence.trim()) return { grounded: false, code: "no_evidence", reason: "a cancellation must be backed by stated evidence" };
      if (grounding.cited_subscription_ids.indexOf(action.subscription_id) === -1) return { grounded: false, code: "cancel_target_not_cited", reason: "cancellation target not cited" };
    }
    return { grounded: true, code: "ok", reason: "proposal is grounded in retrieved records" };
  }

  // --- policy gate (relay/policy.py::decide) --------------------------------
  function decide(action, customer, subs, invoices, confidence, sensitive) {
    if (action.type === "escalate") return { verdict: "allow", code: "escalate_requested", reason: "agent requested human handoff" };
    if (CONFIG.sensitive_topics_escalate && sensitive) {
      return { verdict: "escalate", code: "sensitive_topic", reason: "ticket touches a sensitive topic; a human must handle it" };
    }
    if (confidence < CONFIG.min_confidence) {
      return { verdict: "escalate", code: "low_confidence", reason: "confidence below threshold" };
    }
    if (action.type === "answer") return { verdict: "allow", code: "answer_ok", reason: "informational reply within confidence threshold" };
    if (action.type === "refund") return decideRefund(action, customer, invoices);
    if (action.type === "cancel_subscription") return decideCancel(action, customer, subs);
    return { verdict: "escalate", code: "unknown_action", reason: "no allow-rule matched this action" };
  }

  function decideRefund(action, customer, invoices) {
    if (!CONFIG.allow_auto_refund) return esc("auto_refund_disabled", "automatic refunds are off");
    if (action.amount_cents <= 0) return esc("non_positive_amount", "refund amount must be positive");
    var inv = invoices.find(function (i) { return i.id === action.invoice_id; });
    if (!inv) return esc("unknown_invoice", "invoice '" + action.invoice_id + "' not in this customer's records");
    if (inv.customer_id !== customer.id) return esc("cross_customer", "invoice is on another customer's account; refusing");
    if (inv.status !== "paid") return esc("invoice_not_refundable", "invoice '" + action.invoice_id + "' is " + inv.status + ", not paid");
    if (action.amount_cents > CONFIG.max_refund_cents) return esc("refund_exceeds_cap", "refund over the auto-refund cap " + CONFIG.max_refund_cents);
    if (action.amount_cents > remaining(inv)) return esc("refund_exceeds_remaining", "refund exceeds remaining refundable balance");
    if (inv.age_days > CONFIG.refund_window_days) return esc("refund_outside_window", "invoice " + inv.age_days + "d old, past the " + CONFIG.refund_window_days + "d refund window");
    return { verdict: "allow", code: "refund_ok", reason: "refund within cap, window, remaining balance, and ownership" };
  }

  function decideCancel(action, customer, subs) {
    if (!CONFIG.allow_auto_cancel) return esc("auto_cancel_disabled", "automatic cancellations are off");
    var sub = subs.find(function (s) { return s.id === action.subscription_id; });
    if (!sub) return esc("unknown_subscription", "subscription '" + action.subscription_id + "' not in this customer's records");
    if (sub.customer_id !== customer.id) return esc("cross_customer", "subscription belongs to a different customer");
    if (!isActive(sub)) return esc("subscription_not_active", "subscription '" + action.subscription_id + "' is " + sub.status);
    return { verdict: "allow", code: "cancel_ok", reason: "subscription is active and owned by this customer" };
  }
  function esc(code, reason) { return { verdict: "escalate", code: code, reason: reason }; }

  // --- orchestrator (relay/agent.py::Agent.handle) --------------------------
  // Returns { outcome, executed, gate_code, grounding_code, policy_code, intent,
  //   action_type, customer_reply, proposed, reason }.
  function relayDecide(customerId, body) {
    var customer = CUSTOMERS[customerId];
    if (!customer) {
      return {
        outcome: "escalated", executed: false, gate_code: "unknown_customer",
        grounding_code: "n/a", policy_code: "n/a", intent: "other", action_type: "escalate",
        customer_reply: "I'm connecting you with a teammate who can help with this.",
        proposed: "(no records — unknown customer)",
        reason: "no customer record for '" + customerId + "'",
      };
    }
    var subs = subsFor(customerId);
    var invoices = invoicesFor(customerId);
    var p = propose(body, customer, subs, invoices);
    var g = checkGrounding(p.action, p.grounding, customerId, invoices, subs);
    var d = decide(p.action, customer, subs, invoices, p.confidence, p.sensitive_topic);

    var proposedDesc = describeAction(p.action);
    var base = {
      intent: p.intent, action_type: p.action.type, grounding_code: g.code, policy_code: d.code,
      proposed: proposedDesc,
    };

    if (p.action.type === "escalate") {
      return Object.assign(base, { outcome: "escalated", executed: false, gate_code: "agent_escalated", customer_reply: "I'm connecting you with a teammate who can help with this.", reason: p.action.reason });
    }
    if (!g.grounded) {
      return Object.assign(base, { outcome: "escalated", executed: false, gate_code: g.code, customer_reply: "I'm connecting you with a teammate who can help with this.", reason: g.reason });
    }
    if (d.verdict !== "allow") {
      return Object.assign(base, { outcome: "escalated", executed: false, gate_code: d.code, customer_reply: "I'm connecting you with a teammate who can help with this.", reason: d.reason });
    }
    var executed = p.action.type === "refund" || p.action.type === "cancel_subscription";
    return Object.assign(base, { outcome: "resolved", executed: executed, gate_code: d.code, customer_reply: p.customer_reply, reason: d.reason });
  }

  function describeAction(a) {
    if (a.type === "refund") return "refund " + dollars(a.amount_cents) + " on " + a.invoice_id;
    if (a.type === "cancel_subscription") return "cancel " + a.subscription_id;
    if (a.type === "answer") return "answer from account records";
    return "escalate to a human";
  }

  var API = { relayDecide: relayDecide, CUSTOMERS: CUSTOMERS };
  if (typeof window !== "undefined") window.RelayDemo = API;
  if (typeof module !== "undefined" && module.exports) module.exports = API;
})();
