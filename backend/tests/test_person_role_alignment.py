from __future__ import annotations

import importlib
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from backend.app import models
from backend.app.database import Base, get_session
from backend.app.main import app
from backend.app.models import canada as cm
from backend.app.schemas.core import PersonCreate, PersonRead
from backend.app.services.core import CoreDataService


def test_person_api_and_canonical_operational_role_vocabularies_are_identical():
    expected = {role.value for role in cm.OperationalRole}
    assert expected == {"applicant", "representative", "sponsor", "host", "other"}
    for role in expected:
        assert PersonCreate(first_name="Valid", last_name="Person", roles=[role]).roles
    for relationship in ("spouse", "former_spouse", "parent", "child", "family_member"):
        with pytest.raises(ValidationError):
            PersonCreate(first_name="Invalid", last_name="Role", roles=[relationship])


def test_core_person_writes_normalized_roles_and_projection_together(session):
    case = models.Case(case_number="ROLE-SYNC", visa_type="canada_trv", purpose="Test")
    session.add(case)
    session.commit()
    person = CoreDataService(session).create_person(
        case.id, PersonCreate(first_name="Dual", last_name="Role", roles=["sponsor", "host"])
    )
    assert person.roles == ["sponsor", "host"]
    assert set(session.scalars(select(cm.CasePersonRole.role).where(
        cm.CasePersonRole.person_id == person.id
    ))) == {"sponsor", "host"}
    assert PersonRead.model_validate(person).roles


def test_people_endpoint_normalizes_legacy_family_role_without_500(session):
    case = models.Case(case_number="LEGACY-API", visa_type="canada_trv", purpose="Test")
    session.add(case)
    session.flush()
    person = models.Person(
        case_id=case.id, first_name="Legacy", last_name="Relative", roles=["family_member"]
    )
    session.add(person)
    session.commit()

    def override():
        yield session

    app.dependency_overrides[get_session] = override
    try:
        response = TestClient(app).get(f"/cases/{case.id}/persons")
        assert response.status_code == 200
        assert response.json()[0]["roles"] == ["other"]
    finally:
        app.dependency_overrides.pop(get_session, None)


def test_0014_migration_repairs_family_member_and_bootstraps_authoritative_role(session, monkeypatch):
    case = models.Case(case_number="LEGACY-MIGRATION", visa_type="canada_trv", purpose="Test")
    session.add(case)
    session.flush()
    person = models.Person(
        id=uuid.uuid4(), case_id=case.id, first_name="Existing", last_name="Relative",
        roles=["family_member"],
    )
    session.add(person)
    session.commit()

    migration = importlib.import_module(
        "backend.migrations.versions.0014_person_role_alignment"
    )
    monkeypatch.setattr(migration.op, "get_bind", lambda: session.connection())
    migration.upgrade()
    session.commit()
    session.expire_all()

    assert session.get(models.Person, person.id).roles == ["other"]
    rows = list(session.scalars(select(cm.CasePersonRole).where(
        cm.CasePersonRole.person_id == person.id
    )))
    assert [row.role for row in rows] == ["other"]
    assert rows[0].assigned_by == "migration:0014"

    migration.upgrade()
    session.commit()
    assert len(list(session.scalars(select(cm.CasePersonRole).where(
        cm.CasePersonRole.person_id == person.id
    )))) == 1


def test_alembic_upgrade_from_0013_repairs_existing_family_member(tmp_path, monkeypatch):
    database_path = tmp_path / "existing-0013.db"
    url = f"sqlite+pysqlite:///{database_path}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    with Session(engine) as database:
        case = models.Case(case_number="UPGRADE-0013", visa_type="canada_trv", purpose="Test")
        database.add(case)
        database.flush()
        person = models.Person(
            case_id=case.id, first_name="Legacy", last_name="Family",
            roles=["family_member"],
        )
        database.add(person)
        database.commit()
        person_id = person.id
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
        ))
        connection.execute(text(
            "INSERT INTO alembic_version (version_num) VALUES ('0013_automated_intake')"
        ))
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config(str(Path(__file__).parents[2] / "backend/alembic.ini"))
    command.upgrade(config, "head")
    with Session(engine) as database:
        assert database.get(models.Person, person_id).roles == ["other"]
        assert database.scalar(select(cm.CasePersonRole.role).where(
            cm.CasePersonRole.person_id == person_id
        )) == "other"
    engine.dispose()
