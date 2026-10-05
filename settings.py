from __future__ import annotations
import json
import os
import sys
from pathlib import Path
from models import RecipientData

APP_NAME = "956A Generator"
SETTINGS_VERSION = 5

# Personal recipient details are supplied only through local settings.
RECIPIENT_DEFAULTS = RecipientData()


def app_data_dir() -> Path:
    if sys.platform.startswith("win"):
        root = Path(os.environ.get("APPDATA", Path.home()))
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    path = root / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_path() -> Path:
    return app_data_dir() / "settings.json"


def default_settings() -> dict:
    return {
        "settings_version": SETTINGS_VERSION,
        "default_client_country": "BRAZIL",
        "recipient": RECIPIENT_DEFAULTS.to_dict(),
    }


def load_settings() -> dict:
    path = settings_path()
    if not path.exists():
        data = default_settings()
        save_settings(data)
        return data
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        data = default_settings()
    base = default_settings()
    base.update({k: v for k, v in data.items() if k != "recipient"})

    # Preserve explicit blanks and saved values for every settings version.
    # Never inject or overwrite personal details during migration.
    rec = dict(base["recipient"])
    existing_rec = data.get("recipient", {}) or {}
    for key in rec:
        if key in existing_rec:
            rec[key] = str(existing_rec[key] or "")

    base["recipient"] = rec
    base["settings_version"] = SETTINGS_VERSION
    if data.get("settings_version") != SETTINGS_VERSION:
        save_settings(base)
    return base


def save_settings(data: dict) -> None:
    settings_path().write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
