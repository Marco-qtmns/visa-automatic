from __future__ import annotations

import pytest
from types import SimpleNamespace
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend.app.database import Base
from backend.app.auth import require_authenticated_request
from backend.app.main import app


@pytest.fixture(autouse=True)
def authenticated_business_requests(request):
    """Keep pre-M10A business tests focused; auth tests opt into the real boundary."""
    if request.node.get_closest_marker("real_auth") is None:
        app.dependency_overrides[require_authenticated_request] = lambda: SimpleNamespace(
            id=None,
            email="existing-test@example.invalid",
            display_name="Existing test user",
            role="ADMIN",
            is_active=True,
            mfa_enabled=True,
        )
    yield
    app.dependency_overrides.pop(require_authenticated_request, None)


@pytest.fixture
def session(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'test.db'}")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as value:
        yield value
    engine.dispose()
