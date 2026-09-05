from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date
from pathlib import Path

from serviceflow.infrastructure.policy_ingestion import build_default_policy_retriever


async def run(query: str, output: Path | None) -> None:
    retriever = build_default_policy_retriever()
    prepared = await retriever.prepare()
    evidence, backend, fallback = await retriever.retrieve(
        query,
        tenant_id="tenant-a",
        region="CN",
        at=date(2026, 8, 1),
        limit=5,
    )
    result = {
        "scope": "small_smoke",
        "prepared_backend": prepared,
        "retrieval_backend": backend,
        "fallback": fallback,
        "policy_ids": [item.document.policy_id for item in evidence],
        "scores": [round(item.score, 6) for item in evidence],
        "evidence_boundary": "证明完整语料的 Hybrid + qwen3.7 重排链路可运行，不代表质量结论。",
    }
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if output:
        output.write_text(rendered, encoding="utf-8")
        print(f"result_written={output}")
    else:
        print(rendered)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    asyncio.run(run(args.query, args.output))


if __name__ == "__main__":
    main()
