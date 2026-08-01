# Path-safety SDK ownership decision

> Status: accepted
> Date: 2026-08-01
> Applies from: 2.3.1

## Context

Path validation, archive handling, filesystem publication, and process launch all
need the same portable identity rules. Keeping copies in bridge, application,
plugin-host, and tool modules caused the security policy to diverge. The shared
implementation is standard-library-only and does not import Shinsekai host layers.

## Decision

The following modules are stable public SDK submodules:

- `sdk.path_contract` and `sdk.path_references` define portable validation and
  persisted-reference contracts;
- `sdk.file_transactions` provides identity-bound file and directory operations;
- `sdk.archive_paths` provides portable member validation and link-free extraction;
- `sdk.process_launch` provides identity-bound subprocess launch operations.

These modules may depend only on the standard library and other `sdk/` modules.
They do not choose a project root, download source, domain storage directory, or
business overwrite policy on behalf of callers. Host-specific authorization and
domain ownership remain in `core/security/`, `config/`, `application/`, and
`plugin_system/` as appropriate.

The public names are the explicit `__all__` of each module. Breaking or removing a
public name requires a documented deprecation period and a major-version removal
target. New `core.archive_paths`, `core.file_transactions`, and
`core.process_launch` aliases were created only inside the unmerged path-contract
work and have never shipped; they are therefore removed before release instead of
starting a false compatibility surface.

## Enforcement

- Internal production imports use the canonical `sdk.*` modules directly.
- Unit tests for these modules live under `test/unit/sdk/`.
- Architecture tests reject the three unshipped `core.*` aliases and any internal
  import that reintroduces them.
- Application use cases own theme, effect, and plugin-config persistence; bridge
  routes only translate requests and responses.

## Consequences

Plugins can use one documented set of cross-platform safety primitives, while host
layers retain responsibility for deciding which paths and mutations a request is
authorized to perform. The stable public surface is larger, but its dependency and
compatibility rules are now explicit and testable.
