# Changelog

## [Unreleased]

### Changed

- **Webhook `event` values now derive from final job status.** The success-path
  webhook previously always emitted `"event": "job.completed"`. It now emits
  `"event": "job.<status>"` where `<status>` is the final job status string
  (`job.completed` on success : backward compatible : or `job.needs_review`
  when schema validation, business-rule validation, or guardrails route the
  extraction to the review lifecycle). The payload `status` field changes the
  same way. The `job.failed` status is set by the worker's failure handler and
  is not emitted as a webhook event. Downstream consumers matching exactly
  `job.completed` should also accept `job.needs_review` (and treat any
  `job.*` value as the final job status).
