"""Explicit sponsor setup; does not create a paid cloud service or print secrets."""
import argparse
import json

from roboforge.integrations.tiger import TigerTelemetry, TigerUnavailable


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tiger", action="store_true", help="Initialize the configured Tiger database")
    parser.add_argument("--check", action="store_true", help="Check connection and schema without writes")
    args = parser.parse_args()
    if not (args.tiger or args.check):
        parser.error("Choose --tiger or --check")
    database = TigerTelemetry()
    if args.tiger:
        try:
            database.initialize()
        except TigerUnavailable as error:
            print(json.dumps({"ready": False, "error": str(error)}))
            return 1
    status = database.health()
    print(json.dumps(status))
    return 0 if status.get("connected") and status.get("schema_ready") else 1


if __name__ == "__main__":
    raise SystemExit(main())
