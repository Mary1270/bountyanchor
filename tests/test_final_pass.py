"""Final review pass: claim priority, timestamp parsing and the clock."""
import datetime
import unittest
from unittest.mock import patch

from _bootstrap import (
    m, gl, REAL_NOW_UTC, REPO, make_contract, ruled_bounty, get, pr_json, open_pr_json, pr_url,
)

P = m.OUT_PARTIAL


class TestClaimPriority(unittest.TestCase):
    def test_partial_by_maintainer_silence_claims_the_pending_pull_request_not_an_unlinked_one(self):
        c = make_contract()
        pages = {pr_url(3): pr_json(3, body="unrelated cleanup"), pr_url(9): open_pr_json(9)}
        bid = ruled_bounty(c, pages=pages, model={"outcome": P})
        b = get(c, bid)
        self.assertEqual((b["tier1_outcome"], b["claimed_pr_key"]), (P, f"{REPO}#9"))
        self.assertEqual(c.get_pr_claim(REPO, 3), "")

    def test_candidates_are_ordered_by_strength_not_number(self):
        a = {"delivered_prs": [20], "pending_prs": [10], "ambiguous_prs": [1], "rejected_prs": [2]}
        self.assertEqual(m.BountyAnchor._claim_candidates(m.OUT_PARTIAL, a), [20, 10, 1, 2])
        self.assertEqual(m.BountyAnchor._claim_candidates(m.OUT_DELIVERED, a), [20])


class TestTimestamps(unittest.TestCase):
    def test_a_trailing_z_is_accepted(self):
        self.assertEqual(m.BountyAnchor._parse_iso("2026-03-04T12:00:00Z"),
                         datetime.datetime(2026, 3, 4, 12, tzinfo=datetime.timezone.utc))

    def test_browser_iso_strings_create_a_bounty(self):
        from _bootstrap import create_bounty, DEFAULT_DEADLINE
        c = make_contract()
        with patch("_bootstrap.iso", lambda d: d.strftime("%Y-%m-%dT%H:%M:%S.000Z")):
            bid = create_bounty(c)
        self.assertEqual(get(c, bid)["deadline"], DEFAULT_DEADLINE.isoformat())

    def test_the_clock_prefers_the_transaction_timestamp(self):
        fixed = "2030-01-02T03:04:05Z"
        with patch.object(gl, "message_raw", {"datetime": fixed}, create=True):
            self.assertEqual(REAL_NOW_UTC.__func__(), datetime.datetime(2030, 1, 2, 3, 4, 5, tzinfo=datetime.timezone.utc))

    def test_the_clock_falls_back_to_the_runtime_clock(self):
        now = REAL_NOW_UTC.__func__()
        self.assertEqual(now.utcoffset(), datetime.timedelta(0))


if __name__ == "__main__":
    unittest.main()
