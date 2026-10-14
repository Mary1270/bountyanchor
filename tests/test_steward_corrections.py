"""Regression tests for the steward review: unavailable or negative inference
must never authorise full payment, and unverified or trivial work must never
earn a partial reward automatically, while maintainer silence and maintainer
actions still never become contributor breach."""
import datetime
import json
import unittest
from unittest.mock import patch

from _bootstrap import (
    m, gl, CLOCK, REPO, REWARD, BOND, PARTY_A_ADDRESS, PARTY_B_ADDRESS, STRANGER_ADDRESS,
    make_contract, set_caller, locked_bounty, ruled_bounty, get, pending, pass_deadline, pass_appeal_window,
    adjudicate, pr_json, open_pr_json, pr_url, search_url, search_json, gh_ts, web_for, anchors, assess,
    register_jurors, MODEL_DELIVERED, MODEL_PARTIAL, MODEL_UNDETERMINED, DEADLINE_EPOCH, DAY,
)
from test_jury import jury_case, run_vote

D, P, N, U = m.OUT_DELIVERED, m.OUT_PARTIAL, m.OUT_NOT_DELIVERED, m.OUT_UNDETERMINED
BROKEN_MODELS = ({}, {"outcome": "gibberish"}, {"outcome": None}, "not json", RuntimeError("model down"), {"reasoning": "x"})


def settle(c, bid):
    pass_appeal_window(c, bid)
    set_caller(STRANGER_ADDRESS)
    c.settle_unappealed(bid)
    return get(c, bid)


class TestUnavailableInferenceCannotAuthoriseFullDelivery(unittest.TestCase):
    def setUp(self):
        self.c = make_contract()

    def locked(self, pages):
        bid = locked_bounty(self.c, urls=list(pages), both=True)
        pass_deadline(self.c, bid)
        return bid

    def test_a_structurally_valid_merged_pull_request_is_not_paid_when_the_model_fails(self):
        pages = {pr_url(7): pr_json(7)}
        for mdl in BROKEN_MODELS:
            with self.subTest(mdl=mdl):
                self.setUp()
                bid = self.locked(pages)
                with self.assertRaises(gl.vm.UserError):
                    adjudicate(self.c, bid, pages, model=mdl)
                b = get(self.c, bid)
                self.assertEqual((b["status"], b.get("tier1_outcome")), ("evidence_locked", None))
                self.assertEqual(pending(self.c, PARTY_B_ADDRESS), 0)
                self.assertEqual(self.c.get_pr_claim(REPO, 7), "")

    def test_after_the_model_window_the_same_case_is_refunded_never_paid(self):
        pages = {pr_url(7): pr_json(7)}
        bid = self.locked(pages)
        deadline = datetime.datetime.fromisoformat(get(self.c, bid)["deadline"])
        CLOCK.set(deadline + datetime.timedelta(seconds=m.MODEL_WINDOW_SECONDS + 1))
        prompts = []
        b = adjudicate(self.c, bid, pages, model=None, prompts=prompts)
        self.assertEqual((b["tier1_outcome"], prompts), (U, []))
        self.assertEqual(b["claimed_pr_key"], "")
        done = settle(self.c, bid)
        self.assertEqual(done["final_outcome"], U)
        self.assertEqual((pending(self.c, PARTY_A_ADDRESS), pending(self.c, PARTY_B_ADDRESS)), (REWARD, BOND))

    def test_a_model_that_is_not_affirmative_never_yields_delivery(self):
        pages = {pr_url(7): pr_json(7)}
        for mdl, expected in ((MODEL_UNDETERMINED, U), ({"outcome": N}, U), (MODEL_PARTIAL, P)):
            with self.subTest(mdl=mdl):
                self.setUp()
                bid = ruled_bounty(self.c, pages=pages, model=mdl)
                self.assertEqual(get(self.c, bid)["tier1_outcome"], expected)

    def test_only_an_affirmative_model_answer_pays_in_full(self):
        bid = ruled_bounty(self.c, pages={pr_url(7): pr_json(7)}, model=MODEL_DELIVERED)
        done = settle(self.c, bid)
        self.assertEqual((done["final_outcome"], pending(self.c, PARTY_B_ADDRESS)), (D, REWARD + BOND))

    def test_a_jury_can_still_award_a_proven_delivery_after_a_refund(self):
        c = make_contract()
        bid = jury_case(c, tier1=U, pages={pr_url(7): pr_json(7)}, model=MODEL_UNDETERMINED)
        self.assertEqual(json.loads(c.get_jury_options(bid)), sorted([D, P, U]))
        self.assertEqual(run_vote(c, bid, [D] * 5)["final_outcome"], D)

    def test_validators_must_agree_on_whether_the_model_answered(self):
        b = anchors()
        ctx = {"bounty": b, "urls": [pr_url(7)], "before_deadline": False}
        with patch.object(gl.nondet.web, "render", side_effect=web_for({pr_url(7): pr_json(7)})):
            with patch.object(gl.nondet, "exec_prompt", return_value=MODEL_DELIVERED):
                leader = json.loads(json.dumps(m._tier1_compute(ctx)))
            with patch.object(gl.nondet, "exec_prompt", return_value={}):
                self.assertFalse(m._tier1_validator(gl.vm.Return(leader), ctx))
            leader["model_answered"] = False
            with patch.object(gl.nondet, "exec_prompt", return_value=MODEL_DELIVERED):
                self.assertFalse(m._tier1_validator(gl.vm.Return(leader), ctx))

    def test_a_late_merge_and_an_unlinked_merge_never_reach_delivery(self):
        for data in (pr_json(7, merged_at=gh_ts(DEADLINE_EPOCH + 3600)), pr_json(7, body="no closing link")):
            with self.subTest(merged_at=data["merged_at"]):
                self.setUp()
                bid = ruled_bounty(self.c, pages={pr_url(7): data}, model=MODEL_DELIVERED)
                self.assertNotEqual(get(self.c, bid)["tier1_outcome"], D)


class TestUnverifiedWorkCannotEarnAPartialReward(unittest.TestCase):
    def setUp(self):
        self.c = make_contract()

    def test_an_open_linked_pull_request_needs_an_affirmative_merit_check(self):
        pages = {pr_url(7): open_pr_json(7)}
        for mdl in (MODEL_UNDETERMINED, {"outcome": N}, MODEL_DELIVERED):
            with self.subTest(mdl=mdl):
                self.setUp()
                bid = ruled_bounty(self.c, pages=pages, model=mdl)
                b = get(self.c, bid)
                self.assertEqual((b["tier1_outcome"], b["claimed_pr_key"]), (U, ""))
                done = settle(self.c, bid)
                self.assertEqual((pending(self.c, PARTY_A_ADDRESS), pending(self.c, PARTY_B_ADDRESS)), (REWARD, BOND))
                self.assertEqual(done["final_outcome"], U)

    def test_an_affirmative_merit_check_still_gives_the_partial_split(self):
        bid = ruled_bounty(self.c, pages={pr_url(7): open_pr_json(7)}, model=MODEL_PARTIAL)
        b = get(self.c, bid)
        self.assertEqual((b["tier1_outcome"], b["claimed_pr_key"]), (P, f"{REPO}#7"))
        settle(self.c, bid)
        self.assertEqual(pending(self.c, PARTY_B_ADDRESS), BOND + REWARD // 2)
        self.assertEqual(pending(self.c, PARTY_A_ADDRESS), REWARD - REWARD // 2)

    def test_the_merit_prompt_shows_the_pending_pull_request_and_forbids_other_answers(self):
        prompts = []
        c = make_contract()
        bid = locked_bounty(c, urls=[pr_url(7)], both=True)
        pass_deadline(c, bid)
        adjudicate(c, bid, {pr_url(7): open_pr_json(7)}, model=MODEL_PARTIAL, prompts=prompts)
        tail = prompts[0].split("Respond ONLY")[1]
        self.assertIn("PENDING_PRS: [7]", prompts[0])
        self.assertIn("PARTIALLY_DELIVERED", tail)
        self.assertIn("UNDETERMINED", tail)
        self.assertNotIn("BOUNTY_DELIVERED", tail)
        self.assertNotIn("NOT_DELIVERED", tail)

    def test_an_open_pull_request_with_no_model_answer_records_nothing(self):
        for mdl in BROKEN_MODELS:
            with self.subTest(mdl=mdl):
                self.setUp()
                bid = locked_bounty(self.c, urls=[pr_url(7)], both=True)
                pass_deadline(self.c, bid)
                with self.assertRaises(gl.vm.UserError):
                    adjudicate(self.c, bid, {pr_url(7): open_pr_json(7)}, model=mdl)
                self.assertEqual(get(self.c, bid)["status"], "evidence_locked")

    def test_after_the_model_window_an_open_pull_request_is_refunded_not_paid(self):
        pages = {pr_url(7): open_pr_json(7)}
        bid = locked_bounty(self.c, urls=list(pages), both=True)
        deadline = datetime.datetime.fromisoformat(get(self.c, bid)["deadline"])
        CLOCK.set(deadline + datetime.timedelta(seconds=m.MODEL_WINDOW_SECONDS + 1))
        b = adjudicate(self.c, bid, pages, model=None)
        self.assertEqual(b["tier1_outcome"], U)

    def test_empty_or_unmeasurable_pull_requests_are_never_pending(self):
        cases = (
            dict(changed_files=0, additions=0, deletions=0),
            dict(changed_files=1, additions=0, deletions=0),
            dict(changed_files=0, additions=5, deletions=0),
            dict(changed_files=None, additions=None, deletions=None),
            dict(additions=-1, deletions="x"),
        )
        for over in cases:
            with self.subTest(over=over):
                self.setUp()
                data = open_pr_json(7, **over)
                a = assess({pr_url(7): data})
                self.assertEqual((a["pending_prs"], a["ambiguous_prs"]), ([], [7]))
                self.assertFalse(a["reports"][0]["substantive"])
                prompts = []
                bid = locked_bounty(self.c, urls=[pr_url(7)], both=True)
                pass_deadline(self.c, bid)
                b = adjudicate(self.c, bid, {pr_url(7): data}, model=None, prompts=prompts)
                self.assertEqual((b["tier1_outcome"], prompts, b["claimed_pr_key"]), (U, [], ""))

    def test_a_one_line_change_is_still_measurable_and_goes_to_the_merit_check(self):
        a = assess({pr_url(7): open_pr_json(7, changed_files=1, additions=1, deletions=0)})
        self.assertEqual(a["pending_prs"], [7])
        self.assertTrue(a["reports"][0]["substantive"])

    def test_trivial_work_that_the_model_rejects_does_not_pay(self):
        data = open_pr_json(7, title="Fix typo", body="Fixes #42", changed_files=1, additions=1, deletions=1)
        bid = ruled_bounty(self.c, pages={pr_url(7): data}, model={"outcome": U, "reasoning": "cosmetic only"})
        self.assertEqual(get(self.c, bid)["tier1_outcome"], U)

    def test_a_late_merge_is_judged_on_merit_too(self):
        data = pr_json(7, merged_at=gh_ts(DEADLINE_EPOCH + 3600))
        self.assertEqual(get(self.c, ruled_bounty(self.c, pages={pr_url(7): data}, model=MODEL_UNDETERMINED))["tier1_outcome"], U)
        c = make_contract()
        self.assertEqual(get(c, ruled_bounty(c, pages={pr_url(7): data}, model=MODEL_PARTIAL))["tier1_outcome"], P)


class TestSafeguardsAgainstMaintainerManipulationAndSilence(unittest.TestCase):
    def test_silence_is_never_breach_whatever_the_model_says(self):
        pages = {pr_url(7): open_pr_json(7), search_url(): search_json(0)}
        for mdl in (MODEL_PARTIAL, {"outcome": N}, MODEL_UNDETERMINED, {}):
            with self.subTest(mdl=mdl):
                c = make_contract()
                bid = locked_bounty(c, urls=list(pages), both=True)
                pass_deadline(c, bid)
                try:
                    adjudicate(c, bid, pages, model=mdl)
                except gl.vm.UserError:
                    continue
                self.assertNotEqual(get(c, bid)["tier1_outcome"], N)

    def test_maintainer_actions_never_become_breach_and_never_pay_the_sponsor_automatically(self):
        closed = dict(merged=False, merged_at=None, state="closed")
        cases = (pr_json(7, **closed), open_pr_json(7, draft=True),
                 open_pr_json(7, base={"ref": "elsewhere", "repo": {"full_name": REPO}}))
        for data in cases:
            with self.subTest(state=data["state"], draft=data["draft"]):
                c = make_contract()
                bid = ruled_bounty(c, pages={pr_url(7): data}, model={"outcome": N})
                self.assertEqual(get(c, bid)["tier1_outcome"], U)

    def test_a_late_pull_request_is_still_breach_only_with_the_model(self):
        data = pr_json(7, created_at=gh_ts(DEADLINE_EPOCH + 60), merged=False, merged_at=None, state="closed")
        c = make_contract()
        self.assertEqual(get(c, ruled_bounty(c, pages={pr_url(7): data}, model={"outcome": N}))["tier1_outcome"], N)
        c = make_contract()
        self.assertEqual(get(c, ruled_bounty(c, pages={pr_url(7): data}, model=MODEL_UNDETERMINED))["tier1_outcome"], U)


class TestTheJuryBoundsForPendingWork(unittest.TestCase):
    def test_a_jury_may_confirm_or_refund_pending_work_but_never_award_breach_or_delivery(self):
        c = make_contract()
        bid = ruled_bounty(c, pages={pr_url(7): open_pr_json(7)}, model=MODEL_PARTIAL)
        self.assertEqual(json.loads(c.get_jury_options(bid)), sorted([P, U]))
        for bad in (N, D):
            with self.subTest(bad=bad):
                c = make_contract()
                bid = jury_case(c, tier1=P, pages={pr_url(7): open_pr_json(7)}, model=MODEL_PARTIAL)
                b = run_vote(c, bid, [bad] * 5)
                self.assertNotIn(b["final_outcome"], (N, D))
                self.assertFalse(b["jury"]["verification_passed"])

    def test_a_jury_can_overturn_an_unjustified_partial_to_undetermined(self):
        c = make_contract()
        bid = jury_case(c, tier1=P, pages={pr_url(7): open_pr_json(7)}, model=MODEL_PARTIAL)
        b = run_vote(c, bid, [U] * 5)
        self.assertEqual(b["final_outcome"], U)
        self.assertEqual(c.get_pr_claim(REPO, 7), "")

    def test_a_jury_can_award_partial_after_a_refund_when_the_work_deserves_it(self):
        c = make_contract()
        bid = jury_case(c, tier1=U, pages={pr_url(7): open_pr_json(7)}, model=MODEL_UNDETERMINED)
        self.assertEqual(json.loads(c.get_jury_options(bid)), sorted([P, U]))
        self.assertEqual(run_vote(c, bid, [P] * 5)["final_outcome"], P)


class TestMoneyIsConserved(unittest.TestCase):
    def test_every_new_path_conserves_funds(self):
        scenarios = (
            ({pr_url(7): pr_json(7)}, MODEL_UNDETERMINED),
            ({pr_url(7): pr_json(7)}, MODEL_PARTIAL),
            ({pr_url(7): open_pr_json(7)}, MODEL_UNDETERMINED),
            ({pr_url(7): open_pr_json(7)}, MODEL_PARTIAL),
            ({pr_url(7): open_pr_json(7, changed_files=0, additions=0, deletions=0)}, None),
        )
        for pages, mdl in scenarios:
            with self.subTest(outcome=mdl):
                c = make_contract()
                bid = ruled_bounty(c, pages=pages, model=mdl)
                done = settle(c, bid)
                total = pending(c, PARTY_A_ADDRESS) + pending(c, PARTY_B_ADDRESS)
                self.assertEqual(total, REWARD + int(done["bond_amount"]))
                self.assertEqual(total, int(c.balance))


if __name__ == "__main__":
    unittest.main()
