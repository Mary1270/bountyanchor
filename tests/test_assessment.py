import unittest

from _bootstrap import (
    late_pr_json,
    m, pr_json, open_pr_json, search_json, pr_url, search_url, gh_ts, anchors, gather, assess,
    BASE_EPOCH, DEADLINE_EPOCH, DAY, ISSUE, LOGIN, REPO, BRANCH,
)

OTHER = {"login": "someone-else"}


def verdict_of(data, number=7, **b_over):
    a = assess({pr_url(number): data}, anchors(**b_over))
    return a["reports"][0]["verdict"] if a["reports"] else None


class TestDelivered(unittest.TestCase):
    def test_a_fully_matching_merged_pull_request_is_delivered(self):
        a = assess({pr_url(7): pr_json(7)})
        self.assertEqual(a["delivered_prs"], [7])
        self.assertEqual((a["pending_prs"], a["ambiguous_prs"], a["failed_prs"]), ([], [], []))
        self.assertFalse(a["non_delivery_supported"])
        self.assertEqual(a["parsed_prs"], 1)

    def test_report_lists_every_check(self):
        r = assess({pr_url(7): pr_json(7)})["reports"][0]
        self.assertEqual(
            {k: r[k] for k in ("number", "repo_ok", "base_ok", "author_ok", "linked", "merged", "in_window", "on_time", "draft", "verdict")},
            {"number": 7, "repo_ok": True, "base_ok": True, "author_ok": True, "linked": True, "merged": True,
             "in_window": True, "on_time": True, "draft": False, "verdict": "delivered"},
        )
        self.assertEqual(r["url"], pr_url(7))

    def test_author_comparison_ignores_case(self):
        self.assertEqual(verdict_of(pr_json(7, user={"login": "OCTODEV"})), "delivered")
        self.assertEqual(verdict_of(pr_json(7, user={"login": "octodev"}), contributor_key="octodev"), "delivered")

    def test_repository_comparison_ignores_case(self):
        self.assertEqual(verdict_of(pr_json(7, base={"ref": BRANCH, "repo": {"full_name": "Acme/WIDGETS"}})), "delivered")

    def test_base_branch_comparison_is_exact(self):
        # A wrong base can be set by a maintainer (retarget), so it is "rejected", never delivery.
        self.assertEqual(verdict_of(pr_json(7, base={"ref": "Main", "repo": {"full_name": REPO}})), "rejected")
        self.assertEqual(verdict_of(pr_json(7, base={"ref": "main2", "repo": {"full_name": REPO}})), "rejected")
        self.assertEqual(verdict_of(pr_json(7, base={"ref": "develop", "repo": {"full_name": REPO}})), "rejected")

    def test_merge_window_boundaries_are_inclusive(self):
        self.assertEqual(verdict_of(pr_json(7, merged_at=gh_ts(BASE_EPOCH))), "delivered")
        self.assertEqual(verdict_of(pr_json(7, merged_at=gh_ts(DEADLINE_EPOCH))), "delivered")

    def test_merged_one_second_before_the_bounty_existed_is_not_delivery(self):
        self.assertEqual(verdict_of(pr_json(7, merged_at=gh_ts(BASE_EPOCH - 1), created_at=gh_ts(BASE_EPOCH - 3600))), "unrelated")

    def test_merged_one_second_after_the_deadline_is_pending_not_delivered(self):
        self.assertEqual(verdict_of(pr_json(7, merged_at=gh_ts(DEADLINE_EPOCH + 1))), "pending")

    def test_integer_time_math_has_no_rounding(self):
        a = assess({pr_url(7): pr_json(7, merged_at=gh_ts(DEADLINE_EPOCH))}, anchors(deadline_epoch=DEADLINE_EPOCH - 1))
        self.assertEqual(a["delivered_prs"], [])

    def test_state_open_with_merged_true_still_counts_as_merged(self):
        self.assertEqual(verdict_of(pr_json(7, state="open")), "delivered")

    def test_several_deliveries_are_sorted_and_unique(self):
        a = assess({pr_url(9): pr_json(9), pr_url(3): pr_json(3), pr_url(5): pr_json(5)})
        self.assertEqual(a["delivered_prs"], [3, 5, 9])
        self.assertEqual([r["number"] for r in a["reports"]], [3, 5, 9])


class TestSingleFailures(unittest.TestCase):
    def test_not_merged_and_closed_is_rejected_not_breach(self):
        self.assertEqual(verdict_of(pr_json(7, merged=False, merged_at=None, state="closed")), "rejected")

    def test_merged_true_without_a_merge_time(self):
        self.assertEqual(verdict_of(pr_json(7, merged_at=None)), "rejected")
        self.assertEqual(verdict_of(pr_json(7, merged_at="garbage")), "rejected")

    def test_wrong_repository(self):
        self.assertEqual(verdict_of(pr_json(7, base={"ref": BRANCH, "repo": {"full_name": "acme/other"}})), "unrelated")

    def test_wrong_author(self):
        self.assertEqual(verdict_of(pr_json(7, user=OTHER)), "unrelated")

    def test_no_closing_keyword_is_ambiguous(self):
        self.assertEqual(verdict_of(pr_json(7, body="Adds sorting", title="Sort widgets")), "ambiguous")

    def test_closing_keyword_for_another_issue_is_ambiguous(self):
        self.assertEqual(verdict_of(pr_json(7, body="Fixes #43")), "ambiguous")

    def test_keyword_for_a_longer_issue_number_is_ambiguous(self):
        self.assertEqual(verdict_of(pr_json(7, body="Fixes #420")), "ambiguous")

    def test_keyword_for_another_repository_is_ambiguous(self):
        self.assertEqual(verdict_of(pr_json(7, body="Fixes other/repo#42")), "ambiguous")

    def test_a_reference_without_a_keyword_is_ambiguous(self):
        self.assertEqual(verdict_of(pr_json(7, body="See #42 for context")), "ambiguous")

    def test_each_failure_blocks_delivery(self):
        cases = [
            pr_json(7, merged=False), pr_json(7, user=OTHER), pr_json(7, body=""),
            pr_json(7, base={"ref": "dev", "repo": {"full_name": REPO}}),
            pr_json(7, merged_at=gh_ts(BASE_EPOCH - 5)), pr_json(7, merged_at=gh_ts(DEADLINE_EPOCH + 5)),
            pr_json(7, base={"ref": BRANCH, "repo": {"full_name": "x/y"}}),
        ]
        for data in cases:
            with self.subTest(data=data):
                self.assertEqual(assess({pr_url(7): data})["delivered_prs"], [])


class TestPending(unittest.TestCase):
    """Maintainer silence is not contributor breach."""

    def test_open_linked_on_time_pull_request_is_pending(self):
        a = assess({pr_url(7): open_pr_json(7)})
        self.assertEqual(a["pending_prs"], [7])
        self.assertEqual(a["delivered_prs"], [])
        self.assertFalse(a["non_delivery_supported"])

    def test_pending_pull_request_never_supports_non_delivery(self):
        a = assess({pr_url(7): open_pr_json(7), search_url(): search_json(0)})
        self.assertTrue(a["absence_proven"])
        self.assertFalse(a["non_delivery_supported"])

    def test_opened_exactly_at_the_deadline_is_on_time(self):
        self.assertEqual(verdict_of(open_pr_json(7, created_at=gh_ts(DEADLINE_EPOCH))), "pending")

    def test_opened_one_second_after_the_deadline_is_late_and_failed(self):
        self.assertEqual(verdict_of(open_pr_json(7, created_at=gh_ts(DEADLINE_EPOCH + 1))), "failed")

    def test_opened_before_the_bounty_existed_never_counts(self):
        self.assertEqual(verdict_of(open_pr_json(7, created_at=gh_ts(BASE_EPOCH - 10 * DAY))), "unrelated")

    def test_a_draft_is_not_pending_and_not_breach(self):
        self.assertEqual(verdict_of(open_pr_json(7, draft=True)), "rejected")

    def test_open_without_the_closing_keyword_is_ambiguous_not_pending(self):
        self.assertEqual(verdict_of(open_pr_json(7, body="no link")), "ambiguous")

    def test_open_pull_request_by_someone_else_is_unrelated(self):
        self.assertEqual(verdict_of(open_pr_json(7, user=OTHER)), "unrelated")

    def test_open_pull_request_on_the_wrong_base_is_rejected(self):
        self.assertEqual(verdict_of(open_pr_json(7, base={"ref": "dev", "repo": {"full_name": REPO}})), "rejected")

    def test_open_pull_request_in_another_repository_is_unrelated(self):
        self.assertEqual(verdict_of(open_pr_json(7, base={"ref": BRANCH, "repo": {"full_name": "a/b"}})), "unrelated")

    def test_merged_after_the_deadline_with_an_on_time_pull_request_is_pending(self):
        self.assertEqual(verdict_of(pr_json(7, merged_at=gh_ts(DEADLINE_EPOCH + 5 * DAY))), "pending")

    def test_merged_after_the_deadline_but_opened_late_is_failed(self):
        data = pr_json(7, created_at=gh_ts(DEADLINE_EPOCH + 100), merged_at=gh_ts(DEADLINE_EPOCH + 5 * DAY))
        self.assertEqual(verdict_of(data), "failed")

    def test_closed_unmerged_is_rejected_not_pending(self):
        self.assertEqual(verdict_of(pr_json(7, merged=False, merged_at=None, state="closed")), "rejected")

    def test_opened_after_the_deadline_is_failed(self):
        self.assertEqual(verdict_of(late_pr_json(7)), "failed")

    def test_missing_created_time_is_never_pending(self):
        self.assertEqual(verdict_of(open_pr_json(7, created_at=None)), "unrelated")

    def test_delivered_beats_pending_when_both_exist(self):
        a = assess({pr_url(7): open_pr_json(7), pr_url(8): pr_json(8)})
        self.assertEqual((a["delivered_prs"], a["pending_prs"]), ([8], [7]))


class TestNonDeliverySupport(unittest.TestCase):
    def test_a_late_contributor_pull_request_supports_it(self):
        a = assess({pr_url(7): late_pr_json(7)})
        self.assertEqual(a["failed_prs"], [7])
        self.assertTrue(a["non_delivery_supported"])

    def test_a_rejected_pull_request_does_not_support_it(self):
        a = assess({pr_url(7): pr_json(7, merged=False, merged_at=None, state="closed")})
        self.assertEqual((a["rejected_prs"], a["failed_prs"]), ([7], []))
        self.assertFalse(a["non_delivery_supported"])

    def test_someone_elses_pull_request_does_not(self):
        a = assess({pr_url(7): pr_json(7, user=OTHER)})
        self.assertEqual(a["reports"][0]["verdict"], "unrelated")
        self.assertFalse(a["non_delivery_supported"])

    def test_a_pull_request_in_another_repository_does_not(self):
        a = assess({pr_url(7): pr_json(7, base={"ref": BRANCH, "repo": {"full_name": "a/b"}})})
        self.assertFalse(a["non_delivery_supported"])

    def test_an_ambiguous_pull_request_blocks_it(self):
        a = assess({pr_url(7): pr_json(7, body="no link"), pr_url(8): late_pr_json(8)})
        self.assertEqual((a["ambiguous_prs"], a["failed_prs"]), ([7], [8]))
        self.assertFalse(a["non_delivery_supported"])

    def test_a_delivered_pull_request_blocks_it(self):
        a = assess({pr_url(7): pr_json(7), pr_url(8): pr_json(8, merged=False, merged_at=None, state="closed")})
        self.assertFalse(a["non_delivery_supported"])

    def test_proven_absence_supports_it(self):
        a = assess({search_url(): search_json(0)})
        self.assertTrue(a["absence_proven"])
        self.assertTrue(a["non_delivery_supported"])

    def test_incomplete_or_non_empty_search_proves_nothing(self):
        for blob in (search_json(0, incomplete=True), search_json(1), search_json(25)):
            with self.subTest(blob=blob):
                a = assess({search_url(): blob})
                self.assertFalse(a["absence_proven"])
                self.assertFalse(a["non_delivery_supported"])

    def test_absence_does_not_override_a_delivered_pull_request(self):
        a = assess({search_url(): search_json(0), pr_url(7): pr_json(7)})
        self.assertTrue(a["absence_proven"])
        self.assertEqual(a["delivered_prs"], [7])
        self.assertFalse(a["non_delivery_supported"])

    def test_absence_does_not_override_an_ambiguous_pull_request(self):
        a = assess({search_url(): search_json(0), pr_url(7): pr_json(7, body="")})
        self.assertFalse(a["non_delivery_supported"])


class TestUnreadableEvidence(unittest.TestCase):
    def test_fetch_errors_are_unparsed_and_prove_nothing(self):
        a = assess({pr_url(7): None})
        self.assertEqual((a["parsed_prs"], a["parsed_searches"], a["reports"]), (0, 0, []))
        self.assertFalse(a["non_delivery_supported"])
        self.assertEqual(a["delivered_prs"], [])

    def test_rate_limit_and_not_found_bodies(self):
        for body in ({"message": "API rate limit exceeded"}, {"message": "Not Found"}, "<html>429</html>", ""):
            with self.subTest(body=body):
                a = assess({pr_url(7): body})
                self.assertEqual(a["parsed_prs"], 0)
                self.assertFalse(a["non_delivery_supported"])

    def test_a_record_for_a_different_number_is_unparsed(self):
        a = assess({pr_url(7): pr_json(8)})
        self.assertEqual(a["parsed_prs"], 0)
        self.assertEqual(a["delivered_prs"], [])

    def test_a_pull_request_body_served_for_the_search_url_is_unparsed(self):
        a = assess({search_url(): pr_json(7)})
        self.assertEqual((a["parsed_searches"], a["absence_proven"]), (0, False))

    def test_a_search_body_served_for_a_pull_request_url_is_unparsed(self):
        a = assess({pr_url(7): search_json(0)})
        self.assertEqual(a["parsed_prs"], 0)

    def test_pages_with_urls_outside_the_anchors_are_ignored(self):
        pages = gather({pr_url(7): pr_json(7)})
        pages[0]["url"] = "https://api.github.com/repos/evil/repo/pulls/7"
        a = m._assess(pages, anchors())
        self.assertEqual((a["parsed_prs"], a["delivered_prs"]), (0, []))

    def test_forged_facts_for_another_number_are_ignored(self):
        pages = gather({pr_url(7): pr_json(7)})
        pages[0]["pr"] = dict(pages[0]["pr"], number=8)
        self.assertEqual(m._assess(pages, anchors())["delivered_prs"], [])

    def test_assessment_is_plain_json_data(self):
        import json
        a = assess({pr_url(7): pr_json(7), pr_url(8): open_pr_json(8), search_url(): search_json(0)})
        self.assertEqual(json.loads(json.dumps(a)), a)


class TestModelNeeded(unittest.TestCase):
    def a(self, **over):
        base = {"delivered_prs": [], "pending_prs": [], "ambiguous_prs": [], "failed_prs": [], "absence_proven": False,
                "parsed_prs": 0, "parsed_searches": 0, "non_delivery_supported": False, "reports": []}
        base.update(over)
        return base

    def test_delivery_needs_the_model_even_before_the_deadline(self):
        self.assertTrue(m._model_needed(self.a(delivered_prs=[7]), True))
        self.assertTrue(m._model_needed(self.a(delivered_prs=[7]), False))

    def test_pending_is_pure_code(self):
        self.assertFalse(m._model_needed(self.a(pending_prs=[7]), False))
        self.assertFalse(m._model_needed(self.a(pending_prs=[7], non_delivery_supported=False), True))

    def test_non_delivery_needs_the_model_only_after_the_deadline(self):
        self.assertTrue(m._model_needed(self.a(non_delivery_supported=True, failed_prs=[7]), False))
        self.assertFalse(m._model_needed(self.a(non_delivery_supported=True, failed_prs=[7]), True))

    def test_nothing_proven_is_pure_code(self):
        self.assertFalse(m._model_needed(self.a(), False))
        self.assertFalse(m._model_needed(self.a(ambiguous_prs=[7]), False))


class TestDecisionTable(unittest.TestCase):
    D = m.OUT_DELIVERED
    P = m.OUT_PARTIAL
    N = m.OUT_NOT_DELIVERED
    U = m.OUT_UNDETERMINED

    def a(self, **over):
        return TestModelNeeded().a(**over)

    def test_proven_delivery_stands_when_the_model_agrees_or_abstains(self):
        a = self.a(delivered_prs=[7])
        self.assertEqual(m._decide(a, self.D), self.D)
        self.assertEqual(m._decide(a, None), self.D)

    def test_the_model_may_only_downgrade_a_proven_delivery(self):
        a = self.a(delivered_prs=[7])
        self.assertEqual(m._decide(a, self.P), self.P)
        self.assertEqual(m._decide(a, self.U), self.U)
        self.assertEqual(m._decide(a, self.N), self.U)

    def test_pending_is_partial_whatever_the_model_says(self):
        a = self.a(pending_prs=[7])
        for claim in (None, self.D, self.P, self.N, self.U):
            with self.subTest(claim=claim):
                self.assertEqual(m._decide(a, claim), self.P)

    def test_pending_with_supposed_non_delivery_is_still_never_not_delivered(self):
        a = self.a(pending_prs=[7], non_delivery_supported=True)
        self.assertEqual(m._decide(a, self.N), self.P)

    def test_not_delivered_needs_code_support_and_the_model(self):
        self.assertEqual(m._decide(self.a(non_delivery_supported=True), self.N), self.N)
        self.assertEqual(m._decide(self.a(non_delivery_supported=True), self.U), self.U)
        self.assertEqual(m._decide(self.a(non_delivery_supported=True), None), self.U)
        self.assertEqual(m._decide(self.a(non_delivery_supported=False), self.N), self.U)

    def test_nothing_else_is_ever_delivered_or_partial(self):
        a = self.a()
        for claim in (None, self.D, self.P, self.N, self.U):
            with self.subTest(claim=claim):
                self.assertEqual(m._decide(a, claim), self.U)

    def test_decide_never_returns_delivered_without_a_delivered_pull_request(self):
        for pending in ([], [7]):
            for nds in (False, True):
                for amb in ([], [8]):
                    a = self.a(pending_prs=pending, non_delivery_supported=nds, ambiguous_prs=amb)
                    for claim in (None, self.D, self.P, self.N, self.U):
                        self.assertNotEqual(m._decide(a, claim), self.D)

    def test_backstop_forces_delivered_down_to_undetermined(self):
        self.assertEqual(m._apply_backstop(self.D, self.a()), self.U)
        self.assertEqual(m._apply_backstop(self.D, self.a(pending_prs=[7])), self.U)
        self.assertEqual(m._apply_backstop(self.D, self.a(ambiguous_prs=[7])), self.U)
        self.assertEqual(m._apply_backstop(self.D, self.a(delivered_prs=[7])), self.D)

    def test_backstop_leaves_other_claims_alone(self):
        for claim in (None, self.P, self.N, self.U):
            self.assertEqual(m._apply_backstop(claim, self.a()), claim)

    def test_premature_guard(self):
        self.assertEqual(m._premature_guard(self.N, True), self.U)
        self.assertEqual(m._premature_guard(self.P, True), self.U)
        self.assertEqual(m._premature_guard(self.D, True), self.D)
        self.assertEqual(m._premature_guard(self.U, True), self.U)
        for outcome in m.VALID_OUTCOMES:
            self.assertEqual(m._premature_guard(outcome, False), outcome)


class TestReasoningText(unittest.TestCase):
    def test_every_code_path_has_a_reason(self):
        a = TestModelNeeded().a
        cases = [
            (a(delivered_prs=[7]), m.OUT_DELIVERED, "#7"),
            (a(pending_prs=[7]), m.OUT_PARTIAL, "Maintainer silence is not contributor breach"),
            (a(delivered_prs=[7]), m.OUT_PARTIAL, "only part"),
            (a(ambiguous_prs=[7], parsed_prs=1), m.OUT_UNDETERMINED, "does not close the anchored issue"),
            (a(), m.OUT_UNDETERMINED, "no evidence page could be read"),
            (a(parsed_prs=1), m.OUT_UNDETERMINED, "neither proves delivery"),
            (a(), m.OUT_NOT_DELIVERED, "non-delivery"),
        ]
        for assessment, outcome, needle in cases:
            with self.subTest(outcome=outcome, needle=needle):
                self.assertIn(needle, m._code_reasoning(assessment, outcome))


if __name__ == "__main__":
    unittest.main()
