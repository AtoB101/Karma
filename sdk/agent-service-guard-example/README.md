# SDK Example: Agent Service Guard

This directory contains public-safe SDK usage examples for the Karma Guard
flow. It demonstrates data contract usage and reserved private risk interfaces.

## Example scope

- Build `Service` and `Order` payloads.
- Build `EvidenceBundle` payload and compute local hash placeholder.
- Call reserved private endpoints:
  - `/risk/check`
  - `/dispute/recommend-resolution`
  - `/score/seller`

## Private logic boundary

The SDK example does not implement private scoring, anti-fraud logic, or
arbitration weights. It only consumes outputs from private engine endpoints.
