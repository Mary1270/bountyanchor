"""Regression tests for problems found by stewards and live testing in
earlier GenLayer projects, checked against this contract."""
import ast
import json
import os
import unittest

from _bootstrap import (
    late_pr_json,
    m, gl, CLOCK, PARTY_A_ADDRESS, PARTY_B_ADDRESS, STRANGER_ADDRESS, JUROR_ADDRESSES, REWARD, BOND,
    make_contract, set_caller, call_payable, create_bounty, accept_bounty, ruled_bounty, register_jurors, get,
    pending, pr_json, pr_url, search_json, PaymentRejected,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = open(os.path.join(ROOT, "contract.py"), encoding="utf-8").read()
N = m.OUT_NOT_DELIVERED
CLOSED = {pr_url(7): late_pr_json(7)}


class TestRejectedPaymentsAreRefundedNotStranded(unittest.TestCase):
    """GEN attached to a payable call that reverts can stay in the contract
    with no record of the sender. Every payable method therefore refunds a
    rejected payment to the sender's withdrawable balance."""

    def setUp(self):
        self.c = make_contract()

    def assert_refunded(self, who, amount):
        self.assertEqual(pending(self.c, who), amount)
        set_caller(who)
        self.c.withdraw()
        self.assertEqual(gl.evm.transfers[-1], {"to": who, "value": amount})

    def test_create_with_a_bad_argument(self):
        with self.assertRaises(PaymentRejected):
            create_bounty(self.c, repo="not a repo")
        self.assertEqual(self.c.total_bounties(), 0)
        self.assert_refunded(PARTY_A_ADDRESS, REWARD)

    def test_accept_with_the_wrong_bond(self):
        bid = create_bounty(self.c)
        set_caller(PARTY_B_ADDRESS)
        with self.assertRaises(PaymentRejected):
            call_payable(self.c, "accept_bounty", BOND + 7, bid)
        self.assertEqual(get(self.c, bid)["status"], "posted")
        self.assert_refunded(PARTY_B_ADDRESS, BOND + 7)

    def test_accept_by_a_stranger(self):
        bid = create_bounty(self.c)
        set_caller(STRANGER_ADDRESS)
        with self.assertRaises(PaymentRejected):
            call_payable(self.c, "accept_bounty", BOND, bid)
        self.assert_refunded(STRANGER_ADDRESS, BOND)

    def test_accept_of_an_unknown_bounty(self):
        set_caller(PARTY_B_ADDRESS)
        with self.assertRaises(PaymentRejected):
            call_payable(self.c, "accept_bounty", BOND, "bounty_77")
        self.assert_refunded(PARTY_B_ADDRESS, BOND)

    def test_appeal_with_too_few_jurors(self):
        register_jurors(self.c, 3)
        bid = ruled_bounty(self.c, pages=CLOSED, model={"outcome": N})
        set_caller(PARTY_B_ADDRESS)
        with self.assertRaises(PaymentRejected):
            call_payable(self.c, "file_appeal", REWARD * 2000 // 10000, bid)
        self.assertEqual(get(self.c, bid)["status"], "ruled")
        for addr in JUROR_ADDRESSES[:3]:
            self.assertEqual(json.loads(self.c.get_juror(addr)).get("pool_holds", 0), 0)
        self.assertEqual(pending(self.c, PARTY_B_ADDRESS), REWARD * 2000 // 10000)

    def test_register_juror_below_the_minimum(self):
        from unittest.mock import patch
        with patch.object(m.BountyAnchor, "MIN_JUROR_STAKE", m.u256(100)):
            set_caller(JUROR_ADDRESSES[0])
            with self.assertRaises(PaymentRejected):
                call_payable(self.c, "register_juror", 99)
        self.assertEqual(json.loads(self.c.get_juror(JUROR_ADDRESSES[0]))["stake"], "0")
        self.assert_refunded(JUROR_ADDRESSES[0], 99)

    def test_without_gen_a_rejection_is_a_plain_revert(self):
        set_caller(PARTY_B_ADDRESS)
        with self.assertRaises(gl.vm.UserError) as ctx:
            call_payable(self.c, "accept_bounty", 0, "bounty_77")
        self.assertNotIsInstance(ctx.exception, PaymentRejected)
        self.assertEqual(pending(self.c, PARTY_B_ADDRESS), 0)

    def test_the_contract_balance_always_equals_escrow_plus_what_is_owed(self):
        create_bounty(self.c)
        for amount in (1, 2, 3):
            with self.assertRaises(PaymentRejected):
                create_bounty(self.c, reward=amount, repo="x")
        owed = sum(int(v) for v in self.c.pending_withdrawals.values())
        self.assertEqual(int(self.c.balance), REWARD + owed)

    def test_every_payable_method_goes_through_the_refund_wrapper(self):
        tree = ast.parse(SOURCE)
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "BountyAnchor")
        for fn in cls.body:
            if isinstance(fn, ast.FunctionDef) and any(ast.unparse(d) == "gl.public.write.payable" for d in fn.decorator_list):
                body = ast.unparse(fn)
                self.assertIn("except gl.vm.UserError", body, fn.name)
                self.assertIn("self._bounce(", body, fn.name)


class TestConsensusOnlyComparesStableFields(unittest.TestCase):
    """A byte-exact comparison of independently fetched pages never reaches
    agreement. Only facts that decide the outcome are compared."""

    def test_a_new_search_hit_between_leader_and_validator_fetches_still_agrees(self):
        b = m.BountyAnchor  # noqa: F841
        from _bootstrap import gather, search_url
        leader = m._manifest(gather({search_url(): search_json(4)}))
        validator = m._manifest(gather({search_url(): search_json(5)}))
        self.assertEqual(leader, validator)

    def test_fields_that_change_with_activity_are_not_in_the_pull_request_record(self):
        from _bootstrap import gather
        page = gather({pr_url(7): pr_json(7, comments=99, updated_at="2026-03-09T00:00:00Z")})[0]
        other = gather({pr_url(7): pr_json(7, comments=1, updated_at="2026-03-02T00:00:00Z")})[0]
        self.assertEqual(page["excerpt_sha256"], other["excerpt_sha256"])

    def test_raw_page_hashes_are_never_compared_by_validators(self):
        start = SOURCE.index("def _tier1_agree")
        end = SOURCE.index("def _jury_options")
        self.assertNotIn("full_content_sha256", SOURCE[start:end])


class TestStorageAccessPatterns(unittest.TestCase):
    def test_storage_maps_are_read_with_membership_checks_not_get(self):
        for name in ("bounties", "jurors", "pending_withdrawals", "pr_claims"):
            self.assertNotIn(f"self.{name}.get(", SOURCE)

    def test_no_inmem_allocate_or_min_datetime_sentinels(self):
        self.assertNotIn("inmem_allocate", SOURCE)
        self.assertNotIn("datetime.min", SOURCE)

    def test_no_keyword_arguments_to_run_nondet_unsafe(self):
        self.assertNotIn("run_nondet_unsafe(leader_fn=", SOURCE)

    def test_exec_prompt_result_is_not_treated_as_a_string(self):
        start = SOURCE.index("def _ask_model")
        end = SOURCE.index("def _tier1_compute")
        self.assertIn("_safe_json_obj(raw)", SOURCE[start:end])
        self.assertNotIn("raw.strip()", SOURCE[start:end])


if __name__ == "__main__":
    unittest.main()
