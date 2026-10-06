from __future__ import annotations

import argparse
import getpass

from sqlalchemy.orm import Session

from backend.app.auth import create_user
from backend.app.database import engine
from backend.app.models.auth import UserRole


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Create the first Visa Automatic administrator.")
    value.add_argument("--email", required=True)
    value.add_argument("--display-name", required=True)
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    password = getpass.getpass("Password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        print("Administrator was not created: passwords do not match.")
        return 2
    try:
        with Session(engine) as session:
            user = create_user(
                session,
                email=args.email,
                display_name=args.display_name,
                password=password,
                role=UserRole.ADMIN.value,
            )
    except ValueError as error:
        print(f"Administrator was not created: {error}")
        return 2
    print(f"Administrator created for {user.email}. Complete MFA enrollment at the normal login page.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
