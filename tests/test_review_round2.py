"""Second review round: early adjudication must not close a case, and claim
priority must not depend on one-second timestamps."""
import datetime
import itertools
import json
import unittest

from _bootstrap import (
    late_pr_json,
    m, gl, CLOCK, DAY, BASE, BASE_EPOCH, PARTY_A_ADDRESS, PARTY_B_ADDRESS, STRANGER_ADDRESS, REPO, REWARD, BOND,
    make_contract, set_caller, call_payable, create_bounty, accept_bounty, locked_bounty, active_bounty, get, pending,
    pass_deadline, pass_appeal_window, adjudicate, pr_json, open_pr_json, search_json, pr_url, search_url,
    expect_user_error, JUROR_ADDRESSES, register_jurors,
)

D, P, N, U = m.OUT_DELIVERED, m.OUT_PARTIAL, m.OUT_NOT_DELIVERED, m.OUT_UNDETERMINED
LAG = m.ABSENCE_LAG_SECONDS


def snapshot(c):
    return {
        "balance": int(c.balance),
        "pending": dict(c.pending_withdrawals),
        "claims": dict(c.pr_claims),
        "settled": int(c.settled_count),
    }


def rule_expecting_revert(test, c, bid, pages, model=None):
    before = snapshot(c)
    record_before = c.bounties[bid]
    with test.assertRaises(gl.vm.UserError):
        adjudicate(c, bid, pages, model=model)
    test.assertEqual(snapshot(c), before)
    test.assertEqual(c.bounties[bid], record_before)
    return json.loads(record_before)


class TestEarlyAdjudicationKeepsTheCaseOpen(unittest.TestCase):
    def setUp(self):
        self.c = make_contract()
        self.bid = locked_bounty(self.c, urls=[search_url()], both=True)
        pass_deadline(self.c, self.bid)
        self.deadline = datetime.datetime.fromisoformat(get(self.c, self.bid)["deadline"])

    def test_valid_empty_search_before_the_lag_is_refused_and_nothing_changes(self):
        b = rule_expecting_revert(self, self.c, self.bid, {search_url(): search_json(0)})
        self.assertEqual(b["status"], "evidence_locked")
        self.assertNotIn("appeal_deadline", b)
        self.assertIsNone(b.get("tier1_outcome"))
        self.assertEqual(pending(self.c, PARTY_A_ADDRESS) + pending(self.c, PARTY_B_ADDRESS), 0)

    def test_the_same_case_can_be_ruled_after_the_lag(self):
        rule_expecting_revert(self, self.c, self.bid, {search_url(): search_json(0)})
        CLOCK.set(self.deadline + datetime.timedelta(seconds=LAG))
        b = adjudicate(self.c, self.bid, {search_url(): search_json(0)}, model={"outcome": N})
        self.assertEqual((b["status"], b["tier1_outcome"]), ("ruled", N))

    def test_repeated_early_attempts_never_accumulate_state(self):
        for _ in range(3):
            rule_expecting_revert(self, self.c, self.bid, {search_url(): search_json(0)})
            CLOCK.advance(3600)
        self.assertEqual(get(self.c, self.bid)["status"], "evidence_locked")

    def test_no_appeal_window_starts_and_nothing_can_be_settled_early(self):
        rule_expecting_revert(self, self.c, self.bid, {search_url(): search_json(0)})
        set_caller(STRANGER_ADDRESS)
        expect_user_error(self, self.c.settle_unappealed, self.bid)

    def test_the_recovery_path_still_refunds_a_case_nobody_can_rule(self):
        rule_expecting_revert(self, self.c, self.bid, {search_url(): search_json(0)})
        CLOCK.set(self.deadline + datetime.timedelta(days=7, seconds=1))
        set_caller(STRANGER_ADDRESS)
        self.c.expire_unruled(self.bid)
        self.assertEqual(get(self.c, self.bid)["final_outcome"], U)
        self.assertEqual(pending(self.c, PARTY_A_ADDRESS), REWARD)
        self.assertEqual(pending(self.c, PARTY_B_ADDRESS), BOND)

    def test_a_jury_over_a_late_ruling_verifies_the_same_way(self):
        c = make_contract()
        register_jurors(c, 6)
        bid = locked_bounty(c, urls=[search_url()], both=True)
        deadline = datetime.datetime.fromisoformat(get(c, bid)["deadline"])
        CLOCK.set(deadline + datetime.timedelta(seconds=LAG))
        adjudicate(c, bid, {search_url(): search_json(0)}, model={"outcome": N})
        record = get(c, bid)
        frozen = record["evidence_content"]
        ready = dict(record, absence_ready=True)
        self.assertTrue(m._assess(frozen, ready)["non_delivery_supported"])
        self.assertFalse(m._assess(frozen, dict(record, absence_ready=False))["non_delivery_supported"])


class TestSearchResponseKinds(unittest.TestCase):
    """Fetch error, timeout, rate limit, bad JSON and an incomplete search
    are all different from a valid empty search, and none of them is proof
    of non-delivery."""

    RATE_LIMIT = json.dumps({"message": "API rate limit exceeded", "documentation_url": "https://docs.github.com"})

    def case(self, page, late=True, model=None):
        c = make_contract()
        bid = locked_bounty(c, urls=[search_url()], both=True)
        deadline = datetime.datetime.fromisoformat(get(c, bid)["deadline"])
        CLOCK.set(deadline + datetime.timedelta(seconds=LAG if late else 5))
        return c, bid

    def assess_of(self, page):
        from _bootstrap import assess
        return assess({search_url(): page})

    def test_a_valid_empty_search_is_absence(self):
        a = self.assess_of(search_json(0))
        self.assertTrue(a["absence_proven"])
        self.assertEqual(a["unreadable"], 0)

    def test_unreadable_responses_are_not_absence(self):
        for label, page in (
            ("rate limit", self.RATE_LIMIT), ("invalid json", "<html>nope</html>"), ("empty", ""),
            ("wrong shape", json.dumps({"total_count": "0", "incomplete_results": False, "items": []})),
            ("missing items", json.dumps({"total_count": 0, "incomplete_results": False})),
            ("incomplete", search_json(0, incomplete=True)),
        ):
            with self.subTest(label):
                a = self.assess_of(page)
                self.assertFalse(a["absence_proven"])
                self.assertFalse(a["non_delivery_supported"])
                self.assertEqual(a["unreadable"], 1)

    def test_a_search_with_results_is_conclusive_but_not_absence(self):
        a = self.assess_of(search_json(3))
        self.assertEqual((a["absence_proven"], a["unreadable"]), (False, 0))

    def test_a_fetch_exception_is_unreadable(self):
        from unittest.mock import patch
        c, bid = self.case(None)
        set_caller(STRANGER_ADDRESS)
        with patch.object(gl.nondet.web, "render", side_effect=TimeoutError("timeout")):
            with self.assertRaises(gl.vm.UserError):
                c.adjudicate(bid)
        self.assertEqual(get(c, bid)["status"], "evidence_locked")

    def test_unreadable_responses_leave_the_case_open_even_after_the_lag(self):
        for label, page in (("rate limit", self.RATE_LIMIT), ("invalid", "xx"), ("incomplete", search_json(0, True)),
                            ("missing", None)):
            with self.subTest(label):
                c, bid = self.case(page)
                rule_expecting_revert(self, c, bid, {search_url(): page})
                self.assertEqual(get(c, bid)["status"], "evidence_locked")

    def test_a_retry_with_a_clean_answer_then_succeeds(self):
        c, bid = self.case(None)
        rule_expecting_revert(self, c, bid, {search_url(): self.RATE_LIMIT})
        b = adjudicate(c, bid, {search_url(): search_json(0)}, model={"outcome": N})
        self.assertEqual(b["tier1_outcome"], N)

    def test_the_model_is_never_consulted_for_unreadable_evidence(self):
        c, bid = self.case(None)
        prompts = []
        with self.assertRaises(gl.vm.UserError):
            adjudicate(c, bid, {search_url(): self.RATE_LIMIT}, model=None, prompts=prompts)
        self.assertEqual(prompts, [])

    def test_a_late_pull_request_needs_no_wait_and_no_search(self):
        c = make_contract()
        pages = {pr_url(7): late_pr_json(7)}
        bid = locked_bounty(c, urls=list(pages), both=True)
        pass_deadline(c, bid)
        b = adjudicate(c, bid, pages, model={"outcome": N})
        self.assertEqual(b["tier1_outcome"], N)

    def test_a_late_pull_request_beside_an_early_empty_search_decides_on_the_pull_request(self):
        c = make_contract()
        pages = {pr_url(7): late_pr_json(7), search_url(): search_json(0)}
        bid = locked_bounty(c, urls=list(pages), both=True)
        pass_deadline(c, bid)
        b = adjudicate(c, bid, pages, model={"outcome": N})
        self.assertEqual(b["tier1_outcome"], N)

    def test_one_dead_link_beside_a_proven_delivery_does_not_block_it(self):
        c = make_contract()
        pages = {pr_url(7): pr_json(7), pr_url(8): None}
        bid = locked_bounty(c, urls=list(pages), both=True)
        pass_deadline(c, bid)
        b = adjudicate(c, bid, pages, model={"outcome": D})
        self.assertEqual(b["tier1_outcome"], D)


class ClaimWorld:
    """Several bounties over the same pull request, created in one clock
    second, each with its own two wallets."""

    def __init__(self, count):
        self.c = make_contract()
        self.ids = []
        self.parties = []
        for i in range(count):
            a = "0x" + format(0xB0 + i, "02x") * 20
            b = "0x" + format(0xC0 + i, "02x") * 20
            self.parties.append((a, b))
            self.ids.append(create_bounty(self.c, party_a=a, party_b=b))
        for bid, (a, b) in zip(self.ids, self.parties):
            accept_bounty(self.c, bid, party_b=b)
        self.pages = {pr_url(7): pr_json(7)}
        for bid, (a, b) in zip(self.ids, self.parties):
            set_caller(b)
            self.c.submit_evidence(bid, [pr_url(7)])
            set_caller(a)
            self.c.submit_evidence(bid, [pr_url(7)])
        pass_deadline(self.c, self.ids[0])
        self.deposited = count * (REWARD + BOND)

    def rule(self, index):
        return adjudicate(self.c, self.ids[index], self.pages, model=None)

    def settle_all(self):
        for bid in self.ids:
            if get(self.c, bid)["status"] == "ruled":
                pass_appeal_window(self.c, bid)
                set_caller(STRANGER_ADDRESS)
                self.c.settle_unappealed(bid)

    def owed(self):
        return sum(int(v) for v in self.c.pending_withdrawals.values())

    def winners(self):
        return [bid for bid in self.ids if get(self.c, bid)["final_outcome"] in (D, P)]


class TestClaimPriorityIsBySequenceNotTimestamp(unittest.TestCase):
    def test_bounties_created_in_the_same_second_have_a_strict_order(self):
        w = ClaimWorld(3)
        epochs = {get(w.c, bid)["created_epoch"] for bid in w.ids}
        self.assertEqual(len(epochs), 1)
        ranks = [m.BountyAnchor._rank(bid) for bid in w.ids]
        self.assertEqual(ranks, sorted(set(ranks)))

    def test_the_earlier_real_bounty_takes_the_claim_back_from_a_same_second_copy(self):
        w = ClaimWorld(2)
        w.rule(1)
        self.assertEqual(w.c.get_pr_claim(REPO, 7), w.ids[1])
        self.assertEqual(w.rule(0)["tier1_outcome"], D)
        self.assertEqual(w.c.get_pr_claim(REPO, 7), w.ids[0])

    def test_the_later_bounty_cannot_take_it_from_the_earlier_one(self):
        w = ClaimWorld(2)
        w.rule(0)
        self.assertEqual(w.rule(1)["tier1_outcome"], U)
        self.assertEqual(w.c.get_pr_claim(REPO, 7), w.ids[0])

    def test_a_claim_is_never_permanently_blocked_by_equal_timestamps(self):
        for order in itertools.permutations(range(3)):
            with self.subTest(order=order):
                w = ClaimWorld(3)
                for i in order:
                    w.rule(i)
                self.assertEqual(w.c.get_pr_claim(REPO, 7), w.ids[min(order)])

    def test_three_bounties_in_every_order_pay_one_reward_and_conserve_funds(self):
        for order in itertools.permutations(range(3)):
            with self.subTest(order=order):
                w = ClaimWorld(3)
                for i in order:
                    w.rule(i)
                w.settle_all()
                self.assertEqual(w.winners(), [w.ids[0]])
                self.assertEqual(w.owed(), w.deposited)
                self.assertEqual(w.owed(), int(w.c.balance))
                self.assertEqual(int(w.c.pending_withdrawals[w.parties[0][1].lower()]), REWARD + BOND)
                for loser in (1, 2):
                    a, b = w.parties[loser]
                    self.assertEqual(pending(w.c, a), REWARD)
                    self.assertEqual(pending(w.c, b), BOND)

    def test_a_pull_request_pays_at_most_one_reward_even_with_appeals_between(self):
        w = ClaimWorld(2)
        w.rule(1)
        w.rule(0)
        w.settle_all()
        paid = [bid for bid in w.ids if int(get(w.c, bid)["contributor_payout"]) > BOND]
        self.assertEqual(paid, [w.ids[0]])

    def test_a_settled_claim_is_final_and_no_payment_is_reversed(self):
        w = ClaimWorld(2)
        w.rule(1)
        pass_appeal_window(w.c, w.ids[1])
        set_caller(STRANGER_ADDRESS)
        w.c.settle_unappealed(w.ids[1])
        paid_before = pending(w.c, w.parties[1][1])
        self.assertEqual(w.rule(0)["tier1_outcome"], U)
        w.settle_all()
        self.assertEqual(pending(w.c, w.parties[1][1]), paid_before)
        self.assertEqual(w.owed(), w.deposited)

    def test_creation_arguments_cannot_change_the_order(self):
        c = make_contract()
        first = create_bounty(c, deadline=BASE + datetime.timedelta(days=30))
        second = create_bounty(c, deadline=BASE + datetime.timedelta(hours=2))
        self.assertLess(m.BountyAnchor._rank(first), m.BountyAnchor._rank(second))
        self.assertEqual(get(c, first)["created_epoch"], get(c, second)["created_epoch"])

    def test_a_cancelled_or_unknown_owner_never_blocks_a_claim(self):
        w = ClaimWorld(2)
        w.c.pr_claims[f"{REPO}#7"] = "bounty_999"
        self.assertEqual(w.rule(0)["tier1_outcome"], D)
        self.assertEqual(w.c.get_pr_claim(REPO, 7), w.ids[0])

    def test_money_conservation_holds_after_claim_takeover_with_a_jury(self):
        c = make_contract()
        register_jurors(c, 6)
        w = ClaimWorld.__new__(ClaimWorld)
        w.c = c
        w.ids, w.parties = [], []
        for i in range(2):
            a = "0x" + format(0xB0 + i, "02x") * 20
            b = "0x" + format(0xC0 + i, "02x") * 20
            w.parties.append((a, b))
            w.ids.append(create_bounty(c, party_a=a, party_b=b))
            accept_bounty(c, w.ids[-1], party_b=b)
        w.pages = {pr_url(7): pr_json(7)}
        for bid, (a, b) in zip(w.ids, w.parties):
            set_caller(b)
            c.submit_evidence(bid, [pr_url(7)])
            set_caller(a)
            c.submit_evidence(bid, [pr_url(7)])
        pass_deadline(c, w.ids[0])
        w.rule(1)
        w.rule(0)
        w.settle_all()
        self.assertEqual(w.owed(), 2 * (REWARD + BOND))


if __name__ == "__main__":
    unittest.main()
