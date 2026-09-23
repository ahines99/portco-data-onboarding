# Data contracts

Generated from the Pydantic models by `scripts/gen_data_contracts.py`; do not edit by hand.
JSON Schemas live in `contracts/` and a test fails if they drift from the models.

Every persisted contract carries `schema_version`. No contract has a field that can carry row values.

## `Evidence` (evidence)

A persisted record of one read from a source. The payload holds aggregates only.

| field | type | required | description |
|---|---|---|---|
| `evidence_id` | string (uuid) |  |  |
| `source_uri` | string | yes |  |
| `source_type` | string | yes |  |
| `as_of` | string (date-time) \| null |  |  |
| `retrieved_at` | string (date-time) |  |  |
| `content_hash` | string | yes |  |
| `payload` | object |  |  |
| `schema_version` | `1` |  |  |

## `EvidenceRef` (evidence_ref)

| field | type | required | description |
|---|---|---|---|
| `source_id` | string | yes |  |
| `uri` | string | yes |  |
| `retrieved_at` | string (date-time) | yes |  |
| `as_of` | string (date-time) \| null |  |  |
| `excerpt_hash` | string \| null |  |  |

## `Finding` (finding)

| field | type | required | description |
|---|---|---|---|
| `finding_id` | string (uuid) |  |  |
| `code` | string | yes |  |
| `finding_type` | FindingType |  |  |
| `title` | string | yes |  |
| `statement` | string | yes |  |
| `confidence` | Confidence | yes |  |
| `status` | FindingStatus |  |  |
| `evidence` | list[EvidenceRef] |  |  |
| `assumptions` | list[string] |  |  |
| `metadata` | object |  |  |
| `schema_version` | `1` |  |  |

## `AuditEvent` (audit_event)

| field | type | required | description |
|---|---|---|---|
| `run_id` | string (uuid) | yes |  |
| `step` | string | yes |  |
| `event_type` | string | yes |  |
| `actor` | string | yes |  |
| `created_at` | string (date-time) |  |  |
| `payload` | object |  |  |
| `event_id` | integer \| null |  |  |
| `prev_hash` | string \| null |  |  |
| `event_hash` | string \| null |  |  |
| `schema_version` | `1` |  |  |

## `ConnectionCheck` (connection_check)

| field | type | required | description |
|---|---|---|---|
| `connection_id` | string | yes |  |
| `company_id` | string | yes |  |
| `reachable` | boolean | yes |  |
| `read_only_verified` | boolean | yes |  |
| `schemas_visible` | list[string] | yes |  |
| `tables_visible` | integer | yes |  |
| `source_fingerprint` | string | yes |  |
| `engine_version` | string | yes |  |
| `evidence_id` | string (uuid) \| null |  |  |
| `schema_version` | `1` |  |  |

## `SchemaProfile` (schema_profile)

| field | type | required | description |
|---|---|---|---|
| `profile_id` | string (uuid) |  |  |
| `connection_id` | string | yes |  |
| `company_id` | string | yes |  |
| `source_fingerprint` | string | yes |  |
| `tables` | list[TableProfile] | yes |  |
| `schema_version` | `1` |  |  |

## `EntityInference` (entity_inference)

| field | type | required | description |
|---|---|---|---|
| `candidates` | list[EntityCandidate] | yes |  |
| `overlaps` | list[EntityOverlap] |  |  |
| `schema_version` | `1` |  |  |

## `JoinGraph` (join_graph)

| field | type | required | description |
|---|---|---|---|
| `joins` | list[JoinCandidate] | yes |  |
| `schema_version` | `1` |  |  |

## `MappingSet` (mapping_set)

| field | type | required | description |
|---|---|---|---|
| `mapping_id` | string (uuid) |  |  |
| `proposals` | list[MappingProposal] | yes |  |
| `row_filters` | list[RowFilter] |  |  |
| `joins` | list[JoinCandidate] |  |  |
| `entity_tables` | object |  | table -> canonical entity |
| `primary_tables` | object |  | entity -> system-of-record table |
| `unmapped_required` | list[UnmappedField] |  |  |
| `metrics_needing_evidence` | list[string] |  |  |
| `schema_version` | `1` |  |  |

## `ResolvedMapping` (resolved_mapping)

Output of the mapping-review gate: what artifact generation is allowed to use.

| field | type | required | description |
|---|---|---|---|
| `mapping_hash` | string | yes |  |
| `accepted` | list[AcceptedMapping] | yes |  |
| `filters` | list[RowFilter] | yes |  |
| `joins` | list[JoinCandidate] | yes |  |
| `entity_tables` | object | yes |  |
| `primary_tables` | object | yes |  |
| `rejected_keys` | list[string] |  |  |
| `approval_ids` | list[string (uuid)] |  |  |
| `metrics_needing_evidence` | list[string] |  |  |
| `schema_version` | `1` |  |  |

## `ReviewItem` (review_item)

| field | type | required | description |
|---|---|---|---|
| `item_key` | string | yes |  |
| `gate` | ReviewGate | yes |  |
| `kind` | `mapping` \| `row_filter` \| `join` \| `bundle` \| `metric` \| `test_failure` | yes |  |
| `summary` | string | yes |  |
| `reason_codes` | list[string] |  |  |
| `subject_hash` | string | yes |  |
| `evidence_ids` | list[string (uuid)] |  |  |
| `options` | object |  |  |

## `Approval` (approval)

| field | type | required | description |
|---|---|---|---|
| `approval_id` | string (uuid) |  |  |
| `run_id` | string (uuid) | yes |  |
| `gate` | ReviewGate | yes |  |
| `subject_hash` | string | yes |  |
| `decisions` | list[ItemDecision] | yes |  |
| `reviewer` | string | yes |  |
| `role` | string | yes |  |
| `comment` | string \| null |  |  |
| `created_at` | string (date-time) |  |  |
| `expires_at` | string (date-time) \| null |  |  |
| `revoked_at` | string (date-time) \| null |  |  |
| `revoked_reason` | string \| null |  |  |

## `ArtifactBundle` (artifact_bundle)

| field | type | required | description |
|---|---|---|---|
| `bundle_id` | string (uuid) |  |  |
| `mapping_hash` | string | yes |  |
| `files` | list[ArtifactFile] | yes |  |
| `manifest_hash` | string | yes |  |
| `generated_metrics` | list[string] | yes |  |
| `not_generated` | object |  |  |
| `models` | list[string] |  |  |
| `schema_version` | `1` |  |  |

## `TestReport` (test_report)

| field | type | required | description |
|---|---|---|---|
| `manifest_hash` | string | yes |  |
| `source_fingerprint` | string | yes |  |
| `passed` | boolean | yes |  |
| `dbt_exit_code` | integer | yes |  |
| `dbt_results` | list[DbtResult] | yes |  |
| `reconciliation` | list[ReconciliationCheck] | yes |  |
| `failing_checks` | list[string] |  |  |
| `waived_checks` | list[string] |  |  |
| `cached` | boolean |  |  |
| `duration_seconds` | number |  |  |
| `schema_version` | `1` |  |  |

## `CertificationPacket` (certification_packet)

| field | type | required | description |
|---|---|---|---|
| `run_id` | string (uuid) | yes |  |
| `manifest_hash` | string | yes |  |
| `mapping_hash` | string | yes |  |
| `joins` | list[JoinCandidate] | yes |  |
| `mapping_summary` | object | yes |  |
| `reviewer_overrides` | list[string] | yes |  |
| `metrics` | list[MetricCertification] | yes |  |
| `test_report_passed` | boolean | yes |  |
| `failing_checks` | list[string] | yes |  |
| `waived_checks` | list[string] | yes |  |
| `open_findings` | list[object] | yes |  |
| `evidence_ids` | list[string (uuid)] | yes |  |
| `schema_version` | `1` |  |  |

## `PublishReceipt` (publish_receipt)

| field | type | required | description |
|---|---|---|---|
| `company_id` | string | yes |  |
| `version` | string | yes |  |
| `manifest_hash` | string | yes |  |
| `certification_id` | string (uuid) | yes |  |
| `publisher` | string | yes |  |
| `published_at` | string (date-time) |  |  |
| `path` | string | yes |  |
| `published_metrics` | list[string] | yes |  |
| `excluded_metrics` | list[string] | yes |  |
| `reused` | boolean |  |  |
| `schema_version` | `1` |  |  |
