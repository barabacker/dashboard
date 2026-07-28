# New Service Architecture Guidance

Use this as a baseline for new services.

## Default approach

Start new services as a simple modular service / modular monolith internally.

Use one deployable service by default, with clear internal module boundaries.

Split into separate services only when operational, ownership, scaling, deployment, data
ownership, security, or failure-boundary reasons justify it.

Use DDD-lite as a thinking tool:
- understand the domain language
- identify entities, value-like concepts, states and transitions
- define invariants
- separate user errors from system errors
- make the source of truth explicit

Do not apply heavyweight DDD patterns unless the domain complexity justifies them.

## Default boundaries

Separate:

- API / transport
- application use cases
- domain rules
- persistence
- external clients
- infrastructure/configuration
- background jobs/workers
- observability
- tests

Domain rules should not depend on the web framework, database sessions, HTTP clients, queues or
framework lifecycle.

## Suggested structure

Adapt to repository conventions and the project's framework (Django, FastAPI, etc.) when they
exist. A FastAPI-style layout is shown as one example; the same layering maps onto other stacks.

    app/
      api/
        routes/
        schemas/
      use_cases/
      domain/
      db/
        models/
        repositories/
      clients/
      workers/
      core/
        config.py
        logging.py
      errors/
      main.py
      lifespan.py

    tests/
      unit/
      integration/

    docs/
      architecture/
      operations/

For a Django project, the same boundaries typically map to: apps for bounded contexts,
`models.py` for persistence, plain modules for domain rules and use cases, management commands
for workers/schedulers, and `admin.py`/views for transport — keeping domain rules out of
framework glue.

## Layer rules

API / transport layer:
- parse requests
- validate transport-level input
- call use cases
- map domain/application errors to responses

Use case layer:
- orchestrate domain logic
- coordinate repositories and clients
- manage transaction boundaries
- keep business flow readable

Domain layer:
- hold domain rules, invariants, state transitions
- avoid framework dependencies
- prefer pure functions where practical

Persistence layer:
- hide database details
- expose explicit methods
- do not leak ORM details into domain rules unnecessarily

Client layer:
- isolate external service contracts
- define timeouts, retries, errors and fallback behavior

Infrastructure layer:
- config
- logging
- metrics
- startup/shutdown
- wiring

## Architecture decision

For each new service, create:

    docs/architecture/adr/0001-architecture-baseline.md

It should explain:
- chosen style
- why this style is enough
- alternatives considered
- module boundaries
- data ownership
- integration boundaries
- testing strategy
- known risks

## Engineering checks

Before implementing, answer:

- What is the service responsible for?
- What is explicitly out of scope?
- What is the source of truth?
- What are the main states and transitions?
- What invariants must always hold?
- What operations must be idempotent?
- What can fail partially?
- What must be observable?
- What tests prove the important behavior?

## Avoid

- framework-driven domain logic
- global mutable state
- hidden side effects
- premature abstraction
- generic repositories without purpose
- deep inheritance
- magic lifecycle coupling
- mixing validation, persistence, transport and business rules in one function

## Prefer

- explicit dependencies
- small modules
- clear inputs and outputs
- composition
- pure domain logic where practical
- side effects at boundaries
- tests for important rules
- logs/metrics for production behavior
- short ADRs for architectural decisions

## Summary rule

Default to a modular monolith inside one service.
Split services only for real operational, ownership, scaling, deployment, data, security, or
failure-boundary reasons.
Do not split just because the architecture looks more "microservice-like".
