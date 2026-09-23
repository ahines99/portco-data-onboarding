"""Primary onboarding workflow: the nine steps plus the mapping-review gate (POD-402)."""

from __future__ import annotations

from src.domain.models import ReviewGate, StepName
from src.domain.project_models import (
    ArtifactBundle,
    CertificationPacket,
    ConnectionCheck,
    EntityInference,
    JoinGraph,
    MappingSet,
    PublishReceipt,
    ResolvedMapping,
    SchemaProfile,
    TestReport,
)
from src.services import (
    certification,
    connection,
    entities,
    gates,
    generation,
    joins,
    mapping,
    profiling,
    publish,
    sandbox,
)
from src.workflows.base import StepSpec

PROJECT_STEPS: list[StepSpec] = [
    StepSpec(StepName.CONNECTION_VALIDATION, connection.validate_connection, ConnectionCheck, always_execute=True),
    StepSpec(StepName.SCHEMA_PROFILING, profiling.profile_schema, SchemaProfile),
    StepSpec(StepName.ENTITY_INFERENCE, entities.infer_entities, EntityInference),
    StepSpec(StepName.JOIN_INFERENCE, joins.infer_joins, JoinGraph),
    StepSpec(StepName.CANONICAL_MAPPING, mapping.propose_mapping, MappingSet),
    StepSpec(
        StepName.MAPPING_REVIEW,
        gates.mapping_review,
        ResolvedMapping,
        always_execute=True,
        gate=ReviewGate.MAPPING_REVIEW,
        retryable=False,
    ),
    StepSpec(StepName.ARTIFACT_GENERATION, generation.generate_artifacts, ArtifactBundle),
    StepSpec(
        StepName.AUTOMATED_TESTS,
        sandbox.run_automated_tests,
        TestReport,
        always_execute=True,
        gate=ReviewGate.TEST_FAILURES,
    ),
    StepSpec(
        StepName.HUMAN_CERTIFICATION,
        certification.human_certification,
        CertificationPacket,
        always_execute=True,
        gate=ReviewGate.CERTIFICATION,
        retryable=False,
    ),
    StepSpec(StepName.PUBLISH, publish.publish_bundle, PublishReceipt, retryable=False),
]

OUTPUT_TYPES = {s.name: s.output_type for s in PROJECT_STEPS}
