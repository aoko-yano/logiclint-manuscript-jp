from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import importlib.resources as resources


def _force_utf8_stdio() -> None:
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _read_json(path: Path) -> Any:
    return json.loads(_read_text(path))


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _normalize_user_path(s: str) -> Path:
    raw = (s or "").strip().strip('"').strip("'")
    raw = raw.replace("\\", "/")
    if raw.startswith("./"):
        raw = raw[2:]
    return Path(raw)


def _extract_json_text(text: str) -> str:
    s = text.strip()
    if not s:
        raise ValueError("empty input")

    if s.startswith("```"):
        lines = s.splitlines()
        if len(lines) >= 2:
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        s = "\n".join(lines).strip()

    if not s.startswith("{"):
        start = s.find("{")
        end = s.rfind("}")
        if start != -1 and end != -1 and end > start:
            s = s[start : end + 1].strip()

    if not (s.startswith("{") and s.endswith("}")):
        raise ValueError("could not locate a JSON object in input")
    return s


def _get_api_key_from_file(path: Path) -> str | None:
    try:
        raw = _read_text(path).strip()
    except FileNotFoundError:
        return None

    try:
        obj = json.loads(raw)
    except Exception:
        return raw or None

    if isinstance(obj, str):
        return obj.strip() or None
    if isinstance(obj, dict):
        v = obj.get("gemini_api_key")
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _gemini_generate_text(*, model: str, prompt: str, api_key: str) -> str:
    if not (api_key or "").strip():
        raise RuntimeError("Gemini APIキーが未設定です（.logiclint/secret.json を用意してください）")

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{urllib.parse.quote(model, safe='')}:generateContent"
        f"?key={urllib.parse.quote(api_key, safe='')}"
    )

    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2},
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url=url,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )

    raw: bytes | None = None
    last_err: Exception | None = None
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                raw = resp.read()
            last_err = None
            break
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace") if hasattr(e, "read") else ""
            last_err = RuntimeError(f"Gemini API HTTPError: {e.code} {e.reason}\n{body}")

            if e.code == 429 and attempt < 4:
                retry_seconds: float | None = None
                try:
                    err_obj = json.loads(body)
                    details = (((err_obj.get("error") or {}).get("details")) or [])
                    for d in details:
                        if isinstance(d, dict) and d.get("@type") == "type.googleapis.com/google.rpc.RetryInfo":
                            delay = str(d.get("retryDelay") or "").strip()
                            m = re.match(r"^(\d+)(?:\.\d+)?s$", delay)
                            if m:
                                retry_seconds = float(m.group(1))
                except Exception:
                    retry_seconds = None

                if retry_seconds is None:
                    retry_seconds = 2.0 * attempt
                time.sleep(retry_seconds)
                continue

            break
        except Exception as e:
            last_err = RuntimeError(f"Gemini API 呼び出しに失敗しました: {e}")
            break

    if last_err is not None:
        raise last_err
    if raw is None:
        raise RuntimeError("Gemini API 応答が空です")

    obj = json.loads(raw.decode("utf-8"))
    cands = obj.get("candidates") or []
    if not cands:
        raise RuntimeError(f"Gemini API 応答に candidates がありません: {obj}")
    content = (cands[0] or {}).get("content") or {}
    parts = content.get("parts") or []
    texts = []
    for p in parts:
        if isinstance(p, dict) and "text" in p:
            texts.append(str(p["text"]))
    out = "".join(texts).strip()
    if not out:
        raise RuntimeError(f"Gemini API 応答に text がありません: {obj}")
    return out


def _validate_report_shape(obj: Any, taxonomy: set[str]) -> list[str]:
    errors: list[str] = []
    if not isinstance(obj, dict):
        return ["top-level must be an object"]

    for k in ["source", "issues"]:
        if k not in obj:
            errors.append(f"missing required key: {k}")

    if "issues" in obj and not isinstance(obj["issues"], list):
        errors.append("issues must be an array")

    issues = obj.get("issues")
    if isinstance(issues, list):
        for i, it in enumerate(issues):
            if not isinstance(it, dict):
                errors.append(f"issues[{i}] must be an object")
                continue
            for k in ["type", "location", "claim_a", "claim_b", "why", "severity", "fix"]:
                if k not in it:
                    errors.append(f"issues[{i}].{k} is required")
            if "type" in it and isinstance(it["type"], str):
                if taxonomy and it["type"] not in taxonomy:
                    errors.append(f"issues[{i}].type must be one of taxonomy: {it['type']}")
            loc = it.get("location")
            if not isinstance(loc, dict) or "quote" not in loc:
                errors.append(f"issues[{i}].location.quote is required")
            sev = it.get("severity")
            if not isinstance(sev, int) or not (1 <= sev <= 5):
                errors.append(f"issues[{i}].severity must be integer 1..5")
    return errors


def _normalize_report(obj: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    out["source"] = str(obj.get("source", "")).strip()
    issues_in = obj.get("issues") if isinstance(obj.get("issues"), list) else []
    issues_out: list[dict[str, Any]] = []
    for it in issues_in:
        if not isinstance(it, dict):
            continue
        loc = it.get("location") if isinstance(it.get("location"), dict) else {}
        issues_out.append(
            {
                "type": str(it.get("type", "")).strip(),
                "location": {
                    "quote": str(loc.get("quote", "")).strip(),
                    **({"note": str(loc.get("note", "")).strip()} if "note" in loc else {}),
                },
                "claim_a": str(it.get("claim_a", "")).strip(),
                "claim_b": str(it.get("claim_b", "")).strip(),
                "why": str(it.get("why", "")).strip(),
                "severity": int(it.get("severity", 0) or 0),
                "fix": str(it.get("fix", "")).strip(),
            }
        )
    issues_out.sort(key=lambda x: (-x["severity"], x["type"], x["location"]["quote"]))
    out["issues"] = issues_out
    meta = obj.get("meta")
    if isinstance(meta, dict):
        out["meta"] = meta
    return out


def _load_default_assets() -> tuple[str, dict[str, Any]]:
    rubric = resources.files("logiclint.assets").joinpath("rubric.md").read_text(encoding="utf-8")
    schema_text = resources.files("logiclint.assets").joinpath("schema.json").read_text(encoding="utf-8")
    schema = json.loads(schema_text)
    if not isinstance(schema, dict):
        raise RuntimeError("bundled schema.json must be an object")
    return rubric, schema


def _load_config(work_root: Path, path: Path | None) -> dict[str, Any]:
    if path is None:
        # 優先順:
        # 1) 原稿ルート（cwd）配下の ./.logiclint/logiclint.config.json
        # 2) ツール同梱（=リポジトリ/イメージ内）の ./.logiclint/logiclint.config.json
        candidate = work_root / ".logiclint" / "logiclint.config.json"
        if candidate.exists():
            path = candidate
        else:
            tool_cfg = Path(__file__).resolve().parents[2] / ".logiclint" / "logiclint.config.json"
            path = tool_cfg
    if not path.exists():
        raise SystemExit(f"ERROR: 設定ファイルが見つかりません: {path}")
    user_cfg = _read_json(path)
    if not isinstance(user_cfg, dict):
        raise SystemExit(f"ERROR: 設定ファイルは JSON object である必要があります: {path}")
    return user_cfg


def _build_prompt(*, rubric: str, schema: dict[str, Any], source: str, body: str) -> str:
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


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdio()
    argv = list(sys.argv[1:] if argv is None else argv)

    p = argparse.ArgumentParser(
        prog="logiclint",
        description="原稿の内部論理不整合を、固定スキーマJSONで出力させるツール。",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    p.add_argument(
        "--config",
        default="",
        help="設定ファイル（省略時: ./.logiclint/logiclint.config.json を優先し、無ければツール同梱を使用）",
    )
    p.add_argument("--model", default="", help="Geminiモデル名（省略時: configの gemini.model）")
    p.add_argument("--recursive", action="store_true", help="ディレクトリ配下の .md を再帰的に順番に処理する")
    p.add_argument("target", nargs="?", help="対象Markdown（ファイル or ディレクトリ）")

    if not argv:
        p.print_help(sys.stderr)
        return 0
    args = p.parse_args(argv)
    if not args.target:
        p.print_help(sys.stderr)
        return 0

    work_root = Path(os.getcwd()).resolve()
    cfg_path = Path(args.config).resolve() if args.config else None
    cfg = _load_config(work_root, cfg_path)

    if not isinstance(cfg.get("output"), dict) or not str(cfg["output"].get("dir") or "").strip():
        raise SystemExit("ERROR: config.output.dir が必要です")
    if not isinstance(cfg.get("gemini"), dict):
        raise SystemExit("ERROR: config.gemini が必要です")
    gem: dict[str, Any] = cfg["gemini"]
    if not str(gem.get("model") or "").strip():
        raise SystemExit("ERROR: config.gemini.model が必要です")
    if not str(gem.get("api_key_file") or "").strip():
        raise SystemExit("ERROR: config.gemini.api_key_file が必要です")
    if not isinstance(cfg.get("taxonomy"), list) or not cfg["taxonomy"]:
        raise SystemExit("ERROR: config.taxonomy（配列）が必要です")

    model = (args.model or str(gem["model"])).strip()
    out_dir = work_root / str(cfg["output"]["dir"])

    try:
        sleep_between = float(gem["sleep_seconds_between_requests"])
        max_retries = int(gem["max_retries_per_file"])
        sleep_between_retries = float(gem["sleep_seconds_between_retries"])
    except KeyError as e:
        raise SystemExit(f"ERROR: config.gemini.{e.args[0]} が必要です") from e
    if sleep_between < 0 or sleep_between_retries < 0 or max_retries < 0:
        raise SystemExit("ERROR: sleep/max_retries は 0 以上で指定してください")

    key_file = str(gem["api_key_file"])
    key_path = (work_root / key_file).resolve()
    api_key = _get_api_key_from_file(key_path)
    if not api_key:
        raise SystemExit(f"ERROR: APIキーを読み取れませんでした: {key_file} ({key_path})")

    rubric, schema = _load_default_assets()
    taxonomy = set(cfg["taxonomy"])

    target = _normalize_user_path(args.target)
    target_path = (work_root / target).resolve() if not target.is_absolute() else target

    def iter_md_files(root: Path) -> list[Path]:
        files = [p for p in root.rglob("*.md") if p.is_file()]
        files.sort(key=lambda p: str(p).lower())
        return files

    def run_one(md_path: Path) -> int:
        body = _read_text(md_path)
        try:
            source = str(md_path.resolve().relative_to(work_root)).replace("\\", "/")
        except Exception:
            source = str(md_path)

        prompt = _build_prompt(rubric=rubric, schema=schema, source=source, body=body)
        prompt_path = (out_dir / f"{md_path.name}.PROMPT.md").resolve()
        _write_text(prompt_path, prompt + "\n")

        text = _gemini_generate_text(model=model, prompt=prompt, api_key=api_key)
        try:
            report_obj = json.loads(_extract_json_text(text))
        except Exception as e:
            raise SystemExit(f"ERROR: Geminiの出力をJSONとして解釈できませんでした（{e}）\n---\n{text[:2000]}\n---")

        errs = _validate_report_shape(report_obj, taxonomy)
        if errs:
            for e in errs:
                print(f"ERROR: {e}", file=sys.stderr)
            return 2

        norm = _normalize_report(report_obj)
        norm.setdefault("meta", {})
        norm["meta"]["generated_by"] = "gemini-api"
        norm["meta"]["model"] = model
        norm["meta"]["generated_at"] = _dt.datetime.now(tz=_dt.timezone.utc).isoformat()

        out_path = (out_dir / f"{md_path.name}.json").resolve()
        _write_json(out_path, norm)
        print(str(out_path.relative_to(work_root)).replace("\\", "/"))
        return 0

    def run_one_with_retries(md_path: Path) -> int:
        last_rc = 0
        for attempt in range(0, max_retries + 1):
            try:
                last_rc = run_one(md_path)
            except SystemExit as e:
                msg = e.code
                if msg:
                    print(str(msg), file=sys.stderr)
                last_rc = 2
            if last_rc == 0:
                break
            if attempt < max_retries and sleep_between_retries > 0:
                time.sleep(sleep_between_retries)
        return last_rc

    out_dir.mkdir(parents=True, exist_ok=True)

    if args.recursive:
        if not (target_path.exists() and target_path.is_dir()):
            raise SystemExit("ERROR: --recursive のときは引数にディレクトリを指定してください")
        md_files = iter_md_files(target_path)
        for i, md in enumerate(md_files):
            rc = run_one_with_retries(md)
            if rc != 0:
                return rc
            if sleep_between > 0 and i < (len(md_files) - 1):
                time.sleep(sleep_between)
        return 0

    if not (target_path.exists() and target_path.is_file()):
        raise SystemExit("ERROR: ファイルが見つかりません")
    return int(run_one(target_path))

