import datetime
import json
import os
import re
import unittest

from _bootstrap import (
    m, gl, CLOCK, PARTY_A_ADDRESS, PARTY_B_ADDRESS, STRANGER_ADDRESS,
    make_contract, set_caller, create_bounty, active_bounty, locked_bounty, ruled_bounty, get,
    pass_appeal_window, expect_user_error, pr_url, _state,
)
from test_jury import appealed, jury_case
from test_settlement import settle, ruling, D

SECOND = datetime.timedelta(seconds=1)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def parse(value):
    return datetime.datetime.fromisoformat(value)


def timeline(c, bid):
    return json.loads(c.get_timeline(bid))


def at(c, moment):
    CLOCK.set(moment)
    set_caller(STRANGER_ADDRESS)


class TestTimeline(unittest.TestCase):
    def setUp(self):
        self.c = make_contract()

    def test_unknown_bounty_is_an_error(self):
        expect_user_error(self, self.c.get_timeline, "bounty_9")

    def test_posted_bounty_waits_for_the_contributor(self):
        bid = create_bounty(self.c)
        t = timeline(self.c, bid)
        self.assertEqual((t["status"], t["next_step"]["method"], t["next_step"]["next_at"]), ("posted", "accept_bounty", None))
        self.assertEqual([e["key"] for e in t["events"]], ["created", "deadline"])
        self.assertIsNone(t["fallback"])

    def test_active_without_evidence_points_to_submission_and_expiry(self):
        bid = active_bounty(self.c)
        t = timeline(self.c, bid)
        self.assertEqual(t["next_step"]["method"], "submit_evidence")
        self.assertEqual(t["fallback"]["method"], "expire_no_evidence")
        self.assertEqual(t["fallback"]["at"], get(self.c, bid)["evidence_deadline"])
        at(self.c, parse(t["fallback"]["at"]))
        expect_user_error(self, self.c.expire_no_evidence, bid)
        at(self.c, parse(t["fallback"]["at"]) + SECOND)
        self.c.expire_no_evidence(bid)
        self.assertEqual(get(self.c, bid)["status"], "settled")

    def test_one_submission_lock_time_matches_the_contract(self):
        bid = active_bounty(self.c)
        set_caller(PARTY_B_ADDRESS)
        self.c.submit_evidence(bid, [pr_url(7)])
        t = timeline(self.c, bid)
        self.assertEqual((t["next_step"]["method"], t["next_step"]["next_at"]), ("lock_evidence", get(self.c, bid)["evidence_lock_at"]))
        at(self.c, parse(t["next_step"]["next_at"]))
        expect_user_error(self, self.c.lock_evidence, bid)
        at(self.c, parse(t["next_step"]["next_at"]) + SECOND)
        self.c.lock_evidence(bid)
        self.assertEqual(get(self.c, bid)["status"], "evidence_locked")

    def test_two_submissions_lock_immediately_and_move_to_adjudication(self):
        bid = active_bounty(self.c)
        set_caller(PARTY_B_ADDRESS)
        self.c.submit_evidence(bid, [pr_url(7)])
        set_caller(PARTY_A_ADDRESS)
        self.c.submit_evidence(bid, [pr_url(7)])
        t = timeline(self.c, bid)
        self.assertEqual((t["status"], t["next_step"]["method"]), ("evidence_locked", "adjudicate"))

    def test_locked_bounty_points_to_adjudicate_and_the_timeout(self):
        bid = locked_bounty(self.c)
        t = timeline(self.c, bid)
        b = get(self.c, bid)
        self.assertEqual((t["next_step"]["method"], t["next_step"]["next_at"]), ("adjudicate", b["deadline"]))
        base = max(parse(b["evidence_snapshot"]["locked_at"]), parse(b["deadline"]))
        expected = (base + datetime.timedelta(seconds=m.BountyAnchor.RESOLUTION_TIMEOUT_SECONDS)).isoformat()
        self.assertEqual((t["fallback"]["method"], t["fallback"]["at"]), ("expire_unruled", expected))
        at(self.c, parse(expected))
        expect_user_error(self, self.c.expire_unruled, bid)
        at(self.c, parse(expected) + SECOND)
        self.c.expire_unruled(bid)
        self.assertEqual(get(self.c, bid)["final_outcome"], m.OUT_UNDETERMINED)

    def test_ruled_bounty_settles_exactly_at_the_appeal_deadline(self):
        bid = ruling(self.c, D)
        t = timeline(self.c, bid)
        self.assertEqual((t["next_step"]["method"], t["next_step"]["next_at"]), ("settle_unappealed", get(self.c, bid)["appeal_deadline"]))
        at(self.c, parse(t["next_step"]["next_at"]))
        expect_user_error(self, self.c.settle_unappealed, bid)
        at(self.c, parse(t["next_step"]["next_at"]) + SECOND)
        self.c.settle_unappealed(bid)
        self.assertEqual(get(self.c, bid)["status"], "settled")

    def test_appeal_filed_points_to_the_jury_draw_and_recovery(self):
        bid = appealed(self.c)
        t = timeline(self.c, bid)
        b = get(self.c, bid)
        self.assertEqual((t["status"], t["next_step"]["method"]), ("appeal_filed", "draw_jury"))
        expected = (parse(b["appeal_deadline"]) + datetime.timedelta(seconds=m.BountyAnchor.RESOLUTION_TIMEOUT_SECONDS)).isoformat()
        self.assertEqual((t["fallback"]["method"], t["fallback"]["at"]), ("recover_stuck_appeal", expected))

    def test_jury_voting_points_to_settle_jury_after_reveal(self):
        bid = jury_case(self.c)
        t = timeline(self.c, bid)
        jury = get(self.c, bid)["jury"]
        self.assertEqual((t["status"], t["next_step"]["method"], t["next_step"]["next_at"]), ("jury_voting", "settle_jury", jury["reveal_deadline"]))
        keys = [e["key"] for e in t["events"]]
        self.assertIn("commit_deadline", keys)
        self.assertIn("reveal_deadline", keys)
        self.assertEqual(t["fallback"]["method"], "recover_stuck_appeal")

    def test_settled_and_cancelled_have_nothing_left_to_do(self):
        bid = ruling(self.c, D)
        settle(self.c, bid)
        cancelled = create_bounty(self.c, deadline=CLOCK.now + datetime.timedelta(days=5))
        set_caller(PARTY_A_ADDRESS)
        self.c.cancel_bounty(cancelled)
        for name in (bid, cancelled):
            t = timeline(self.c, name)
            self.assertIsNone(t["next_step"]["method"])
            self.assertIsNone(t["fallback"])
        self.assertEqual(timeline(self.c, bid)["events"][-1]["key"], "settled")

    def test_events_are_in_time_order_and_valid_timestamps(self):
        bid = ruling(self.c, D)
        stamps = [parse(e["at"]) for e in timeline(self.c, bid)["events"]]
        self.assertEqual(stamps, sorted(stamps))
        self.assertGreaterEqual(len(stamps), 5)

    def test_creation_precedes_acceptance_when_they_share_a_moment(self):
        bid = active_bounty(self.c)
        keys = [e["key"] for e in timeline(self.c, bid)["events"]]
        self.assertLess(keys.index("created"), keys.index("accepted"))

    def test_timeline_never_changes_state(self):
        bid = ruling(self.c, D)
        before = _state(self.c)
        timeline(self.c, bid)
        self.c.list_by_status("ruled", 0, 5)
        self.assertEqual(_state(self.c), before)

    def test_timeline_is_deterministic(self):
        bid = ruling(self.c, D)
        self.assertEqual(self.c.get_timeline(bid), self.c.get_timeline(bid))


class TestListByStatus(unittest.TestCase):
    def setUp(self):
        self.c = make_contract()

    def make_active(self, count):
        ids = []
        for i in range(count):
            CLOCK.reset()
            ids.append(active_bounty(self.c, issue=500 + i))
        return ids

    def listing(self, status, offset=0, limit=10):
        return json.loads(self.c.list_by_status(status, offset, limit))

    def test_unknown_status_is_rejected(self):
        expect_user_error(self, self.c.list_by_status, "done", 0, 5)
        expect_user_error(self, self.c.list_by_status, "", 0, 5)

    def test_every_valid_status_is_accepted_on_an_empty_contract(self):
        for status in m.BountyAnchor.VALID_STATUSES:
            data = self.listing(status)
            self.assertEqual((data["matched"], data["bounties"]), (0, []))

    def test_valid_statuses_match_the_statuses_the_contract_assigns(self):
        with open(os.path.join(ROOT, "contract.py"), encoding="utf-8") as handle:
            source = handle.read()
        assigned = set(re.findall(r'bounty\["status"\] = "([a-z_]+)"', source)) | {"posted"}
        self.assertEqual(set(m.BountyAnchor.VALID_STATUSES), assigned)

    def test_only_matching_bounties_newest_first(self):
        ids = self.make_posted_and_active()
        data = self.listing("active")
        self.assertEqual([r["bounty_id"] for r in data["bounties"]], [ids["active"][1], ids["active"][0]])
        self.assertEqual(data["matched"], 2)
        self.assertEqual([r["bounty_id"] for r in self.listing("posted")["bounties"]], ids["posted"])

    def make_posted_and_active(self):
        out = {"active": [], "posted": []}
        CLOCK.reset()
        out["active"].append(active_bounty(self.c, issue=600))
        CLOCK.reset()
        out["posted"].append(create_bounty(self.c, issue=601))
        CLOCK.reset()
        out["active"].append(active_bounty(self.c, issue=602))
        return out

    def test_pagination_walks_every_match_once(self):
        ids = self.make_active(5)
        seen = []
        for offset in (0, 2, 4):
            seen += [r["bounty_id"] for r in self.listing("active", offset, 2)["bounties"]]
        self.assertEqual(seen, list(reversed(ids)))

    def test_limit_is_capped(self):
        self.make_active(2)
        data = self.listing("active", 0, 10 ** 6)
        self.assertEqual(data["limit"], m.BountyAnchor.MAX_LIST_LIMIT)

    def test_settled_status_follows_settlement(self):
        bid = ruling(self.c, D)
        self.assertEqual(self.listing("settled")["matched"], 0)
        self.assertEqual([r["bounty_id"] for r in self.listing("ruled")["bounties"]], [bid])
        settle(self.c, bid)
        self.assertEqual([r["bounty_id"] for r in self.listing("settled")["bounties"]], [bid])
        self.assertEqual(self.listing("ruled")["matched"], 0)

    def test_scan_is_bounded_and_flags_truncation(self):
        self.make_active(3)
        self.c.MAX_LEDGER_SCAN = 2
        data = self.listing("active")
        self.assertEqual((data["matched"], data["truncated"]), (2, True))

    def test_status_is_trimmed(self):
        self.make_active(1)
        self.assertEqual(self.listing("  active  ")["matched"], 1)

    def test_rows_are_the_standard_summaries(self):
        ids = self.make_active(1)
        row = self.listing("active")["bounties"][0]
        self.assertEqual(row, json.loads(self.c.list_bounties(0, 5))["bounties"][0])
        self.assertEqual(row["bounty_id"], ids[0])


if __name__ == "__main__":
    unittest.main()
