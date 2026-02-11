from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def force_utf8_stdio() -> None:
    """標準出力/標準エラーを可能な範囲で UTF-8 に寄せる。"""
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def read_text(path: Path) -> str:
    """UTF-8 としてテキストファイルを読む。"""
    return path.read_text(encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    """親ディレクトリを作成して、UTF-8 でテキストを書き込む。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def read_json(path: Path) -> Any:
    """JSON ファイルを読み込み、Python オブジェクトに変換して返す。"""
    return json.loads(read_text(path))


def write_json(path: Path, obj: Any) -> None:
    """Python オブジェクトを整形 JSON として書き出す（末尾改行あり）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize_user_path(s: str) -> Path:
    """ユーザー入力のパス文字列を正規化して Path にする（\\→/、先頭 ./ 除去）。"""
    raw = (s or "").strip().strip('"').strip("'")
    raw = raw.replace("\\", "/")
    if raw.startswith("./"):
        raw = raw[2:]
    return Path(raw)


def extract_json_text(text: str) -> str:
    """LLM 出力から JSON オブジェクト部分（文字列）だけを抽出する。"""
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


def get_api_key_from_file(path: Path, *, key_name: str = "gemini_api_key") -> str | None:
    """API キーファイル（raw文字列 or JSON）から API キーを取り出す。

    - raw文字列: そのままキーとして扱う
    - JSON文字列: 指定キー（例: gemini_api_key / openai_api_key）から取り出す
    """
    try:
        raw = read_text(path).strip()
    except FileNotFoundError:
        return None

    try:
        obj = json.loads(raw)
    except Exception:
        return raw or None

    if isinstance(obj, str):
        return obj.strip() or None
    if isinstance(obj, dict):
        # 指定キーを優先
        v = obj.get(key_name)
        if isinstance(v, str) and v.strip():
            return v.strip()
        # 互換: OpenAI系では汎用キー名 `api_key` が使われることがある
        v2 = obj.get("api_key")
        if isinstance(v2, str) and v2.strip():
            return v2.strip()
    return None

