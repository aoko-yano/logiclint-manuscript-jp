from __future__ import annotations

import json
from typing import Any

import importlib.resources as resources


def load_default_assets() -> tuple[str, dict[str, Any]]:
    """同梱アセット（rubric.md / schema.json）を読み込む。"""
    rubric = resources.files("logiclint.assets").joinpath("rubric.md").read_text(encoding="utf-8")
    schema_text = resources.files("logiclint.assets").joinpath("schema.json").read_text(encoding="utf-8")
    schema = json.loads(schema_text)
    if not isinstance(schema, dict):
        raise RuntimeError("bundled schema.json must be an object")
    return rubric, schema


def build_prompt(*, rubric: str, schema: dict[str, Any], source: str, body: str) -> str:
    """Gemini に渡すプロンプト本文を組み立てる（rubric + schema要約 + 入力）。"""
    schema_min = {
        "type": "object",
        "required": schema.get("required", []),
        "properties": schema.get("properties", {}),
        "additionalProperties": schema.get("additionalProperties", False),
    }
    return "\n".join(
        [
            "あなたは査読者ではなく、形式的な「論理Lint」です。",
            "目的は、原稿内部の論理的一貫性（internal consistency）のみを点検することです。",
            "",
            "## ルーブリック",
            rubric.strip(),
            "",
            "## 出力制約（最重要）",
            "- 必ず JSON だけを出力する（前置き・後書き・コードフェンス禁止）。",
            "- 同梱スキーマに準拠する。",
            "- `location.quote` は必ず原文から逐語引用する（存在しない文言を作らない）。",
            "- 推測で断定しない。本文から言えない場合は issue を作らない。",
            "",
            "## JSONスキーマ（要約）",
            json.dumps(schema_min, ensure_ascii=False, indent=2),
            "",
            "## 入力（チェック対象）",
            f"source: {source}",
            "",
            body.strip(),
            "",
        ]
    )

