#!/usr/bin/env python3
"""Compact canonical market JSON without changing the public data shape.

Historical symbol files keep the symbol name once at payload level.  Daily
partitions keep names and all fields needed by the frontend, while null fields
are omitted everywhere.  Run with --dry-run first; --apply rewrites files
atomically. By default all three canonical market roots are processed.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path


def compact_value(value, *, strip_record_name=False):
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if item is None:
                continue
            if strip_record_name and key == "name":
                continue
            result[key] = compact_value(item, strip_record_name=False)
        return result
    if isinstance(value, list):
        return [compact_value(item, strip_record_name=False) for item in value]
    return value


def compact_payload(path: Path, *, historical: bool):
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None

    if historical and isinstance(payload.get("records"), list):
        name = payload.get("name")
        if not name:
            for record in reversed(payload["records"]):
                if isinstance(record, dict) and record.get("name"):
                    name = record["name"]
                    break
        compacted = compact_value(payload)
        if name:
            compacted["name"] = name
        compacted["records"] = [compact_value(record, strip_record_name=True)
                                  for record in payload["records"]]
        return compacted
    if isinstance(payload.get("data"), dict) and not isinstance(payload.get("data"), list):
        # Canonical merged.json: keep its public shape, but move repeated names
        # to one top-level map and omit null/name fields from every row.
        names = dict(payload.get("names") or payload.get("name_map") or {})
        meta = payload.get("meta")
        if isinstance(meta, dict) and isinstance(meta.get("name_map"), dict):
            names.update({k: v for k, v in meta["name_map"].items() if v})
        data = {}
        for symbol, records in payload["data"].items():
            if not isinstance(records, list):
                data[symbol] = records
                continue
            compact_records = []
            for record in records:
                if isinstance(record, dict):
                    if record.get("name") and symbol not in names:
                        names[symbol] = record["name"]
                    compact_records.append(compact_value(record, strip_record_name=True))
                else:
                    compact_records.append(record)
            data[symbol] = compact_records
        compacted = compact_value(payload)
        compacted.pop("name_map", None)
        if isinstance(compacted.get("meta"), dict):
            compacted["meta"].pop("name_map", None)
        compacted["names"] = names
        compacted["data"] = data
        return compacted
    return compact_value(payload)


def write_json(path: Path, payload):
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
            handle.write("\n")
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", action="append", default=None,
                        help="market root, repeatable (default: Astocks and ETFs)")
    parser.add_argument("--dry-run", action="store_true", help="estimate only; this is the default")
    parser.add_argument("--apply", action="store_true", help="rewrite files; otherwise dry-run")
    args = parser.parse_args()
    roots = [Path(item) for item in args.root] if args.root else [Path("data/Astocks"), Path("data/ETFs"), Path("data/USstocks")]
    total_before = total_after = files = 0
    for root in roots:
        paths = list((root / "stocks").glob("*.json")) + list((root / "indices").glob("*.json"))
        paths += list((root / "daily").glob("*.json"))
        paths += [root / "latest.json", root / "merged.json"]
        for path in paths:
            if not path.exists():
                continue
            payload = compact_payload(path, historical=path.parent.name in {"stocks", "indices"})
            if payload is None:
                continue
            before = path.stat().st_size
            encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            after = len(encoded) + 1
            total_before += before
            total_after += after
            files += 1
            if args.apply and after < before:
                write_json(path, payload)
        print(f"{root}: {files} files considered")
    saved = total_before - total_after
    print(f"Estimated: {total_before / 1024 / 1024:.1f} MB -> {total_after / 1024 / 1024:.1f} MB; "
          f"save {saved / 1024 / 1024:.1f} MB ({saved / max(total_before, 1):.1%})")
    if not args.apply:
        print("Dry-run only. Add --apply to rewrite files.")


if __name__ == "__main__":
    main()
