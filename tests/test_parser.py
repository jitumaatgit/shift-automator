"""
Test the regex parser against all 20+ known sample shifts.
Run with: pytest tests/test_parser.py -v
"""
import sys
from pathlib import Path
from datetime import datetime

from parser import parse_shift_text, parse_confirmation, classify_incoming, load_sample_shifts



SAMPLE_SHIFTS = load_sample_shifts()


class TestParserOnAllSamples:
    """Run parser across every sample shift and assert core fields."""

    def test_all_samples_loaded(self):
        assert len(SAMPLE_SHIFTS) >= 20, f"Expected 20+ samples, got {len(SAMPLE_SHIFTS)}"
        ids = [sid for sid, _ in SAMPLE_SHIFTS]
        print(f"Loaded samples: {ids}")

    def test_special_projects_samples(self):
        """Samples 1-7 are Special Projects."""
        sp_samples = [(sid, text) for sid, text in SAMPLE_SHIFTS if text.startswith("Open shift available at [Special Projects]")]
        assert len(sp_samples) >= 5

        for sid, text in sp_samples:
            offer, errors = parse_shift_text(text, reference_date=datetime(2026, 4, 29))

            assert offer.building == "Special Projects", f"[{sid}] Wrong building"
            assert offer.title, f"[{sid}] Missing title"
            assert offer.start_time.year > 2000, f"[{sid}] Missing start_time"
            assert offer.end_time.year > 2000, f"[{sid}] Missing end_time"
            assert offer.claim_code, f"[{sid}] Missing claim_code"
            assert offer.shift_note, f"[{sid}] Missing shift_note"
            assert "8225 NE Example St" in offer.address or "Portland" in offer.address, f"[{sid}] Missing address: {offer.address}"

            assert offer.start_time.year == 2026, f"[{sid}] Wrong year: {offer.start_time.year}"

            print(f"[OK] {sid}: {offer.title} @ {offer.start_time.strftime('%a %b %d %H:%M')} ({offer.duration_hours:.1f}h) code={offer.claim_code}")

    def test_building_lunch_samples(self):
        """Samples 8-20+b are Building Lunch Coverage."""
        bl_samples = [(sid, text) for sid, text in SAMPLE_SHIFTS if text.startswith("Open shift available at [Building Lunch Coverage]")]
        assert len(bl_samples) >= 10

        for sid, text in bl_samples:
            offer, errors = parse_shift_text(text, reference_date=datetime(2026, 5, 1))

            assert offer.building == "Building Lunch Coverage", f"[{sid}] Wrong building"
            assert offer.title, f"[{sid}] Missing title"
            assert offer.start_time.year > 2000, f"[{sid}] Missing start_time"
            assert offer.end_time.year > 2000, f"[{sid}] Missing end_time"
            assert offer.claim_code, f"[{sid}] Missing claim_code"

            assert len(offer.locations) == 4, f"[{sid}] Expected 4 locations, got {len(offer.locations)}"

            for loc in offer.locations:
                assert loc.address, f"[{sid}] Location {loc.name} missing address"
                assert loc.start_time < loc.end_time, f"[{sid}] Location {loc.name} invalid times"

            names = [loc.name for loc in offer.locations]
            assert "Medford" in names, f"[{sid}] Missing Medford"
            assert "Shoreline" in names, f"[{sid}] Missing Shoreline"

            print(f"[OK] {sid}: {offer.title} @ {offer.start_time.strftime('%a %b %d %H:%M')} ({offer.duration_hours:.1f}h) {len(offer.locations)} sites code={offer.claim_code}")

    def test_claim_codes_unique(self):
        """All claim codes should be unique across samples."""
        codes = []
        for sid, text in SAMPLE_SHIFTS:
            offer, errors = parse_shift_text(text)
            if offer.claim_code:
                codes.append(offer.claim_code)

        assert len(codes) == len(set(codes)), f"Duplicate claim codes found: {codes}"

    def test_building_lunch_time_fixups(self):
        """Verify semicolons in times are normalized (e.g. 3;15am -> 3:15am)."""
        bl_samples = [(sid, text) for sid, text in SAMPLE_SHIFTS if "Building Lunch Coverage" in text]
        for sid, text in bl_samples:
            offer, errors = parse_shift_text(text)
            for loc in offer.locations:
                assert ";" not in loc.start_time.strftime("%H:%M"), f"[{sid}] Unfixed semicolon in start time"
                assert ";" not in loc.end_time.strftime("%H:%M"), f"[{sid}] Unfixed semicolon in end time"

    def test_special_projects_contact_extraction(self):
        """Verify contact name/phone extracted from shift note."""
        sp_samples = [(sid, text) for sid, text in SAMPLE_SHIFTS if "Special Projects" in text]
        for sid, text in sp_samples:
            offer, errors = parse_shift_text(text)
            assert offer.contact_name == "Jordan Ellis", f"[{sid}] Wrong contact: {offer.contact_name}"
            assert offer.contact_phone == "503-555-0109", f"[{sid}] Wrong phone: {offer.contact_phone}"

    def test_duration_calculations(self):
        """Verify duration math is correct for known samples."""
        text = [t for s, t in SAMPLE_SHIFTS if s == "1"][0]
        offer, errors = parse_shift_text(text, reference_date=datetime(2026, 4, 29))
        assert offer.duration_hours == 6.0, f"Expected 6h, got {offer.duration_hours}"

        text = [t for s, t in SAMPLE_SHIFTS if s == "8"][0]
        offer, errors = parse_shift_text(text, reference_date=datetime(2026, 5, 13))
        assert offer.duration_hours == 3.0, f"Expected 3h, got {offer.duration_hours}"

    def test_building_lockout_parsed(self):
        """Sample c (Building Lockout) should parse with correct times and building."""
        matching = [(sid, text) for sid, text in SAMPLE_SHIFTS if sid == "c"]
        assert len(matching) == 1, f"Expected 1 sample 'c', got {len(matching)}"
        sid, text = matching[0]
        offer, errors = parse_shift_text(text, reference_date=datetime(2026, 5, 4))

        assert offer.building == "Building Lockout", f"[{sid}] Wrong building: {offer.building}"
        assert offer.title == "Building Lockout", f"[{sid}] Wrong title: {offer.title}"
        assert offer.start_time.year > 2000, f"[{sid}] Missing start_time"
        assert offer.end_time.year > 2000, f"[{sid}] Missing end_time"
        assert offer.claim_code == "1791757", f"[{sid}] Wrong claim code: {offer.claim_code}"
        assert offer.duration_hours == 2.0, f"[{sid}] Expected 2h, got {offer.duration_hours}"
        assert offer.cancel_number == "", f"[{sid}] Should not have cancel number"
        print(f"[OK] {sid}: {offer.title} @ {offer.start_time} ({offer.duration_hours:.1f}h) code={offer.claim_code}")

    def test_building_lockout_contact(self):
        """Building Lockout contact format 'Contact @503-555-0134' should be extracted."""
        text = [t for s, t in SAMPLE_SHIFTS if s == "c"][0]
        offer, errors = parse_shift_text(text)
        assert offer.contact_phone == "503-555-0134", f"Expected 503-555-0134, got {offer.contact_phone}"
        print(f"[OK] c: contact={offer.contact_name} phone={offer.contact_phone}")

    def test_header_search_across_lines(self):
        """Parser should find header even if a prefix line exists (forwarded text)."""
        header = "Open shift available at [Special Projects] Special Projects starting at Wed 29/Apr 11:00am - 05:00pm"
        prefix_text = f"Some prefix line\n{header}\nShift Note:Test\nreply 1234567 (only this number) to claim."
        offer, errors = parse_shift_text(prefix_text, reference_date=datetime(2026, 4, 29))
        assert offer.start_time.year > 2000, "Should parse header even with prefix"
        assert offer.claim_code == "1234567"
        assert offer.building == "Special Projects"
        assert len(errors) == 0, f"Should have no parse errors: {errors}"

    def test_estate_building_parsed(self):
        """Estate FD shift should parse with correct building and address."""
        text = "Open shift available at [Estate] FD starting at Sat 09/May 07:00am - 03:00pm\nShift Note:Covering for Ryan Rogue\nEstate Address: 225 NW Test Ct, Portland, OR 97209, United States\nIf you can do this shift, reply 3751288 (only this number) to claim."
        offer, errors = parse_shift_text(text, reference_date=datetime(2026, 5, 5))

        assert offer.building == "Estate", f"Expected Estate, got {offer.building}"
        assert offer.title == "FD", f"Expected FD, got {offer.title}"
        assert offer.start_time.year > 2000
        assert offer.end_time.year > 2000
        assert offer.claim_code == "3751288"
        assert "225 NW Test Ct" in offer.address, f"Address not extracted: {offer.address}"
        print(f"[OK] Estate FD: {offer.title} @ {offer.start_time} address={offer.address}")

    def test_bracket_fuzzy_resolves_known_prefix(self):
        """Bracket [River Haven - FD] should resolve to RIVER_HAVEN via fuzzy fallback."""
        text = "Open shift available at [River Haven - FD] On-Call River Haven FD starting at Mon 18/May 08:00am - 04:00pm\nShift Note:Test\nreply 1234567 (only this number) to claim."
        offer, errors = parse_shift_text(text, reference_date=datetime(2026, 5, 18))
        assert offer.building == "River Haven", f"Expected River Haven, got {offer.building}"
        assert offer.title

    def test_bracket_fuzzy_resolves_estate_j1(self):
        """Bracket [Estate - J1] should resolve to ESTATE via fuzzy fallback."""
        text = "Open shift available at [Estate - J1] On-Call Estate J1 starting at Mon 18/May 08:00am - 04:00pm\nShift Note:Test\nEstate Address: 225 NW Test Ct\nreply 1234567 (only this number) to claim."
        offer, errors = parse_shift_text(text, reference_date=datetime(2026, 5, 18))
        assert offer.building == "Estate", f"Expected Estate, got {offer.building}"

    def test_bracket_fuzzy_unknown_prefix_still_unknown(self):
        """Bracket [Xyz - FD] with unknown prefix should still be UNKNOWN."""
        text = "Open shift available at [Xyz - FD] Some Title starting at Mon 18/May 08:00am - 04:00pm\nShift Note:Test\nreply 1234567 (only this number) to claim."
        offer, errors = parse_shift_text(text, reference_date=datetime(2026, 5, 18))
        assert offer.building == "Unknown", f"Expected Unknown, got {offer.building}"

    def test_bracket_exact_match_still_works(self):
        """Existing exact matches like [Estate - Front Desk] still resolve correctly."""
        text = "Open shift available at [Estate - Front Desk] On-Call Estate Front Desk starting at Mon 18/May 08:00am - 04:00pm\nShift Note:Test\nEstate Address: 225 NW Test Ct\nreply 1234567 (only this number) to claim."
        offer, errors = parse_shift_text(text, reference_date=datetime(2026, 5, 18))
        assert offer.building == "Estate", f"Expected Estate, got {offer.building}"

    def test_stdin_piping_parses_correctly(self):
        """Piping shift text to main.py via stdin should parse correctly."""
        import subprocess
        import json
        text = "Open shift available at [Special Projects] Special Projects starting at Wed 29/Apr 11:00am - 05:00pm\nShift Note:Test\nIf you can do this shift, reply 9998888 (only this number) to claim."
        result = subprocess.run(
            [sys.executable, "src/main.py", "--json"],
            input=text,
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent.parent),
            timeout=30,
        )
        stdout = result.stdout
        json_start = stdout.index("{")
        json_end = stdout.rindex("}") + 1
        data = json.loads(stdout[json_start:json_end])
        assert data["claim_code"] == "9998888", f"Wrong claim code from stdin: {data}"
        assert data["category"] == "Special Projects"


class TestConfirmationParsing:
    def _make_confirmation(self, building="STS", title="On-Call STS Front Desk", day="Sat", date="09/May", start="07:00am", end="03:00pm", address="707 Nw Example St, Portland, OR 97209"):
        return (
            f"Congratulations! You are now booked to do shift [{building}] {title} "
            f"starting at {day} {date} {start} - {end}\n"
            f"Shift Note: Coverage for Jeremiah McKessey.\n"
            f"STS Address : {address}"
        )

    def test_parse_confirmation_basic(self):
        text = self._make_confirmation()
        offer = parse_confirmation(text, reference_date=datetime(2026, 5, 9))
        assert offer is not None, "Should parse confirmation"
        assert offer.building == "STS", f"Expected STS, got {offer.building}"
        assert offer.title == "On-Call STS Front Desk"
        assert offer.start_time == datetime(2026, 5, 9, 7, 0)
        assert offer.end_time == datetime(2026, 5, 9, 15, 0)
        assert offer.duration_hours == 8.0

    def test_parse_confirmation_special_projects(self):
        text = "Congratulations! You are now booked to do shift [Special Projects] Special Projects starting at Wed 29/Apr 11:00am - 05:00pm\nShift Note:Evergreen Crossing Turnovers."
        offer = parse_confirmation(text, reference_date=datetime(2026, 4, 29))
        assert offer is not None
        assert offer.building == "Special Projects"
        assert offer.start_time.hour == 11

    def test_parse_confirmation_fuzzy_bracket(self):
        text = "Congratulations! You are now booked to do shift [River Haven - FD] On-Call Front Desk starting at Mon 18/May 08:00am - 04:00pm"
        offer = parse_confirmation(text, reference_date=datetime(2026, 5, 18))
        assert offer is not None
        assert offer.building == "River Haven"
        assert offer.title == "On-Call Front Desk"

    def test_parse_confirmation_nonsense_input(self):
        offer = parse_confirmation("This is not a confirmation", reference_date=datetime(2026, 5, 18))
        assert offer is None

    def test_classify_confirmation(self):
        text = self._make_confirmation()
        assert classify_incoming(text) == "confirmation"

    def test_classify_rejection(self):
        assert classify_incoming("Sorry this shift has already been taken or has been closed.") == "rejection"
        assert classify_incoming("Sorry, this position has been filled.") == "rejection"

    def test_classify_offer(self):
        text = "Open shift available at [Special Projects] Special Projects starting at Wed 29/Apr 11:00am - 05:00pm\nreply 9998888 (only this number) to claim."
        assert classify_incoming(text) == "offer"

    def test_classify_garbage(self):
        assert classify_incoming("") == "garbage"
        assert classify_incoming("   ") == "garbage"
        assert classify_incoming("Open") == "garbage"
        # Non-shift text without rejection/confirmation patterns is classified as "offer"
        # (router passes it to process_shift_text which parses and scores it normally)
        assert classify_incoming("Help me with something") == "offer"