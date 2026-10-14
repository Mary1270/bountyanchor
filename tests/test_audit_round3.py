"""Third audit round: attacks by a sponsor who also maintains the
repository, unrelated pull requests used as proof, a jury that could never
correct Tier 1, and juror incentives that favoured confirming Tier 1."""
import datetime
import json
import unittest

from _bootstrap import (
    late_pr_json,
    m, gl, CLOCK, DAY, BASE_EPOCH, DEADLINE_EPOCH, PARTY_A_ADDRESS, PARTY_B_ADDRESS, STRANGER_ADDRESS, REPO,
    REWARD, BOND, JUROR_ADDRESSES, make_contract, set_caller, call_payable, ruled_bounty, register_jurors, get,
    pending, pr_json, open_pr_json, pr_url, search_url, search_json, gh_ts, anchors, assess, expect_user_error,
    PaymentRejected,
)
from test_jury import jury_case, run_vote, selected, APPEAL_BOND

D, P, N, U = m.OUT_DELIVERED, m.OUT_PARTIAL, m.OUT_NOT_DELIVERED, m.OUT_UNDETERMINED
CLOSED_ON_TIME = dict(merged=False, merged_at=None, state="closed")


def tier1(pages, model):
    c = make_contract()
    return c, ruled_bounty(c, pages=pages, model=model)


class TestMaintainerActionsAreNotContributorBreach(unittest.TestCase):
    """A sponsor who maintains the repository can close, retarget or
    convert a contributor's pull request. None of those maintainer actions
    may hand the sponsor the contributor's bond automatically."""

    def test_a_good_pull_request_closed_unmerged_is_not_automatic_breach(self):
        c, bid = tier1({pr_url(7): pr_json(7, **CLOSED_ON_TIME)}, {"outcome": N})
        b = get(c, bid)
        self.assertEqual(b["tier1_outcome"], U)
        self.assertEqual(b["tier1_assessment"]["rejected_prs"], [7])

    def test_a_retargeted_pull_request_is_not_automatic_breach(self):
        c, bid = tier1({pr_url(7): open_pr_json(7, base={"ref": "dead-branch", "repo": {"full_name": REPO}})},
                       {"outcome": N})
        self.assertEqual(get(c, bid)["tier1_outcome"], U)

    def test_a_pull_request_converted_to_draft_is_not_automatic_breach(self):
        c, bid = tier1({pr_url(7): open_pr_json(7, draft=True)}, {"outcome": N})
        self.assertEqual(get(c, bid)["tier1_outcome"], U)

    def test_a_pull_request_opened_after_the_deadline_is_still_breach(self):
        late = pr_json(7, created_at=gh_ts(DEADLINE_EPOCH + 60), **CLOSED_ON_TIME)
        c, bid = tier1({pr_url(7): late}, {"outcome": N})
        self.assertEqual(get(c, bid)["tier1_outcome"], N)


class TestUnrelatedPullRequestsProveNothing(unittest.TestCase):
    def test_a_pull_request_from_before_the_bounty_does_not_support_breach(self):
        a = assess({pr_url(7): pr_json(7, created_at=gh_ts(BASE_EPOCH - 30 * DAY), **CLOSED_ON_TIME)})
        self.assertFalse(a["non_delivery_supported"])
        self.assertEqual(a["reports"][0]["verdict"], "unrelated")


class TestTheNoPullRequestSearchIsBoundedByTheDeadline(unittest.TestCase):
    """A pull request opened after the deadline must not erase the proof
    that none was opened in time."""

    def test_the_query_has_an_upper_bound_at_the_deadline(self):
        q = m._search_query(anchors())
        self.assertIn("created:2026-03-01T12:00:00+00:00..2026-03-04T12:00:00+00:00", q)

    def test_an_unbounded_query_is_not_accepted_as_evidence(self):
        unbounded = "https://api.github.com/search/issues?q=repo:acme/widgets%20is:pr%20author:octodev%20created:%3E%3D2026-03-01"
        self.assertIsNone(m._evidence_item(unbounded, anchors()))


class TestTheJuryCanCorrectTierOneWithinCodeBounds(unittest.TestCase):
    def test_a_merged_but_unlinked_pull_request_can_be_awarded_partial(self):
        c = make_contract()
        pages = {pr_url(7): pr_json(7, body="Implements sorting, see the issue")}
        bid = jury_case(c, tier1=U, pages=pages, model=None)
        b = run_vote(c, bid, [P] * 5)
        self.assertEqual((b["tier1_outcome"], b["final_outcome"]), (U, P))
        self.assertTrue(b["jury"]["verification_passed"])

    def test_a_rejected_pull_request_can_be_ruled_breach_by_the_jury(self):
        c = make_contract()
        bid = jury_case(c, tier1=U, pages={pr_url(7): pr_json(7, **CLOSED_ON_TIME)}, model={"outcome": N})
        b = run_vote(c, bid, [N] * 5)
        self.assertEqual(b["final_outcome"], N)

    def test_the_jury_still_cannot_award_delivery_without_a_delivered_pull_request(self):
        c = make_contract()
        bid = jury_case(c, tier1=U, pages={pr_url(7): pr_json(7, **CLOSED_ON_TIME)}, model={"outcome": N})
        b = run_vote(c, bid, [D] * 5)
        self.assertEqual(b["final_outcome"], U)
        self.assertFalse(b["jury"]["verification_passed"])

    def test_the_jury_cannot_turn_maintainer_silence_into_breach(self):
        c = make_contract()
        register_jurors(c, 6)
        bid = ruled_bounty(c, pages={pr_url(7): open_pr_json(7)}, model={"outcome": P})
        self.assertEqual(get(c, bid)["tier1_outcome"], P)
        self.assertEqual(json.loads(c.get_jury_options(bid)), sorted([P, U]))

    def test_the_options_view_lists_what_a_jury_may_decide(self):
        c = make_contract()
        bid = ruled_bounty(c, pages={pr_url(7): pr_json(7, **CLOSED_ON_TIME)}, model={"outcome": N})
        self.assertEqual(json.loads(c.get_jury_options(bid)), sorted([N, P, U]))


class TestJurorPayDoesNotDependOnWhichWayTheyVote(unittest.TestCase):
    def juror_income(self, tier1_outcome, votes, model):
        c = make_contract()
        pages = {pr_url(7): pr_json(7, **CLOSED_ON_TIME)}
        bid = jury_case(c, tier1=tier1_outcome, pages=pages, model=model)
        run_vote(c, bid, votes)
        return c, bid, sum(pending(c, a) for a in selected(c, bid))

    def test_confirming_and_overturning_pay_jurors_the_same(self):
        _, _, confirm = self.juror_income(U, [U] * 5, {"outcome": N})
        _, _, overturn = self.juror_income(U, [N] * 5, {"outcome": N})
        self.assertEqual(confirm, overturn)
        self.assertGreater(confirm, 0)

    def test_a_failed_appeal_compensates_the_other_party(self):
        c, bid, _ = self.juror_income(U, [U] * 5, {"outcome": N})
        fee = APPEAL_BOND * m.BountyAnchor.JURY_FEE_BPS // 10000
        self.assertEqual(pending(c, PARTY_A_ADDRESS), REWARD + (APPEAL_BOND - fee))

    def test_a_successful_appeal_refunds_the_appellant_minus_the_jury_fee(self):
        c, bid, _ = self.juror_income(U, [N] * 5, {"outcome": N})
        fee = APPEAL_BOND * m.BountyAnchor.JURY_FEE_BPS // 10000
        self.assertEqual(get(c, bid)["final_outcome"], N)
        self.assertEqual(pending(c, PARTY_B_ADDRESS), APPEAL_BOND - fee)

    def test_money_is_conserved_through_both_fee_paths(self):
        for votes in ([U] * 5, [N] * 5, [N, N, N, U, None]):
            with self.subTest(votes=votes):
                c, bid, _ = self.juror_income(U, votes, {"outcome": N})
                owed = sum(int(v) for v in c.pending_withdrawals.values())
                stakes = sum(int(json.loads(c.jurors[k])["stake"]) for k in c.jurors.keys())
                self.assertEqual(owed + stakes, int(c.balance))


class TestInputHygiene(unittest.TestCase):
    def test_a_non_numeric_unstake_amount_is_a_clean_error(self):
        c = make_contract()
        set_caller(JUROR_ADDRESSES[0])
        call_payable(c, "register_juror", 100)
        for bad in ("abc", "", "1.5", None):
            with self.subTest(bad=bad):
                expect_user_error(self, c.unstake_juror, bad)


if __name__ == "__main__":
    unittest.main()


class TestCodeOnlyRulingAfterTheModelWindow(unittest.TestCase):
    """If validators keep disagreeing on a model answer, the case must not
    stay stuck until a refund: after the model window a code-only ruling is
    possible."""

    def locked(self, pages):
        from _bootstrap import locked_bounty
        c = make_contract()
        bid = locked_bounty(c, urls=list(pages), both=True)
        deadline = datetime.datetime.fromisoformat(get(c, bid)["deadline"])
        return c, bid, deadline

    def test_inside_the_window_the_model_is_consulted(self):
        from _bootstrap import adjudicate
        pages = {pr_url(7): pr_json(7)}
        c, bid, deadline = self.locked(pages)
        CLOCK.set(deadline + datetime.timedelta(seconds=m.MODEL_WINDOW_SECONDS))
        prompts = []
        b = adjudicate(c, bid, pages, model={"outcome": P}, prompts=prompts)
        self.assertEqual(b["tier1_outcome"], P)
        self.assertTrue(prompts)

    def test_after_the_window_a_proven_delivery_is_refunded_not_paid_without_the_model(self):
        from _bootstrap import adjudicate
        pages = {pr_url(7): pr_json(7)}
        c, bid, deadline = self.locked(pages)
        CLOCK.set(deadline + datetime.timedelta(seconds=m.MODEL_WINDOW_SECONDS + 1))
        prompts = []
        b = adjudicate(c, bid, pages, model=None, prompts=prompts)
        self.assertEqual(b["tier1_outcome"], U)
        self.assertEqual(prompts, [])
        self.assertIn("no merit check", b["tier1_reasoning"])
        self.assertEqual(json.loads(c.get_jury_options(bid)), sorted([D, P, U]))

    def test_after_the_window_breach_is_impossible_and_the_case_still_closes(self):
        from _bootstrap import adjudicate, late_pr_json
        pages = {pr_url(7): late_pr_json(7)}
        c, bid, deadline = self.locked(pages)
        CLOCK.set(deadline + datetime.timedelta(seconds=m.MODEL_WINDOW_SECONDS + 1))
        b = adjudicate(c, bid, pages, model=None)
        self.assertEqual(b["tier1_outcome"], U)
        self.assertEqual(json.loads(c.get_jury_options(bid)), sorted([N, U]))

    def test_the_window_ends_before_the_refund_timeout(self):
        self.assertLess(m.MODEL_WINDOW_SECONDS, m.BountyAnchor.RESOLUTION_TIMEOUT_SECONDS)
