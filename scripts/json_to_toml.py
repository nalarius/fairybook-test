from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Dict, List, Tuple, Union

JSONScalar = Union[str, int, float, bool]
JSONArray = List["JSONValue"]
JSONObject = Dict[str, "JSONValue"]
JSONValue = Union[JSONScalar, None, JSONArray, JSONObject]

SAFE_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert a JSON file to a TOML file with the same base name."
    )
    parser.add_argument("json_path", type=Path, help="Path to the source JSON file")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow overwriting the destination TOML file if it already exists",
    )
    return parser.parse_args()


def load_json(path: Path) -> JSONObject:
    try:
        with path.open("r", encoding="utf-8") as fp:
            data = json.load(fp)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Failed to parse JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise SystemExit("Top-level JSON value must be an object to map to TOML.")

    return data


def format_value(value: JSONValue) -> str:
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if value is None:
        raise TypeError("TOML does not support null values; remove or replace them.")
    if isinstance(value, list):
        return format_array(value)
    if isinstance(value, dict):
        raise TypeError("Inline tables are not supported; nested objects become tables.")
    raise TypeError(f"Unsupported value type: {type(value).__name__}")


def format_array(values: JSONArray) -> str:
    if not values:
        return "[]"

    if all(isinstance(item, dict) for item in values):
        raise TypeError(
            "Arrays of objects map to array-of-table sections and cannot be inline values."
        )

    formatted_items = [format_value(item) for item in values]
    return f"[{', '.join(formatted_items)}]"


def format_key(key: str) -> str:
    if SAFE_KEY_PATTERN.match(key):
        return key
    return json.dumps(key, ensure_ascii=False)


def format_table_key(key: str) -> str:
    if SAFE_KEY_PATTERN.match(key):
        return key
    return json.dumps(key, ensure_ascii=False)


def ensure_blank_line(lines: List[str]) -> None:
    if lines and lines[-1] != "":
        lines.append("")


def emit_table(
    data: JSONObject,
    parent_keys: Tuple[str, ...],
    lines: List[str],
) -> None:
    plain_items: List[Tuple[str, JSONValue]] = []
    child_tables: List[Tuple[str, JSONObject]] = []
    array_tables: List[Tuple[str, List[JSONObject]]] = []

    for key, value in data.items():
        if isinstance(value, dict):
            child_tables.append((key, value))
        elif isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
            array_tables.append((key, value))
        else:
            plain_items.append((key, value))

    for key, value in plain_items:
        try:
            rendered = format_value(value)
        except TypeError as exc:
            raise SystemExit(f"Unable to format key '{key}': {exc}") from exc
        lines.append(f"{format_key(key)} = {rendered}")

    for key, value in child_tables:
        ensure_blank_line(lines)
        header = ".".join(format_table_key(part) for part in (*parent_keys, key))
        lines.append(f"[{header}]")
        emit_table(value, (*parent_keys, key), lines)

    for key, entries in array_tables:
        header = ".".join(format_table_key(part) for part in (*parent_keys, key))
        for entry in entries:
            ensure_blank_line(lines)
            lines.append(f"[[{header}]]")
            emit_table(entry, (*parent_keys, key), lines)


def convert_to_toml(data: JSONObject) -> str:
    lines: List[str] = []
    emit_table(data, tuple(), lines)
    output = "\n".join(lines)
    if output and not output.endswith("\n"):
        output += "\n"
    return output


def resolve_output_path(input_path: Path) -> Path:
    return input_path.with_suffix(".toml")


def main() -> None:
    args = parse_args()
    json_path: Path = args.json_path

    if not json_path.is_file():
        raise SystemExit(f"JSON file not found: {json_path}")

    data = load_json(json_path)
    toml_text = convert_to_toml(data)

    output_path = resolve_output_path(json_path)
    if output_path.exists() and not args.overwrite:
        raise SystemExit(
            f"Destination file already exists: {output_path}. Use --overwrite to replace it."
        )

    try:
        output_path.write_text(toml_text, encoding="utf-8")
    except OSError as exc:
        raise SystemExit(f"Failed to write TOML file: {exc}") from exc

    print(f"Created {output_path}")


if __name__ == "__main__":
    main()
