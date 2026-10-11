# ADR 0000: Project Thesis as Architectural North Star

**Status:** Accepted  
**Date:** 2026-10-11

## Context

This project exists to demonstrate senior-level financial system engineering.
Without a guiding principle, scope expands, tools accumulate, and the system
drifts toward "impressive" rather than "defensible."

## Decision

Adopt the following thesis as the decision filter for all architectural choices:

> I build financial systems where every number can be traced to an event,
> every event can be replayed, and every balance can be reconciled against
> an external source of truth. My work is defensible under audit because
> correctness is architectural, not documented after the fact.

## Consequences

- Every feature must serve traceability, replayability, reconciliation,
  audit-defensibility, or correctness-by-construction.
- Tools that do not serve the thesis are rejected.
- Scope is bounded by the thesis, not by curiosity.
- The thesis is referenced in the README, architecture doc, and every
  subsequent ADR.

## Alternatives Considered

- **No thesis**: Rejected. Leads to unbounded scope and tool accumulation.
- **Thesis focused on "modern stack"**: Rejected. The differentiator is
  financial correctness, not technology fashion.
- **Thesis focused on "AI/ML"**: Rejected. ML is an application of this
  system, not its purpose.
