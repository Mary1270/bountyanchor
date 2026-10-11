import datetime
import unittest

from _bootstrap import (
    m, gl, CLOCK, BASE, DAY, DEFAULT_DEADLINE, PARTY_A_ADDRESS, PARTY_B_ADDRESS, STRANGER_ADDRESS, REPO, LOGIN,
    make_contract, set_caller, create_bounty, accept_bounty, active_bounty, get, pr_url, search_url, anchors,
    submit_and_lock, pass_deadline, iso,
)

B = anchors()
CANON7 = "https://api.github.com/repos/acme/widgets/pulls/7"


class TestPullRequestUrls(unittest.TestCase):
    def item(self, url, b=B):
        return m._evidence_item(url, b)

    def test_plain_pull_request_url(self):
        self.assertEqual(self.item(CANON7), (CANON7, "pr", "7"))

    def test_repo_path_is_case_insensitive_and_canonicalised_to_the_anchor(self):
        self.assertEqual(self.item("https://api.github.com/repos/ACME/Widgets/pulls/7"), (CANON7, "pr", "7"))

    def test_host_case_is_normalised(self):
        self.assertEqual(self.item("https://API.GitHub.COM/repos/acme/widgets/pulls/7")[0], CANON7)

    def test_surrounding_whitespace_is_ignored(self):
        self.assertEqual(self.item("  " + CANON7 + "\n")[0], CANON7)

    def test_canonical_form_is_a_fixed_point(self):
        self.assertEqual(self.item(self.item(CANON7)[0]), (CANON7, "pr", "7"))

    def test_large_pull_request_numbers(self):
        self.assertEqual(self.item("https://api.github.com/repos/acme/widgets/pulls/9999999999")[2], "9999999999")

    def test_rejected_shapes(self):
        bad = [
            "http://api.github.com/repos/acme/widgets/pulls/7",
            "ftp://api.github.com/repos/acme/widgets/pulls/7",
            "//api.github.com/repos/acme/widgets/pulls/7",
            "api.github.com/repos/acme/widgets/pulls/7",
            "https://api.github.com@evil.example/repos/acme/widgets/pulls/7",
            "https://user@api.github.com/repos/acme/widgets/pulls/7",
            "https://user:pw@api.github.com/repos/acme/widgets/pulls/7",
            "https://api.github.com:443/repos/acme/widgets/pulls/7",
            "https://api.github.com:8443/repos/acme/widgets/pulls/7",
            "https://api.github.com:abc/repos/acme/widgets/pulls/7",
            "https://foo.api.github.com/repos/acme/widgets/pulls/7",
            "https://api.github.com.evil.example/repos/acme/widgets/pulls/7",
            "https://notapi.github.com/repos/acme/widgets/pulls/7",
            "https://evilapi.github.com/repos/acme/widgets/pulls/7",
            "https://api.github.com./repos/acme/widgets/pulls/7",
            "https://github.com/acme/widgets/pull/7",
            "https://www.github.com/repos/acme/widgets/pulls/7",
            "https://raw.githubusercontent.com/acme/widgets/main/x.json",
            "https://gist.github.com/x/1",
            "https://api.github.com/repos/other/widgets/pulls/7",
            "https://api.github.com/repos/acme/other/pulls/7",
            "https://api.github.com/repos/acme/widgets-fork/pulls/7",
            "https://api.github.com/repos/acme/widgets/pulls/7?x=1",
            "https://api.github.com/repos/acme/widgets/pulls/7#frag",
            "https://api.github.com/repos/acme/widgets/pulls/7/",
            "https://api.github.com/repos/acme/widgets/pulls/07",
            "https://api.github.com/repos/acme/widgets/pulls/0",
            "https://api.github.com/repos/acme/widgets/pulls/-1",
            "https://api.github.com/repos/acme/widgets/pulls/abc",
            "https://api.github.com/repos/acme/widgets/pulls/12345678901",
            "https://api.github.com/repos/acme/widgets/pulls/7/files",
            "https://api.github.com/repos/acme/widgets/pulls/7/commits",
            "https://api.github.com/repos/acme/widgets/pulls",
            "https://api.github.com/repos/acme/widgets/pulls/%37",
            "https://api.github.com/Repos/acme/widgets/pulls/7",
            "https://api.github.com/repos/acme/widgets/issues/7",
            "https://api.github.com/repos/acme/widgets/pull/7",
            "https://api.github.com/user",
            "https://api.github.com/",
            "https://api.github.com",
            "",
            "   ",
            "not a url",
            None,
            123,
        ]
        for url in bad:
            with self.subTest(url=url):
                self.assertIsNone(self.item(url))

    def test_a_url_with_an_embedded_tab_is_rebuilt_without_it(self):
        out = self.item("https://api.github.com/repos/acme/widgets/pulls/7\t")
        self.assertEqual(out[0] if out else None, CANON7)


class TestSearchUrls(unittest.TestCase):
    def item(self, url, b=B):
        return m._evidence_item(url, b)

    def test_canonical_search_url_is_accepted(self):
        out = self.item(search_url())
        self.assertEqual(out[1:], ("search", "search"))
        self.assertEqual(out[0], search_url())

    def test_plus_encoded_spaces_and_missing_per_page_are_accepted_and_canonicalised(self):
        url = "https://api.github.com/search/issues?q=repo:acme/widgets+is:pr+author:octodev+created:2026-03-01T12:00:00%2B00:00..2026-03-04T12:00:00%2B00:00"
        self.assertEqual(self.item(url)[0], search_url())

    def test_per_page_bounds(self):
        base = search_url().replace("&per_page=1", "")
        for good in ("1", "30", "100"):
            self.assertIsNotNone(self.item(base + "&per_page=" + good), good)
        for bad in ("0", "101", "abc", "-1", "", "1.5", "0100"):
            self.assertIsNone(self.item(base + "&per_page=" + bad), bad)

    def test_query_is_case_insensitive(self):
        url = "https://api.github.com/search/issues?q=REPO:Acme/Widgets+IS:PR+AUTHOR:OctoDev+CREATED:2026-03-01T12:00:00%2B00:00..2026-03-04T12:00:00%2B00:00"
        self.assertIsNotNone(self.item(url))

    def test_wrong_queries_are_rejected(self):
        bad_q = [
            "repo:acme/widgets is:pr author:someone-else created:>=2026-03-01",
            "repo:other/widgets is:pr author:octodev created:>=2026-03-01",
            "repo:acme/widgets is:pr author:octodev created:>=2026-02-01",
            "repo:acme/widgets is:pr author:octodev created:>=2026-03-02",
            "repo:acme/widgets is:pr author:octodev",
            "repo:acme/widgets is:issue author:octodev created:>=2026-03-01",
            "repo:acme/widgets is:pr author:octodev created:>=2026-03-01 extra",
            "repo:acme/widgets is:pr author:octodev -author:octodev created:>=2026-03-01",
            "",
        ]
        for q in bad_q:
            with self.subTest(q=q):
                self.assertIsNone(self.item("https://api.github.com/search/issues?q=" + q.replace(" ", "+")))

    def test_extra_or_duplicate_parameters_are_rejected(self):
        good_q = "repo%3Aacme%2Fwidgets%20is%3Apr%20author%3Aoctodev%20created%3A2026-03-01T12%3A00%3A00%2B00%3A00..2026-03-04T12%3A00%3A00%2B00%3A00"
        base = "https://api.github.com/search/issues?"
        self.assertIsNotNone(self.item(base + "q=" + good_q))
        self.assertIsNone(self.item(base + "q=" + good_q + "&sort=created"))
        self.assertIsNone(self.item(base + "q=" + good_q + "&q=" + good_q))
        self.assertIsNone(self.item(base + "per_page=1"))
        self.assertIsNone(self.item(base + "q=" + good_q + "&per_page=1&per_page=2"))
        self.assertIsNone(self.item(base + "q=" + good_q + "&page=2"))

    def test_other_search_endpoints_and_malformed_queries(self):
        self.assertIsNone(self.item("https://api.github.com/search/issues"))
        self.assertIsNone(self.item("https://api.github.com/search/issues?"))
        self.assertIsNone(self.item("https://api.github.com/search/code?q=x"))
        self.assertIsNone(self.item("https://api.github.com/search/issues/?q=x"))
        self.assertIsNone(self.item("https://api.github.com/search/issues?q"))
        self.assertIsNone(self.item("https://evil.example/search/issues?q=" + "x"))

    def test_query_text_follows_the_anchors(self):
        b = anchors(repo="Org/Repo", repo_key="org/repo", contributor_key="dev-1",
                    search_after="2027-01-09T08:00:00+00:00", search_before="2027-01-19T08:00:00+00:00")
        self.assertEqual(m._search_query(b),
                         "repo:org/repo is:pr author:dev-1 created:2027-01-09T08:00:00+00:00..2027-01-19T08:00:00+00:00")

    def test_a_literal_plus_in_the_timestamp_is_rejected_not_misread(self):
        url = "https://api.github.com/search/issues?q=repo:acme/widgets+is:pr+author:octodev+created:2026-03-01T12:00:00+00:00..2026-03-04T12:00:00+00:00"
        self.assertIsNone(self.item(url))

    def test_canonical_search_url_is_a_fixed_point(self):
        url = self.item(search_url())[0]
        self.assertEqual(self.item(url)[0], url)


class TestSubmitEvidence(unittest.TestCase):
    def setUp(self):
        self.c = make_contract()
        self.bid = active_bounty(self.c)

    def submit(self, caller, urls, bid=None):
        set_caller(caller)
        return self.c.submit_evidence(bid or self.bid, urls)

    def test_contributor_can_submit_and_urls_are_stored_canonically(self):
        self.submit(PARTY_B_ADDRESS, ["https://API.github.com/repos/ACME/widgets/pulls/7"])
        b = get(self.c, self.bid)
        self.assertEqual(b["evidence_submissions"][PARTY_B_ADDRESS.lower()], [CANON7])
        self.assertEqual(b["status"], "active")

    def test_sponsor_can_submit_the_no_pr_search(self):
        self.submit(PARTY_A_ADDRESS, [search_url()])
        self.assertEqual(get(self.c, self.bid)["evidence_submissions"][PARTY_A_ADDRESS.lower()], [search_url()])

    def test_strangers_cannot_submit(self):
        with self.assertRaises(gl.vm.UserError):
            self.submit(STRANGER_ADDRESS, [CANON7])

    def test_a_party_may_replace_its_list_a_limited_number_of_times(self):
        for number in (7, 8, 9):
            self.submit(PARTY_B_ADDRESS, [pr_url(number)])
        self.assertEqual(get(self.c, self.bid)["evidence_submissions"][PARTY_B_ADDRESS.lower()], [pr_url(9)])
        with self.assertRaises(gl.vm.UserError):
            self.submit(PARTY_B_ADDRESS, [pr_url(10)])

    def test_status_gates(self):
        posted = create_bounty(self.c)
        with self.assertRaises(gl.vm.UserError):
            self.submit(PARTY_B_ADDRESS, [CANON7], bid=posted)

    def test_one_bad_item_rejects_the_whole_submission(self):
        with self.assertRaises(gl.vm.UserError):
            self.submit(PARTY_B_ADDRESS, [CANON7, "https://evil.example/x"])
        self.assertEqual(get(self.c, self.bid)["evidence_submissions"], {})
        self.submit(PARTY_B_ADDRESS, [CANON7])

    def test_items_from_other_repositories_are_rejected(self):
        with self.assertRaises(gl.vm.UserError):
            self.submit(PARTY_B_ADDRESS, ["https://api.github.com/repos/other/repo/pulls/7"])

    def test_empty_and_non_list_inputs(self):
        for bad in ([], [""], ["   "], "https://api.github.com/repos/acme/widgets/pulls/7", None):
            with self.subTest(bad=bad):
                with self.assertRaises(gl.vm.UserError):
                    self.submit(PARTY_B_ADDRESS, bad)

    def test_url_length_cap(self):
        with self.assertRaises(gl.vm.UserError):
            self.submit(PARTY_B_ADDRESS, [CANON7 + "?" + "x" * 300])

    def test_at_most_five_distinct_items(self):
        with self.assertRaises(gl.vm.UserError):
            self.submit(PARTY_B_ADDRESS, [pr_url(n) for n in range(1, 7)])
        self.submit(PARTY_B_ADDRESS, [pr_url(n) for n in range(1, 6)])

    def test_spellings_of_one_record_count_once(self):
        spellings = [
            CANON7, "https://api.github.com/repos/ACME/WIDGETS/pulls/7", "  " + CANON7, CANON7 + "  ",
            "https://API.GITHUB.COM/repos/acme/widgets/pulls/7",
        ]
        self.submit(PARTY_B_ADDRESS, spellings)
        self.assertEqual(get(self.c, self.bid)["evidence_submissions"][PARTY_B_ADDRESS.lower()], [CANON7])

    def test_first_submission_sets_the_counterparty_grace_period(self):
        self.submit(PARTY_B_ADDRESS, [CANON7])
        b = get(self.c, self.bid)
        self.assertEqual(b["evidence_lock_at"], iso(DEFAULT_DEADLINE + datetime.timedelta(days=1)))
        self.assertEqual(b["status"], "active")

    def test_grace_period_starts_from_now_when_the_deadline_has_passed(self):
        pass_deadline(self.c, self.bid)
        CLOCK.advance(DAY)
        self.submit(PARTY_B_ADDRESS, [CANON7])
        b = get(self.c, self.bid)
        self.assertEqual(b["evidence_lock_at"], iso(CLOCK.now + datetime.timedelta(days=1)))

    def test_grace_period_never_passes_the_evidence_deadline(self):
        CLOCK.set(DEFAULT_DEADLINE + datetime.timedelta(days=2, hours=20))
        self.submit(PARTY_B_ADDRESS, [CANON7])
        b = get(self.c, self.bid)
        self.assertEqual(b["evidence_lock_at"], b["evidence_deadline"])

    def test_counterparty_can_answer_inside_the_grace_period(self):
        self.submit(PARTY_B_ADDRESS, [CANON7])
        CLOCK.advance(DAY)
        self.submit(PARTY_A_ADDRESS, [search_url()])
        b = get(self.c, self.bid)
        self.assertEqual(b["status"], "evidence_locked")
        self.assertEqual(b["evidence_snapshot"]["source_urls"], sorted([CANON7, search_url()]))
        self.assertEqual(b["evidence_snapshot"]["submitted_by"], sorted([PARTY_A_ADDRESS.lower(), PARTY_B_ADDRESS.lower()]))

    def test_counterparty_cannot_answer_after_the_grace_period(self):
        self.submit(PARTY_B_ADDRESS, [CANON7])
        CLOCK.set(datetime.datetime.fromisoformat(get(self.c, self.bid)["evidence_lock_at"]) + datetime.timedelta(seconds=1))
        with self.assertRaises(gl.vm.UserError):
            self.submit(PARTY_A_ADDRESS, [search_url()])

    def test_nobody_can_submit_after_the_evidence_deadline(self):
        CLOCK.set(datetime.datetime.fromisoformat(get(self.c, self.bid)["evidence_deadline"]) + datetime.timedelta(seconds=1))
        with self.assertRaises(gl.vm.UserError):
            self.submit(PARTY_B_ADDRESS, [CANON7])

    def test_merged_snapshot_deduplicates_across_parties(self):
        self.submit(PARTY_B_ADDRESS, [CANON7, pr_url(8)])
        self.submit(PARTY_A_ADDRESS, [pr_url(8), pr_url(9)])
        snap = get(self.c, self.bid)["evidence_snapshot"]
        self.assertEqual(snap["source_urls"], [pr_url(7), pr_url(8), pr_url(9)])
        self.assertEqual(snap["accepted_source_count"], 3)

    def test_url_set_hash_is_deterministic(self):
        import hashlib
        import json
        self.submit(PARTY_B_ADDRESS, [CANON7])
        self.submit(PARTY_A_ADDRESS, [search_url()])
        snap = get(self.c, self.bid)["evidence_snapshot"]
        expect = hashlib.sha256(json.dumps(sorted([CANON7, search_url()]), sort_keys=True).encode()).hexdigest()
        self.assertEqual(snap["evidence_url_set_hash"], expect)


class TestLockEvidence(unittest.TestCase):
    def setUp(self):
        self.c = make_contract()
        self.bid = active_bounty(self.c)

    def test_lock_without_submissions_is_rejected(self):
        with self.assertRaises(gl.vm.UserError):
            self.c.lock_evidence(self.bid)

    def test_lock_too_early_is_rejected(self):
        set_caller(PARTY_B_ADDRESS)
        self.c.submit_evidence(self.bid, [CANON7])
        set_caller(STRANGER_ADDRESS)
        with self.assertRaises(gl.vm.UserError):
            self.c.lock_evidence(self.bid)

    def test_anyone_can_lock_after_the_grace_period(self):
        set_caller(PARTY_B_ADDRESS)
        self.c.submit_evidence(self.bid, [CANON7])
        CLOCK.set(datetime.datetime.fromisoformat(get(self.c, self.bid)["evidence_lock_at"]) + datetime.timedelta(seconds=1))
        set_caller(STRANGER_ADDRESS)
        self.c.lock_evidence(self.bid)
        b = get(self.c, self.bid)
        self.assertEqual(b["status"], "evidence_locked")
        self.assertEqual(b["evidence_snapshot"]["source_urls"], [CANON7])

    def test_lock_twice_is_rejected(self):
        submit_and_lock(self.c, self.bid, [CANON7])
        with self.assertRaises(gl.vm.UserError):
            self.c.lock_evidence(self.bid)

    def test_submit_after_lock_is_rejected(self):
        submit_and_lock(self.c, self.bid, [CANON7])
        set_caller(PARTY_A_ADDRESS)
        with self.assertRaises(gl.vm.UserError):
            self.c.submit_evidence(self.bid, [search_url()])


class TestExpireNoEvidence(unittest.TestCase):
    def setUp(self):
        self.c = make_contract()
        self.bid = active_bounty(self.c)

    def test_cannot_expire_before_the_evidence_deadline(self):
        with self.assertRaises(gl.vm.UserError):
            self.c.expire_no_evidence(self.bid)

    def test_expire_with_no_submissions_refunds_both(self):
        CLOCK.set(datetime.datetime.fromisoformat(get(self.c, self.bid)["evidence_deadline"]) + datetime.timedelta(seconds=1))
        set_caller(STRANGER_ADDRESS)
        self.c.expire_no_evidence(self.bid)
        b = get(self.c, self.bid)
        self.assertEqual((b["status"], b["final_outcome"]), ("settled", "UNDETERMINED"))
        self.assertEqual(int(self.c.get_pending_withdrawal(PARTY_A_ADDRESS)), 10000)
        self.assertEqual(int(self.c.get_pending_withdrawal(PARTY_B_ADDRESS)), 2000)

    def test_expire_locks_submitted_evidence_instead_of_discarding_it(self):
        set_caller(PARTY_B_ADDRESS)
        self.c.submit_evidence(self.bid, [CANON7])
        CLOCK.set(datetime.datetime.fromisoformat(get(self.c, self.bid)["evidence_deadline"]) + datetime.timedelta(seconds=1))
        set_caller(STRANGER_ADDRESS)
        self.c.expire_no_evidence(self.bid)
        b = get(self.c, self.bid)
        self.assertEqual(b["status"], "evidence_locked")
        self.assertIsNone(b["final_outcome"])

    def test_expire_after_lock_is_rejected(self):
        submit_and_lock(self.c, self.bid, [CANON7])
        CLOCK.advance(10 * DAY)
        with self.assertRaises(gl.vm.UserError):
            self.c.expire_no_evidence(self.bid)

    def test_expire_twice_does_not_double_refund(self):
        CLOCK.set(datetime.datetime.fromisoformat(get(self.c, self.bid)["evidence_deadline"]) + datetime.timedelta(seconds=1))
        self.c.expire_no_evidence(self.bid)
        with self.assertRaises(gl.vm.UserError):
            self.c.expire_no_evidence(self.bid)
        self.assertEqual(int(self.c.get_pending_withdrawal(PARTY_A_ADDRESS)), 10000)


if __name__ == "__main__":
    unittest.main()
