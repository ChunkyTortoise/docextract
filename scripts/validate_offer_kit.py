from __future__ import annotations

from pathlib import Path

REQUIRED_TOP_LEVEL = {
    "schema_version",
    "name",
    "version",
    "positioning",
    "quickstart",
    "environments",
    "deliverables",
    "smoke_tests",
    "acceptance_checklist",
    "handoff_outputs",
}
LIST_KEYS = {"deliverables", "smoke_tests", "acceptance_checklist", "handoff_outputs"}


def _top_level_keys(lines: list[str]) -> set[str]:
    keys: set[str] = set()
    for raw in lines:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw.startswith(" "):
            continue
        if ":" in raw:
            keys.add(raw.split(":", 1)[0].strip())
    return keys


def _find_block(lines: list[str], key: str) -> list[str]:
    start = None
    for i, raw in enumerate(lines):
        if raw.startswith(f"{key}:"):
            start = i
            break
    if start is None:
        return []

    block: list[str] = []
    for raw in lines[start + 1 :]:
        if raw and not raw.startswith(" "):
            break
        block.append(raw)
    return block


def _count_list_items(block: list[str]) -> int:
    return sum(1 for line in block if line.startswith("  - "))


def main() -> int:
    path = Path("offer-kit.yaml")
    if not path.exists():
        print("offer-kit.yaml not found")
        return 1

    lines = path.read_text().splitlines()

    keys = _top_level_keys(lines)
    missing = sorted(REQUIRED_TOP_LEVEL - keys)
    if missing:
        print(f"Missing required keys: {missing}")
        return 1

    schema_line = next((line for line in lines if line.startswith("schema_version:")), "")
    if schema_line.split(":", 1)[1].strip() != "1":
        print("schema_version must be 1")
        return 1

    quickstart_block = _find_block(lines, "quickstart")
    if not any(line.strip().startswith("command:") for line in quickstart_block):
        print("quickstart.command is required")
        return 1
    if not any(line.strip().startswith("sla_days:") for line in quickstart_block):
        print("quickstart.sla_days is required")
        return 1

    env_block = _find_block(lines, "environments")
    required_idx = None
    for i, line in enumerate(env_block):
        if line.strip().startswith("required:"):
            required_idx = i
            break
    if required_idx is None:
        print("environments.required must exist")
        return 1

    required_items = 0
    for line in env_block[required_idx + 1 :]:
        if line.startswith("  ") and not line.startswith("    "):
            break
        if line.startswith("    - "):
            required_items += 1
    if required_items == 0:
        print("environments.required must be a non-empty list")
        return 1

    for key in LIST_KEYS:
        block = _find_block(lines, key)
        if _count_list_items(block) == 0:
            print(f"{key} must be a non-empty list")
            return 1

    print("offer-kit.yaml validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
