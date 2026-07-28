# Engineering Principles

Use this as a checklist, not as a long manual.

## Main idea

Do not merely make code work.
Design code so it can be understood, changed, tested, and operated.

Prefer simplicity as lack of unnecessary coupling.

## Simple Made Easy checklist

Before changing code, ask:

- What is the domain model?
- What are the invariants?
- What state exists and who owns it?
- What effects are involved: DB, network, files, queues?
- What should be pure logic?
- What should remain at system boundaries?
- What changes independently?
- What must not be coupled?
- What can be tested directly?

## Avoid complecting

Do not mix unnecessarily:
- domain logic and transport
- data and presentation
- state and computation
- validation and side effects
- domain rules and DB/framework details
- policy and mechanism
- reads and writes
- sync and async behavior
- user errors and infrastructure errors

## Prefer

- explicit dependencies
- small modules with clear inputs and outputs
- composition over inheritance/magic
- pure functions for business rules where practical
- side effects at the boundaries
- explicit state transitions
- idempotency for retryable operations
- tests for important behavior
- observability for production behavior

## Change management

Do not build a universal abstraction too early.
But do not accidentally couple things that are likely to change independently.

## State and time

For async, retries, queues, CDC, migrations, and distributed flows, always consider:
- ordering
- idempotency
- partial failure
- checkpointing
- source of truth
- stale data
- replay
- rollback

## Communication

For non-trivial decisions, leave a short note:
- what was chosen
- why
- alternatives considered
- risks
- validation
