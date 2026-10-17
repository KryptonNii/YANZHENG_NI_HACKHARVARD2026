"""Recorded id convention: UUID strings validate, and the schema does not require a version.

The name formats match A4's importer. Plain fixture ids stay valid. Visit.patient_share is not a field.
"""

from __future__ import annotations

import uuid

from trialpilot_contracts import Site, TrialDesign, Visit

IMPORTER_NS = uuid.UUID("6f1c3c3e-8a43-4d0e-9b55-1f2a5e0c7a11")
EXTRACTION_NS = uuid.UUID("0b8f5d0e-5a3c-4c55-9f7e-2c1d7a9e4b21")


def test_imported_uuid5_ids_and_plain_fixture_ids_both_validate() -> None:
    design_id = str(uuid.uuid5(IMPORTER_NS, "ctgov:NCT03930732"))
    site_id = str(uuid.uuid5(IMPORTER_NS, "ctgov:NCT03930732:site:boston#1"))
    assert uuid.UUID(design_id).version == 5
    assert uuid.UUID(site_id).version == 5
    imported = TrialDesign(
        id=design_id,
        source="ctgov",
        registry_id="NCT03930732",
        title="Imported",
        enrollment_target=10,
        duration_months=12,
        sites=[Site(id=site_id, name="Boston", country="US")],
        visits=[Visit(number=1, label="V1", week=0)],
    )
    assert imported.id == design_id and imported.sites[0].id == site_id

    app_id = str(uuid.uuid4())
    plain = TrialDesign(
        id="design-test-1",
        source="fixture",
        title="Fixture",
        enrollment_target=10,
        duration_months=12,
        sites=[Site(id="site-1", name="Test", country="US")],
        visits=[Visit(number=1, label="V1", week=0)],
    )
    assert uuid.UUID(app_id).version == 4
    assert plain.id == "design-test-1" and plain.sites[0].id == "site-1"


def test_extraction_ids_use_the_second_namespace_and_are_not_design_ids() -> None:
    live = uuid.uuid5(EXTRACTION_NS, "abc123:llm_text:claude-opus-5-5")
    cached = uuid.uuid5(EXTRACTION_NS, "abc123:transcription:build-time")
    assert live.version == 5 and cached.version == 5
    assert live != uuid.uuid5(IMPORTER_NS, "abc123:llm_text:claude-opus-5-5")
    assert "patient_share" not in Visit.model_fields
