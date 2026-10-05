from __future__ import annotations

from pathlib import Path


def test_backend_uses_unambiguous_package_path():
    import backend.app as backend_package
    from backend.app.main import app as fastapi_app
    from backend.app.storage import LocalStorageProvider, StorageProvider
    from canada.case_store import load_case

    repository_root = Path(__file__).resolve().parents[2]
    assert Path(backend_package.__file__).resolve() == repository_root / "backend/app/__init__.py"
    assert fastapi_app.title == "Visa Automatic"
    assert LocalStorageProvider is not None
    assert StorageProvider is not None
    assert load_case is not None


def test_root_app_remains_the_desktop_compatibility_module():
    import app as desktop_app

    repository_root = Path(__file__).resolve().parents[2]
    assert Path(desktop_app.__file__).resolve() == repository_root / "app.py"
    assert not hasattr(desktop_app, "__path__")
