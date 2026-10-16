"""Apply Location schema only to an explicitly selected qa_*.db copy."""

import argparse
from pathlib import Path
from sqlalchemy import create_engine
from app.services.location_migration import apply_phase_c_schema


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    path = Path(args.db).resolve()
    trial = Path(__file__).resolve().parents[2] / ".sprint123-trial"
    if (
        not path.is_relative_to(trial.resolve())
        or not path.name.startswith("qa_")
        or path.suffix != ".db"
        or not path.is_file()
    ):
        raise RuntimeError("Select an existing qa_*.db inside .sprint123-trial")
    if not args.apply:
        print("Dry run: QA target validated; pass --apply to migrate this QA copy only.")
        return
    engine = create_engine("sqlite:///" + path.as_posix())
    apply_phase_c_schema(engine)
    engine.dispose()
    print("QA Location migration completed; existing rows unchanged.")


if __name__ == "__main__":
    main()
