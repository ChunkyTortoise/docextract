# ADR-0009: Managed Databases (RDS + ElastiCache) for AWS Deployment

**Status**: Accepted
**Date**: 2026-03

## Context

The AWS Terraform deployment needs a PostgreSQL database and a Redis instance. Options: self-hosted containers on EC2, or managed services (Amazon RDS and ElastiCache).

## Decision

Use Amazon RDS (PostgreSQL 16) and Amazon ElastiCache (Redis 7) instead of self-hosted containers on the EC2 instance.

## Consequences

**Why:** Self-hosted SQLite on EC2 cannot run the asyncpg driver DocExtract requires. Self-hosted Postgres in a container loses all data when the instance is replaced. RDS provides automated backups, point-in-time recovery, storage auto-scaling, and multi-AZ failover without operational overhead. ElastiCache provides a Redis endpoint that survives EC2 instance replacement — critical for ARQ job queues that must not lose in-flight jobs on a deploy.

Both services are free-tier eligible (`db.t3.micro` / `cache.t3.micro`) and are deployed in private subnets with security group rules restricting access to EC2 application instances only.

**Tradeoff:** RDS and ElastiCache add ~2-3 minutes to `terraform apply` time and introduce per-hour billing once the free tier is exhausted. The alternative (containers on a single EC2 instance) is simpler but represents a data durability risk that is unacceptable for a system handling document extraction jobs.
