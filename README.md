# Conversation-History Integrity

A standardized evaluation harness for conversation-history integrity
mechanisms: the same attack suite, session structure, judge, and metrics
applied to any defense mechanism that implements one interface.

## Key findings

The harness measured eight mechanism families head-to-head across 3,249
sessions. Integrity verification of stored conversation history is
deterministic and cheap; the open problems are the content and instruction
channels.

- Storage-layer mutation is detected 126 of 126 sessions per model at zero
  false positives.
- Classic prompt-injection defenses flag 35-50 percent of benign sessions:
  pattern-based detection pays a measured false-positive price.
- Provenance-gated instruction gates reach at most 1.2 percent attack
  adoption at zero false positives and zero utility loss.
- Attacks that escape the gates or compose across fragments defeat all
  deployment-layer defenses: the measured boundary of this class of
  mechanisms.

## For practitioners

- Verify stored history and content provenance with deterministic integrity
  checks: zero false positives, no utility loss.
- Gate instruction overrides on delivery metadata (provenance-gated gates),
  not on pattern filters: the filters flag 35-50 percent of benign sessions.
- The escaped and composite attacks above are the measured boundary of
  deployment-layer defenses; they require model-internal or trajectory-level
  mechanisms (see the paper).

Paper: Detectable Epistemic Attack Layers: A Coverage Theorem and
Standardized Harness for Conversation-History Integrity.

Companion (prior research, baseline corpus):
https://github.com/fahrellgiovanny/epistemic-policy-divergence

Full reproduction: see [RUNBOOK.md](RUNBOOK.md)

License: MIT
