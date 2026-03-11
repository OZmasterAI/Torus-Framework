import json
import sys


def main() -> None:
    with open("/home/crab/.claude/scripts/batch7_data.json") as f:
        data = json.load(f)

    sys.stdout.write(f"Total entries: {len(data)}\n")
    violations = []
    for e in data:
        n = len(e["new_text"])
        status = "OK" if n <= 800 else f"OVER: {n}"
        sys.stdout.write(f"  {e['id']}: {n} {status}\n")
        if n > 800:
            violations.append(e["id"])

    sys.stdout.write(f"\nViolations: {len(violations)}\n")
    if violations:
        sys.exit(1)
    else:
        sys.stdout.write("All entries valid.\n")


if __name__ == "__main__":
    main()
