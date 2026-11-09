import datetime
import json
import unittest

from _bootstrap import (
    m, CLOCK, DAY, PARTY_A_ADDRESS, PARTY_B_ADDRESS, STRANGER_ADDRESS, JUROR_ADDRESSES, REWARD, BOND,
    make_contract, set_caller, create_bounty, active_bounty, ruled_bounty, get, pending, pass_appeal_window,
    register_jurors, pr_json, open_pr_json, pr_url, _state,
)

D, P, U = m.OUT_DELIVERED, m.OUT_PARTIAL, m.OUT_UNDETERMINED


def settle(c, bid):
    pass_appeal_window(c, bid)
    set_caller(STRANGER_ADDRESS)
    c.settle_unappealed(bid)
    return get(c, bid)


def settled_delivered(c, **over):
    bid = ruled_bounty(c, pages={pr_url(7): pr_json(7)}, model={"outcome": D, "reasoning": "ok"}, **over)
    return bid, settle(c, bid)


def ledger(c):
    return json.loads(c.get_ledger())


def profile(c, address):
    return json.loads(c.get_profile(address))


class TestLedger(unittest.TestCase):
    def setUp(self):
        self.c = make_contract()

    def test_empty_contract(self):
        data = ledger(self.c)
        self.assertEqual((data["total"], data["scanned"], data["truncated"]), (0, 0, False))
        self.assertEqual((data["by_status"], data["by_outcome"]), ({}, {}))
        self.assertEqual((data["reward_volume"], data["paid_to_contributors"], data["returned_to_sponsors"]),
                         ("0", "0", "0"))

    def test_counts_statuses_outcomes_and_money(self):
        settled_delivered(self.c)
        cancelled = create_bounty(self.c, issue=101, deadline=CLOCK.now + datetime.timedelta(days=5))
        set_caller(PARTY_A_ADDRESS)
        self.c.cancel_bounty(cancelled)
        active_bounty(self.c, issue=102, deadline=CLOCK.now + datetime.timedelta(days=3))
        data = ledger(self.c)
        self.assertEqual(data["total"], 3)
        self.assertEqual(data["by_status"], {"settled": 1, "cancelled": 1, "active": 1})
        self.assertEqual(data["by_outcome"], {D: 1})
        self.assertEqual(data["reward_volume"], str(2 * REWARD))
        self.assertEqual(data["paid_to_contributors"], str(REWARD + BOND))
        self.assertEqual(data["returned_to_sponsors"], "0")

    def test_partial_outcome_splits_the_money_in_the_report(self):
        bid = ruled_bounty(self.c, pages={pr_url(7): open_pr_json(7)},
                           model={"outcome": P, "reasoning": "substantive work"})
        settle(self.c, bid)
        data = ledger(self.c)
        self.assertEqual(data["by_outcome"], {P: 1})
        self.assertEqual(int(data["paid_to_contributors"]) + int(data["returned_to_sponsors"]), REWARD + BOND)
        self.assertEqual(int(data["paid_to_contributors"]), BOND + REWARD // 2)

    def test_report_matches_the_withdrawable_balances(self):
        settled_delivered(self.c)
        data = ledger(self.c)
        owed = pending(self.c, PARTY_A_ADDRESS) + pending(self.c, PARTY_B_ADDRESS)
        self.assertEqual(int(data["paid_to_contributors"]) + int(data["returned_to_sponsors"]), owed)

    def test_report_does_not_change_state(self):
        settled_delivered(self.c)
        before = _state(self.c)
        ledger(self.c)
        profile(self.c, PARTY_B_ADDRESS)
        self.assertEqual(_state(self.c), before)

    def test_scan_is_bounded_and_flags_truncation(self):
        for i in range(3):
            CLOCK.reset()
            create_bounty(self.c, issue=200 + i)
        self.c.MAX_LEDGER_SCAN = 2
        data = ledger(self.c)
        self.assertEqual((data["total"], data["scanned"], data["truncated"]), (3, 2, True))
        self.assertEqual(sum(data["by_status"].values()), 2)

    def test_report_is_deterministic(self):
        settled_delivered(self.c)
        self.assertEqual(self.c.get_ledger(), self.c.get_ledger())


class TestProfile(unittest.TestCase):
    def setUp(self):
        self.c = make_contract()

    def test_unknown_address_is_all_zero(self):
        data = profile(self.c, STRANGER_ADDRESS)
        self.assertEqual((data["bounties_as_sponsor"], data["bounties_as_contributor"]), (0, 0))
        self.assertEqual((data["received_as_contributor"], data["returned_as_sponsor"]), ("0", "0"))
        self.assertEqual((data["recent_bounties"], data["contributor_outcomes"]), ([], {}))
        self.assertEqual(data["pending_withdrawal"], "0")
        self.assertEqual(data["juror"]["stake"], "0")

    def test_sponsor_and_contributor_views_of_one_settled_bounty(self):
        bid, _ = settled_delivered(self.c)
        sponsor = profile(self.c, PARTY_A_ADDRESS)
        contributor = profile(self.c, PARTY_B_ADDRESS)
        self.assertEqual((sponsor["bounties_as_sponsor"], sponsor["bounties_as_contributor"]), (1, 0))
        self.assertEqual((contributor["bounties_as_sponsor"], contributor["bounties_as_contributor"]), (0, 1))
        self.assertEqual(contributor["received_as_contributor"], str(REWARD + BOND))
        self.assertEqual(contributor["contributor_outcomes"], {D: 1})
        self.assertEqual(contributor["pending_withdrawal"], str(REWARD + BOND))
        self.assertEqual(sponsor["returned_as_sponsor"], "0")
        self.assertEqual(contributor["recent_bounties"], [bid])

    def test_address_case_does_not_matter(self):
        settled_delivered(self.c)
        lower = profile(self.c, PARTY_B_ADDRESS.lower())
        upper = profile(self.c, "0x" + PARTY_B_ADDRESS[2:].upper())
        self.assertEqual(lower, upper)
        self.assertEqual(lower["bounties_as_contributor"], 1)

    def test_unsettled_bounties_count_but_pay_nothing(self):
        active_bounty(self.c)
        data = profile(self.c, PARTY_B_ADDRESS)
        self.assertEqual(data["bounties_as_contributor"], 1)
        self.assertEqual((data["received_as_contributor"], data["contributor_outcomes"]), ("0", {}))

    def test_recent_list_is_newest_first_and_capped(self):
        ids = []
        for i in range(m.BountyAnchor.MAX_PROFILE_RECENT + 3):
            CLOCK.reset()
            ids.append(create_bounty(self.c, issue=300 + i))
        data = profile(self.c, PARTY_A_ADDRESS)
        self.assertEqual(data["bounties_as_sponsor"], len(ids))
        self.assertEqual(data["recent_bounties"], list(reversed(ids))[:m.BountyAnchor.MAX_PROFILE_RECENT])

    def test_juror_record_is_included(self):
        register_jurors(self.c, count=1, base_stake=1000)
        data = profile(self.c, JUROR_ADDRESSES[0])
        self.assertEqual(data["juror"]["stake"], "1000")
        self.assertEqual(data["juror"]["cases_participated"], 0)

    def test_profile_scan_is_bounded(self):
        for i in range(3):
            CLOCK.reset()
            create_bounty(self.c, issue=400 + i)
        self.c.MAX_LEDGER_SCAN = 1
        data = profile(self.c, PARTY_A_ADDRESS)
        self.assertEqual((data["scanned"], data["truncated"], data["bounties_as_sponsor"]), (1, True, 1))

    def test_money_in_profiles_never_exceeds_money_in_the_ledger(self):
        settled_delivered(self.c)
        total = int(ledger(self.c)["paid_to_contributors"]) + int(ledger(self.c)["returned_to_sponsors"])
        seen = sum(int(profile(self.c, a)["received_as_contributor"]) + int(profile(self.c, a)["returned_as_sponsor"])
                   for a in (PARTY_A_ADDRESS, PARTY_B_ADDRESS))
        self.assertEqual(seen, total)


if __name__ == "__main__":
    unittest.main()
