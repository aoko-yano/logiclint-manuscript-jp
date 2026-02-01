from __future__ import annotations

from typing import Any


def validate_report_shape(obj: Any, taxonomy: set[str]) -> list[str]:
    """Gemini のレポート JSON が期待スキーマ形状に近いかを簡易検証する。"""
    # エラー文字列を収集して返す（空ならOK）
    errors: list[str] = []

    # トップレベルは object（dict）である必要がある
    if not isinstance(obj, dict):
        return ["top-level must be an object"]

    # 必須キー（最低限）を確認
    for k in ["source", "issues"]:
        if k not in obj:
            errors.append(f"missing required key: {k}")

    # issues は配列である必要がある
    if "issues" in obj and not isinstance(obj["issues"], list):
        errors.append("issues must be an array")

    # issues 要素ごとの形状チェック
    issues = obj.get("issues")
    if isinstance(issues, list):
        for i, it in enumerate(issues):
            # 各 issue は object
            if not isinstance(it, dict):
                errors.append(f"issues[{i}] must be an object")
                continue
            # 各 issue の必須キー
            for k in ["type", "location", "claim_a", "claim_b", "why", "severity", "fix"]:
                if k not in it:
                    errors.append(f"issues[{i}].{k} is required")
            # taxonomy が指定されている場合は type がその集合に含まれること
            if "type" in it and isinstance(it["type"], str):
                if taxonomy and it["type"] not in taxonomy:
                    errors.append(f"issues[{i}].type must be one of taxonomy: {it['type']}")
            # location.quote は必須（逐語引用）
            loc = it.get("location")
            if not isinstance(loc, dict) or "quote" not in loc:
                errors.append(f"issues[{i}].location.quote is required")
            # severity は 1..5 の整数
            sev = it.get("severity")
            if not isinstance(sev, int) or not (1 <= sev <= 5):
                errors.append(f"issues[{i}].severity must be integer 1..5")
    return errors


def normalize_report(obj: dict[str, Any]) -> dict[str, Any]:
    """レポート JSON を正規化（トリム・並び替え・最小整形）して返す。"""
    # 出力用の新しい dict を作って詰め直す（入力を破壊しない）
    out: dict[str, Any] = {}

    # source は文字列化して前後空白を落とす
    out["source"] = str(obj.get("source", "")).strip()

    # issues は配列でなければ空として扱う
    issues_in = obj.get("issues") if isinstance(obj.get("issues"), list) else []
    issues_out: list[dict[str, Any]] = []

    for it in issues_in:
        # issues の各要素が object でない場合は捨てる
        if not isinstance(it, dict):
            continue
        # location は object でなければ空扱い
        loc = it.get("location") if isinstance(it.get("location"), dict) else {}
        # 必要キーを取り出して文字列化・トリムし、余計なキーは落とす
        issues_out.append(
            {
                "type": str(it.get("type", "")).strip(),
                "location": {
                    "quote": str(loc.get("quote", "")).strip(),
                    # note は任意（存在する場合のみ残す）
                    **({"note": str(loc.get("note", "")).strip()} if "note" in loc else {}),
                },
                "claim_a": str(it.get("claim_a", "")).strip(),
                "claim_b": str(it.get("claim_b", "")).strip(),
                "why": str(it.get("why", "")).strip(),
                "severity": int(it.get("severity", 0) or 0),
                "fix": str(it.get("fix", "")).strip(),
            }
        )

    # 重大度（降順）→ type → quote の順で安定ソート
    issues_out.sort(key=lambda x: (-x["severity"], x["type"], x["location"]["quote"]))
    out["issues"] = issues_out

    # meta は object の場合のみ残す（生成側で付与されることを想定）
    meta = obj.get("meta")
    if isinstance(meta, dict):
        out["meta"] = meta

    return out

