"""Build the versioned 009 policy corpus from its registered layers."""

import json
from pathlib import Path


ROOT = Path(__file__).parent / "policy_documents"
INPUTS = (
    ROOT / "serviceflow_policy_v2_expanded.jsonl",
    ROOT / "local_guidance.jsonl",
    ROOT / "project_internal.jsonl",
    ROOT / "operations_and_faq.jsonl",
)
OUTPUT = ROOT / "serviceflow_policy_v2_complete.jsonl"


def read_records(path: Path) -> list[dict[str, object]]:
    records = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        record = json.loads(line)
        if not isinstance(record, dict):
            raise ValueError(f"{path.name}:{line_number} 必须是 JSON 对象")
        records.append(record)
    return records


def main() -> None:
    records = [record for path in INPUTS for record in read_records(path)]
    ids = [str(record["policy_id"]) for record in records]
    if len(ids) != len(set(ids)):
        raise ValueError("政策编号重复，拒绝生成不可追溯语料")
    required = {
        "policy_id",
        "version",
        "title",
        "content",
        "source_type",
        "source_title",
        "source_url",
        "source_locator",
        "effective_from",
    }
    for record in records:
        missing = required - record.keys()
        if missing:
            raise ValueError(f"{record.get('policy_id', '<unknown>')} 缺少字段: {sorted(missing)}")
    OUTPUT.write_text(
        "".join(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n" for record in records),
        encoding="utf-8",
    )
    counts: dict[str, int] = {}
    for record in records:
        source_type = str(record["source_type"])
        counts[source_type] = counts.get(source_type, 0) + 1
    print(json.dumps({"count": len(records), "source_type_counts": counts}, ensure_ascii=False))


if __name__ == "__main__":
    main()
