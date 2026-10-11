"""Reproductions of the attacks and gaps raised in the external review."""
import datetime
import json
import unittest

from _bootstrap import (
    late_pr_json,
    m, gl, CLOCK, DAY, BASE, BASE_EPOCH, PARTY_A_ADDRESS, PARTY_B_ADDRESS, STRANGER_ADDRESS, REPO, REWARD, BOND,
    make_contract, set_caller, create_bounty, accept_bounty, locked_bounty, ruled_bounty, active_bounty, get, pending,
    pass_deadline, pass_appeal_window, adjudicate, pr_json, open_pr_json, search_json, pr_url, search_url, gh_ts,
    submit_and_lock, expect_user_error, assess, anchors,
)

D, P, N, U = m.OUT_DELIVERED, m.OUT_PARTIAL, m.OUT_NOT_DELIVERED, m.OUT_UNDETERMINED
HOUR = 3600


class TestPrOpenedBeforeTheBounty(unittest.TestCase):
    def test_an_old_merged_pull_request_is_not_a_delivery(self):
        a = assess({pr_url(7): pr_json(7, created_at=gh_ts(BASE_EPOCH - 5 * DAY))})
        self.assertEqual((a["delivered_prs"], a["failed_prs"], a["reports"][0]["verdict"]), ([], [], "unrelated"))

    def test_an_old_open_pull_request_is_not_pending(self):
        a = assess({pr_url(7): open_pr_json(7, created_at=gh_ts(BASE_EPOCH - 5 * DAY))})
        self.assertEqual((a["pending_prs"], a["failed_prs"], a["reports"][0]["verdict"]), ([], [], "unrelated"))

    def test_opened_exactly_at_creation_counts(self):
        a = assess({pr_url(7): pr_json(7, created_at=gh_ts(BASE_EPOCH))})
        self.assertEqual(a["delivered_prs"], [7])

    def test_opened_one_second_before_creation_does_not_count(self):
        a = assess({pr_url(7): pr_json(7, created_at=gh_ts(BASE_EPOCH - 1))})
        self.assertEqual(a["delivered_prs"], [])

    def test_the_report_exposes_the_check(self):
        a = assess({pr_url(7): pr_json(7, created_at=gh_ts(BASE_EPOCH - 1))})
        self.assertFalse(a["reports"][0]["opened_after"])

    def test_end_to_end_an_old_pull_request_cannot_win_a_bounty(self):
        c = make_contract()
        pages = {pr_url(7): pr_json(7, created_at=gh_ts(BASE_EPOCH - 5 * DAY))}
        bid = ruled_bounty(c, pages=pages, model=None)
        self.assertNotEqual(get(c, bid)["tier1_outcome"], D)
        self.assertEqual(c.get_pr_claim(REPO, 7), "")


class TestSearchIndexLag(unittest.TestCase):
    def setUp(self):
        self.c = make_contract()

    def locked(self):
        return locked_bounty(self.c, urls=[search_url()], both=True)

    def test_absence_right_after_the_deadline_is_not_enough(self):
        bid = self.locked()
        pass_deadline(self.c, bid)
        with self.assertRaises(gl.vm.UserError):
            adjudicate(self.c, bid, {search_url(): search_json(0)}, model=None)
        self.assertEqual(get(self.c, bid)["status"], "evidence_locked")

    def test_absence_a_day_after_the_deadline_counts(self):
        bid = self.locked()
        deadline = datetime.datetime.fromisoformat(get(self.c, bid)["deadline"])
        CLOCK.set(deadline + datetime.timedelta(seconds=m.ABSENCE_LAG_SECONDS))
        b = adjudicate(self.c, bid, {search_url(): search_json(0)}, model={"outcome": N})
        self.assertEqual(b["tier1_outcome"], N)

    def test_one_second_short_of_the_lag_does_not_count(self):
        bid = self.locked()
        deadline = datetime.datetime.fromisoformat(get(self.c, bid)["deadline"])
        CLOCK.set(deadline + datetime.timedelta(seconds=m.ABSENCE_LAG_SECONDS - 1))
        with self.assertRaises(gl.vm.UserError):
            adjudicate(self.c, bid, {search_url(): search_json(0)}, model=None)

    def test_a_late_pull_request_needs_no_lag(self):
        c = make_contract()
        pages = {pr_url(7): late_pr_json(7)}
        bid = locked_bounty(c, urls=list(pages), both=True)
        pass_deadline(c, bid)
        b = adjudicate(c, bid, pages, model={"outcome": N})
        self.assertEqual(b["tier1_outcome"], N)

    def test_the_lag_applies_to_the_jury_check_too(self):
        c = make_contract()
        bid = locked_bounty(c, urls=[search_url()], both=True)
        deadline = datetime.datetime.fromisoformat(get(c, bid)["deadline"])
        CLOCK.set(deadline + datetime.timedelta(seconds=m.ABSENCE_LAG_SECONDS))
        adjudicate(c, bid, {search_url(): search_json(0)}, model={"outcome": N})
        b = get(c, bid)
        view = dict(b, absence_ready=False)
        self.assertFalse(m._assess(b["evidence_content"], view)["non_delivery_supported"])
        view["absence_ready"] = True
        self.assertTrue(m._assess(b["evidence_content"], view)["non_delivery_supported"])


class TestCopycatCannotHoldAPullRequestHostage(unittest.TestCase):
    """The attacker posts a copy of a real bounty (same repo, issue and
    login) with their own wallets, then settles it on the victim's pull
    request first."""

    ATTACKER = "0x" + "44" * 20
    ATTACKER_2 = "0x" + "55" * 20

    def setUp(self):
        self.c = make_contract()
        self.real = create_bounty(self.c)
        accept_bounty(self.c, self.real)
        CLOCK.advance(60)
        self.copy = create_bounty(self.c, party_a=self.ATTACKER, party_b=self.ATTACKER_2,
                                  deadline=BASE + datetime.timedelta(days=3))
        accept_bounty(self.c, self.copy, party_b=self.ATTACKER_2)
        self.pages = {pr_url(7): pr_json(7, created_at=gh_ts(BASE_EPOCH + 3600))}

    def lock(self, bid, submitter):
        set_caller(submitter)
        self.c.submit_evidence(bid, [pr_url(7)])

    def rule(self, bid, parties):
        for who in parties:
            self.lock(bid, who)
        pass_deadline(self.c, bid)
        return adjudicate(self.c, bid, self.pages, model=None)

    def test_the_copy_claims_first_but_the_earlier_real_bounty_takes_it_back(self):
        self.rule(self.copy, (self.ATTACKER_2, self.ATTACKER))
        self.assertEqual(self.c.get_pr_claim(REPO, 7), self.copy)
        real = self.rule(self.real, (PARTY_B_ADDRESS, PARTY_A_ADDRESS))
        self.assertEqual(real["tier1_outcome"], D)
        self.assertEqual(self.c.get_pr_claim(REPO, 7), self.real)

    def test_the_displaced_copy_is_refunded_not_paid_on_the_stolen_pull_request(self):
        self.rule(self.copy, (self.ATTACKER_2, self.ATTACKER))
        self.rule(self.real, (PARTY_B_ADDRESS, PARTY_A_ADDRESS))
        pass_appeal_window(self.c, self.copy)
        set_caller(STRANGER_ADDRESS)
        self.c.settle_unappealed(self.copy)
        done = get(self.c, self.copy)
        self.assertEqual(done["final_outcome"], U)
        self.assertEqual(pending(self.c, self.ATTACKER), REWARD)
        self.assertEqual(pending(self.c, self.ATTACKER_2), BOND)
        self.assertEqual(self.c.get_pr_claim(REPO, 7), self.real)

    def test_the_real_contributor_is_paid(self):
        self.rule(self.copy, (self.ATTACKER_2, self.ATTACKER))
        self.rule(self.real, (PARTY_B_ADDRESS, PARTY_A_ADDRESS))
        pass_appeal_window(self.c, self.real)
        set_caller(STRANGER_ADDRESS)
        self.c.settle_unappealed(self.real)
        self.assertEqual(pending(self.c, PARTY_B_ADDRESS), REWARD + BOND)

    def test_a_later_bounty_cannot_displace_an_earlier_claim(self):
        self.rule(self.real, (PARTY_B_ADDRESS, PARTY_A_ADDRESS))
        later = self.rule(self.copy, (self.ATTACKER_2, self.ATTACKER))
        self.assertEqual(later["tier1_outcome"], U)
        self.assertEqual(self.c.get_pr_claim(REPO, 7), self.real)

    def test_a_settled_claim_is_never_displaced(self):
        self.rule(self.copy, (self.ATTACKER_2, self.ATTACKER))
        pass_appeal_window(self.c, self.copy)
        set_caller(STRANGER_ADDRESS)
        self.c.settle_unappealed(self.copy)
        real = self.rule(self.real, (PARTY_B_ADDRESS, PARTY_A_ADDRESS))
        self.assertEqual(real["tier1_outcome"], U)
        self.assertEqual(self.c.get_pr_claim(REPO, 7), self.copy)

    def test_equal_creation_times_are_ordered_by_the_creation_counter(self):
        c = make_contract()
        first = create_bounty(c)
        accept_bounty(c, first)
        second = create_bounty(c, party_a=self.ATTACKER, party_b=self.ATTACKER_2)
        accept_bounty(c, second, party_b=self.ATTACKER_2)
        set_caller(PARTY_B_ADDRESS)
        c.submit_evidence(first, [pr_url(7)])
        set_caller(PARTY_A_ADDRESS)
        c.submit_evidence(first, [pr_url(7)])
        set_caller(self.ATTACKER_2)
        c.submit_evidence(second, [pr_url(7)])
        set_caller(self.ATTACKER)
        c.submit_evidence(second, [pr_url(7)])
        pass_deadline(c, first)
        adjudicate(c, second, self.pages, model=None)
        earlier = adjudicate(c, first, self.pages, model=None)
        self.assertEqual(earlier["tier1_outcome"], D)
        self.assertEqual(c.get_pr_claim(REPO, 7), first)


class TestEvidenceRevision(unittest.TestCase):
    def setUp(self):
        self.c = make_contract()
        self.bid = active_bounty(self.c)

    def test_a_typo_free_list_can_replace_an_earlier_one_before_the_lock(self):
        set_caller(PARTY_B_ADDRESS)
        self.c.submit_evidence(self.bid, [pr_url(6)])
        self.c.submit_evidence(self.bid, [pr_url(7)])
        self.assertEqual(get(self.c, self.bid)["evidence_submissions"][PARTY_B_ADDRESS.lower()], [pr_url(7)])
        self.assertEqual(get(self.c, self.bid)["evidence_revisions"][PARTY_B_ADDRESS.lower()], 2)

    def test_no_revision_after_the_snapshot_is_locked(self):
        set_caller(PARTY_B_ADDRESS)
        self.c.submit_evidence(self.bid, [pr_url(7)])
        set_caller(PARTY_A_ADDRESS)
        self.c.submit_evidence(self.bid, [pr_url(7)])
        set_caller(PARTY_B_ADDRESS)
        expect_user_error(self, self.c.submit_evidence, self.bid, [pr_url(8)])

    def test_a_rejected_revision_keeps_the_previous_list(self):
        set_caller(PARTY_B_ADDRESS)
        self.c.submit_evidence(self.bid, [pr_url(7)])
        expect_user_error(self, self.c.submit_evidence, self.bid, ["https://evil.example/x"])
        self.assertEqual(get(self.c, self.bid)["evidence_submissions"][PARTY_B_ADDRESS.lower()], [pr_url(7)])


if __name__ == "__main__":
    unittest.main()
