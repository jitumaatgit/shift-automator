# this code is pretty deprecated, as I have added more types of shifts. but can be used as a reference
"""Test all sample shifts against the parser."""
import re
from pathlib import Path
from datetime import datetime

from parser import parse_shift_text, parse_with_fallback

SENTINEL = datetime(1970, 1, 1)

if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent

    with open(root / "data" / "sample_shifts.md", encoding="utf-8") as f:
        content = f.read()

    sample_headers = list(re.finditer(r"^## (\d+)$", content, re.MULTILINE))
    samples = []
    for i, h in enumerate(sample_headers):
        start = h.end()
        end = sample_headers[i + 1].start() if i + 1 < len(sample_headers) else len(content)
        text = content[start:end].strip()
        samples.append((int(h.group(1)), text))

    print(f"Loaded {len(samples)} samples\n")

    ref_date = datetime(2026, 5, 4)

    results = []
    for sid, text in samples:
        offer, errors = parse_shift_text(text, reference_date=ref_date)

        passed = offer.start_time.year > 2000 and not errors
        results.append((sid, offer, passed, errors))

        status = "PASS" if passed else "FAIL"
        issues = "; ".join(errors) if errors else "none"
        print(f"[{status}] Sample {sid:2d} | {offer.building:30s} | {offer.title:40s} | "
              f"{offer.start_time.strftime('%H:%M') if offer.start_time.year > 2000 else 'N/A':>5s}-"
              f"{offer.end_time.strftime('%H:%M') if offer.end_time.year > 2000 else 'N/A':>5s} | "
              f"code={offer.claim_code or 'N/A':>7s} | issues: {issues}")

    sid26 = next((s for s in samples if s[0] == 26), None)
    if sid26:
        print("\n" + "=" * 80)
        _, text26 = sid26
        offer26, _ = parse_shift_text(text26, reference_date=ref_date)
        print(f"\n--- Sample 26 (Building Lockout) DEEP DIVE ---")
        print(f"Raw first line: {text26.splitlines()[0]}")
        print(f"Category: {offer26.category}")
        print(f"Title: {offer26.title}")
        print(f"Start: {offer26.start_time}")
        print(f"End: {offer26.end_time}")
        print(f"Claim code: {offer26.claim_code}")
        print(f"Shift note: {offer26.shift_note}")

        header_re = re.compile(
            r"Open shift available at \[(?P<category>[^\]]+)\] "
            r"(?P<title>.+?) "
            r"starting at "
            r"(?P<day>[A-Za-z]{3}) "
            r"(?P<date>\d{1,2}/[A-Za-z]{3}) "
            r"(?P<start_time>\d{1,2}:\d{2}[ap]m) "
            r"- "
            r"(?P<end_time>\d{1,2}:\d{2}[ap]m)"
        )
        m = header_re.search(text26.splitlines()[0])
        print(f"\nHeader regex match: {m is not None}")
        if m:
            print(f"  Groups: {m.groupdict()}")
        else:
            print("  HEADER_RE does NOT match 'Building Lockout' line")

        print("\n" + "=" * 80)
        print("\n--- Log Entry 7 & 8 Inference ---")
        print("Entry 8 was from 'the real friend test' and had 'Could not parse header line'")
        print("Sample 26 is 'Building Lockout' which also won't parse (different category)")
        print("These are likely the SAME text: the friend forwarded a Building Lockout text")

        friends_text = text26
        offer_fallback, _ = parse_with_fallback(friends_text, reference_date=ref_date)
        print(f"\nparse_with_fallback on Building Lockout text:")
        print(f"  Category: {offer_fallback.category}")
        print(f"  Start time: {offer_fallback.start_time}")
        print(f"  Decision: {offer_fallback.decision}")

    print("\n" + "=" * 80)
    print("SUMMARY TABLE")
    print("=" * 80)
    print(f"{'Sample':>6} | {'Status':>6} | {'Category':<30} | Title")
    print("-" * 80)
    pass_count = 0
    fail_count = 0
    for sid, offer, passed, _ in results:
        s = "PASS" if passed else "FAIL"
        if passed:
            pass_count += 1
        else:
            fail_count += 1
        print(f"{sid:>6} | {s:>6} | {offer.building:<30} | {offer.title}")
    print("-" * 80)
    print(f"TOTAL: {pass_count} PASS, {fail_count} FAIL out of {len(results)}")

    failures = [(sid, offer, errors) for sid, offer, passed, errors in results if not passed]
    if failures:
        print(f"\n{'=' * 80}")
        print("FAILURE DETAILS")
        print(f"{'=' * 80}")
        for sid, offer, errors in failures:
            print(f"\n--- Sample {sid} ---")
            print(f"  Category: {offer.building}")
            print(f"  Title: '{offer.title}'")
            print(f"  Start: {offer.start_time}")
            print(f"  End: {offer.end_time}")
            print(f"  Claim code: '{offer.claim_code}'")
            print(f"  Errors: {errors}")
            print(f"  First 120 chars of text: {offer.raw_text[:120]}")
