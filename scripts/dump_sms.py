"""Parse `content query content://sms` dumps into clean, deduped, date-sorted JSON.

Usage:
    python scripts/dump_sms.py data/dumps/old_phone_raw.txt \
        --out data/dumps/old_phone.json --label old_phone
"""
import argparse
import json
import sys
from datetime import datetime, timezone


def parse(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()

    records = []
    lines = text.splitlines()
    cur = []
    for line in lines:
        if line.startswith("Row: "):
            if cur:
                records.append("\n".join(cur))
            cur = [line]
        else:
            cur.append(line)
    if cur:
        records.append("\n".join(cur))

    out = []
    for rec in records:
        # Find the leading "Row: N " prefix and strip it.
        body = rec
        idx = body.find("address=")
        if idx < 0:
            continue
        rest = body[idx + len("address="):]

        date_marker = ", date="
        date_idx = rest.rfind(date_marker)
        if date_idx < 0:
            continue
        address_body = rest[:date_idx]
        date_str = rest[date_idx + len(date_marker):].strip()

        body_marker = ", body="
        body_idx = address_body.find(body_marker)
        if body_idx < 0:
            continue
        address = address_body[:body_idx]
        sms_body = address_body[body_idx + len(body_marker):]

        try:
            date_ms = int(date_str)
        except ValueError:
            continue

        out.append({
            "address": address,
            "body": sms_body,
            "date_ms": date_ms,
            "date": datetime.fromtimestamp(date_ms / 1000, tz=timezone.utc).isoformat(),
        })

    return out


def dedupe(rows):
    seen = set()
    uniq = []
    for r in rows:
        key = (r["body"], r["date_ms"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)
    return uniq


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("--out", required=True)
    ap.add_argument("--label", default="")
    args = ap.parse_args()

    rows = parse(args.input)
    rows = dedupe(rows)
    rows.sort(key=lambda r: r["date_ms"])

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)

    if not rows:
        print(f"[{args.label}] no rows parsed", file=sys.stderr)
        return

    first = rows[0]["date"]
    last = rows[-1]["date"]
    print(f"[{args.label}] rows={len(rows)} first={first} last={last} out={args.out}")


if __name__ == "__main__":
    main()