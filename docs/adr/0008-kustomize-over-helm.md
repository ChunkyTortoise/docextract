# ADR-0008: Kustomize over Helm for Kubernetes Deployment

**Status**: Accepted
**Date**: 2026-03

## Context

DocExtract requires Kubernetes manifests for production deployment across two environments (base and production overlay). Options: Helm (chart templating) or Kustomize (patch-based overlays).

## Decision

Use Kustomize (built into `kubectl`) for Kubernetes manifest management rather than Helm charts.

## Consequences

**Why:** DocExtract is a single-application deployment with two environments. Kustomize handles this with a base directory and an `overlays/production/` patch — no templating language, no chart packaging, no `values.yaml` indirection. Operators can read the base YAML and understand the full deployment without learning Helm's Go templating syntax. Kustomize is included in `kubectl` (v1.14+), so there is zero additional tooling to install.

**Tradeoff:** Helm is the de-facto standard for distributing third-party applications and has a larger ecosystem (Artifact Hub, chart repositories). For DocExtract's use case — deploying one specific application to environments we control — chart distribution is irrelevant. If DocExtract were packaged as a product that users install into their own clusters, Helm would be the right choice at that point.
