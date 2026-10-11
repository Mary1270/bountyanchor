import json
import unittest

from _bootstrap import m, pr_json, search_json, gh_ts, BASE_EPOCH, ISSUE, REPO, LOGIN, BRANCH


def extract(data, number=7, repo=REPO.lower(), issue=ISSUE):
    raw = data if isinstance(data, str) else json.dumps(data)
    return m._extract_pr(raw, number, repo, issue)


class TestTimestamps(unittest.TestCase):
    def test_valid_timestamp(self):
        self.assertEqual(m._gh_epoch("1970-01-01T00:00:00Z"), 0)
        self.assertEqual(m._gh_epoch("2026-03-01T12:00:00Z"), BASE_EPOCH)

    def test_round_trip_with_the_test_helper(self):
        for epoch in (0, 1, BASE_EPOCH, BASE_EPOCH + 86399, 2 ** 31):
            self.assertEqual(m._gh_epoch(gh_ts(epoch)), epoch)

    def test_result_is_an_int(self):
        self.assertIs(type(m._gh_epoch("2026-03-01T12:00:00Z")), int)

    def test_rejected_formats(self):
        for bad in (None, 5, "", "2026-03-01", "2026-03-01T12:00:00", "2026-03-01T12:00:00+00:00", "2026-03-01 12:00:00Z",
                    "2026-03-01T12:00:00.000Z", "2026-13-01T12:00:00Z", "2026-02-30T12:00:00Z", "2026-03-01T25:00:00Z",
                    "2026-03-01T12:60:00Z", "2026-03-01T23:59:60Z", "26-03-01T12:00:00Z", "2026-03-01T12:00:00Z ",
                    "\u0662026-03-01T12:00:00Z"):
            with self.subTest(bad=bad):
                self.assertIsNone(m._gh_epoch(bad))

    def test_leap_day(self):
        self.assertIsNotNone(m._gh_epoch("2028-02-29T00:00:00Z"))
        self.assertIsNone(m._gh_epoch("2027-02-29T00:00:00Z"))


class TestClosingKeywords(unittest.TestCase):
    def closes(self, text, issue=ISSUE, repo=REPO):
        return m._closes_issue(text, repo, issue)

    def test_every_github_keyword(self):
        for kw in ("close", "closes", "closed", "fix", "fixes", "fixed", "resolve", "resolves", "resolved"):
            with self.subTest(kw=kw):
                self.assertTrue(self.closes(f"{kw} #42"))

    def test_case_and_spacing_variants(self):
        for text in ("Fixes #42", "FIXES #42", "fIxEs #42", "Closes: #42", "resolves  #42", "Fixes\n#42", "Fixes\t#42",
                     "closes : #42", "Resolved:#42 ".replace(":#", ": #")):
            with self.subTest(text=text):
                self.assertTrue(self.closes(text))

    def test_inside_sentences_and_markup(self):
        for text in ("This PR fixes #42.", "(fixes #42)", "Done.\n\nCloses #42\n\nThanks", "- fixes #42\n- adds tests",
                     "**Fixes** #42".replace("**", ""), "title: Fix #42"):
            with self.subTest(text=text):
                self.assertTrue(self.closes(text))

    def test_cross_references_to_this_repository(self):
        self.assertTrue(self.closes("Fixes acme/widgets#42"))
        self.assertTrue(self.closes("Fixes ACME/Widgets#42"))
        self.assertTrue(self.closes("Closes https://github.com/acme/widgets/issues/42"))
        self.assertTrue(self.closes("closes https://github.com/Acme/Widgets/issues/42"))

    def test_references_to_other_repositories_never_count(self):
        self.assertFalse(self.closes("Fixes other/repo#42"))
        self.assertFalse(self.closes("Closes https://github.com/other/repo/issues/42"))
        self.assertFalse(self.closes("Fixes acme/widgets-fork#42"))
        self.assertFalse(self.closes("Fixes xacme/widgets#42"))

    def test_a_longer_number_is_not_the_issue(self):
        self.assertFalse(self.closes("Fixes #420"))
        self.assertFalse(self.closes("Fixes #421, #4200"))
        self.assertFalse(self.closes("Fixes #4"))
        self.assertTrue(self.closes("Fixes #42, #7"))
        self.assertTrue(self.closes("Fixes #1", issue=1))
        self.assertFalse(self.closes("Fixes #12", issue=1))

    def test_suffix_characters_make_it_a_different_token(self):
        self.assertFalse(self.closes("Fixes #42a"))
        self.assertFalse(self.closes("Fixes #42_x"))
        self.assertTrue(self.closes("Fixes #42-"))
        self.assertTrue(self.closes("Fixes #42!"))

    def test_words_that_merely_contain_a_keyword_do_not_count(self):
        for text in ("prefix #42", "unfixed #42", "affixes #42", "enclosed #42", "disclose #42", "foreclose #42",
                     "my_fixes #42", "x-fixes #42".replace("x-", "x")):
            with self.subTest(text=text):
                self.assertFalse(self.closes(text))

    def test_a_reference_without_a_keyword_does_not_count(self):
        for text in ("See #42", "Related to #42", "Part of #42", "#42", "Refs #42", "Addresses #42", "Implements #42",
                     "Fixes the bug described in #42"):
            with self.subTest(text=text):
                self.assertFalse(self.closes(text))

    def test_the_keyword_must_be_followed_by_whitespace(self):
        self.assertFalse(self.closes("Fixes#42"))
        self.assertFalse(self.closes("Fixes # 42"))
        self.assertFalse(self.closes("Fixes #\n42"))

    def test_empty_and_odd_inputs(self):
        self.assertFalse(self.closes(""))
        self.assertFalse(self.closes(None))
        self.assertFalse(self.closes("Fixes"))

    def test_repository_names_with_regex_metacharacters(self):
        self.assertTrue(m._closes_issue("Fixes a.b/c+d#5", "a.b/c+d", 5))
        self.assertFalse(m._closes_issue("Fixes aXb/c+d#5", "a.b/c+d", 5))
        self.assertFalse(m._closes_issue("Fixes a.b/ccd#5", "a.b/c+d", 5))


class TestExtractPr(unittest.TestCase):
    def test_decisive_facts(self):
        f = extract(pr_json(7))
        self.assertEqual(f["kind"], "pr")
        self.assertEqual(f["number"], 7)
        self.assertEqual(f["state"], "closed")
        self.assertTrue(f["merged"])
        self.assertFalse(f["draft"])
        self.assertEqual(f["merged_at"], BASE_EPOCH + 86400)
        self.assertEqual(f["created_at"], BASE_EPOCH + 3600)
        self.assertEqual(f["login"], LOGIN.lower())
        self.assertEqual(f["base_ref"], BRANCH)
        self.assertEqual(f["base_repo"], REPO)
        self.assertTrue(f["closes_issue"])
        self.assertEqual((f["changed_files"], f["additions"], f["deletions"]), (3, 120, 8))

    def test_login_and_repo_are_lowercased_but_the_branch_is_not(self):
        f = extract(pr_json(7, user={"login": "OCTODEV"}, base={"ref": "Release/1", "repo": {"full_name": "ACME/Widgets"}}))
        self.assertEqual((f["login"], f["base_repo"], f["base_ref"]), ("octodev", "acme/widgets", "Release/1"))

    def test_volatile_fields_are_not_part_of_the_facts(self):
        a = extract(pr_json(7, comments=1, updated_at="2026-03-02T00:00:00Z"))
        b = extract(pr_json(7, comments=900, updated_at="2026-04-02T00:00:00Z", review_comments=4, labels=[{"name": "x"}]))
        self.assertEqual(a, b)

    def test_facts_are_json_serialisable_and_stable(self):
        f = extract(pr_json(7))
        self.assertEqual(json.dumps(f, sort_keys=True), json.dumps(extract(pr_json(7)), sort_keys=True))

    def test_not_a_record_for_this_pull_request(self):
        for data in ([], "[]", "null", "7", '"x"', "", "   ", "<html>not json</html>", {"message": "Not Found"},
                     {"message": "API rate limit exceeded for 1.2.3.4"}):
            with self.subTest(data=data):
                self.assertIsNone(extract(data))

    def test_number_must_match_the_url(self):
        self.assertIsNone(extract(pr_json(8), number=7))
        self.assertIsNone(extract(pr_json(7), number=8))

    def test_number_must_be_a_real_integer(self):
        for bad in (True, "7", 7.0, None):
            with self.subTest(bad=bad):
                self.assertIsNone(extract(pr_json(number=bad), number=7))

    def test_required_structure(self):
        for key in ("user", "base"):
            with self.subTest(missing=key):
                data = pr_json(7)
                del data[key]
                self.assertIsNone(extract(data))
        for override in ({"user": {}}, {"user": {"login": ""}}, {"user": {"login": 5}}, {"user": "octodev"},
                         {"base": {"repo": {"full_name": REPO}}}, {"base": {"ref": BRANCH}},
                         {"base": {"ref": BRANCH, "repo": None}}, {"base": {"ref": "", "repo": {"full_name": REPO}}},
                         {"base": {"ref": BRANCH, "repo": {"full_name": ""}}}, {"base": []}):
            with self.subTest(override=override):
                self.assertIsNone(extract(pr_json(7, **override)))

    def test_merged_must_be_the_boolean_true(self):
        for val in ("true", 1, "yes", None):
            with self.subTest(val=val):
                self.assertFalse(extract(pr_json(7, merged=val))["merged"])
        self.assertTrue(extract(pr_json(7, merged=True))["merged"])

    def test_draft_must_be_the_boolean_true(self):
        self.assertTrue(extract(pr_json(7, draft=True))["draft"])
        self.assertFalse(extract(pr_json(7, draft="true"))["draft"])
        self.assertFalse(extract(pr_json(7, draft=KeyError))["draft"])

    def test_bad_timestamps_become_none(self):
        f = extract(pr_json(7, merged_at="yesterday", created_at=12345))
        self.assertIsNone(f["merged_at"])
        self.assertIsNone(f["created_at"])

    def test_open_pull_request_has_no_merge_time(self):
        f = extract(pr_json(7, state="open", merged=False, merged_at=None))
        self.assertEqual((f["state"], f["merged"], f["merged_at"]), ("open", False, None))

    def test_state_is_lowercased_and_bounded(self):
        self.assertEqual(extract(pr_json(7, state="OPEN"))["state"], "open")
        self.assertEqual(len(extract(pr_json(7, state="x" * 100))["state"]), 20)
        self.assertEqual(extract(pr_json(7, state=None))["state"], "")

    def test_null_and_missing_text_fields(self):
        f = extract(pr_json(7, body=None, title=None))
        self.assertEqual((f["title"], f["body_excerpt"], f["closes_issue"]), ("", "", False))
        self.assertFalse(extract(pr_json(7, body=KeyError, title=KeyError))["closes_issue"])

    def test_keyword_in_the_title_counts(self):
        self.assertTrue(extract(pr_json(7, title="Fixes #42: sort widgets", body=""))["closes_issue"])

    def test_keyword_far_into_a_long_body_still_counts(self):
        body = ("filler " * 2000) + "\nFixes #42"
        f = extract(pr_json(7, body=body))
        self.assertTrue(f["closes_issue"])
        self.assertLessEqual(len(f["body_excerpt"]), 1000)

    def test_keyword_beyond_the_scan_limit_does_not_count(self):
        body = ("x" * 25000) + " Fixes #42"
        self.assertFalse(extract(pr_json(7, body=body))["closes_issue"])

    def test_text_excerpts_are_normalised_and_bounded(self):
        f = extract(pr_json(7, title="  A \n  title\t here ", body="line one\r\n\r\nline   two " + "z" * 3000))
        self.assertEqual(f["title"], "A title here")
        self.assertTrue(f["body_excerpt"].startswith("line one line two zzz"))
        self.assertEqual(len(f["body_excerpt"]), 1000)
        self.assertEqual(len(extract(pr_json(7, title="t" * 1000))["title"]), 200)

    def test_counts_must_be_sane_integers(self):
        f = extract(pr_json(7, changed_files=-1, additions=True, deletions="5"))
        self.assertEqual((f["changed_files"], f["additions"], f["deletions"]), (None, None, None))
        self.assertIsNone(extract(pr_json(7, additions=10 ** 12))["additions"])

    def test_field_lengths_are_bounded(self):
        f = extract(pr_json(7, user={"login": "L" * 500}, base={"ref": "r" * 500, "repo": {"full_name": "n" * 500}}))
        self.assertEqual((len(f["login"]), len(f["base_ref"]), len(f["base_repo"])), (100, 200, 201))

    def test_viewer_chrome_around_the_json_is_tolerated(self):
        raw = "JSON Raw Data Headers\nSave Copy\n" + json.dumps(pr_json(7)) + "\n"
        self.assertEqual(extract(raw)["number"], 7)

    def test_oversized_content_is_not_parsed_beyond_the_cap(self):
        raw = json.dumps(pr_json(7)) + " " * 3000000 + "tail"
        self.assertEqual(extract(raw)["number"], 7)
        self.assertIsNone(extract(" " * 2000001 + json.dumps(pr_json(7))))


class TestExtractSearch(unittest.TestCase):
    def test_zero_results(self):
        self.assertEqual(m._extract_search(json.dumps(search_json(0))), {"kind": "search", "total": 0, "incomplete": False})

    def test_some_results_and_incomplete(self):
        self.assertEqual(m._extract_search(json.dumps(search_json(3, True))), {"kind": "search", "total": 1, "incomplete": True})

    def test_missing_or_wrong_fields(self):
        for data in ({}, {"total_count": 0}, {"total_count": 0, "incomplete_results": False},
                     {"total_count": True, "incomplete_results": False, "items": []},
                     {"total_count": -1, "incomplete_results": False, "items": []},
                     {"total_count": "0", "incomplete_results": False, "items": []},
                     {"total_count": 0, "incomplete_results": "false", "items": []},
                     {"total_count": 0, "incomplete_results": False, "items": {}},
                     {"message": "Validation Failed"}, [], "x"):
            with self.subTest(data=data):
                self.assertIsNone(m._extract_search(json.dumps(data)))

    def test_only_zero_or_nonzero_is_kept_so_validators_agree(self):
        for total in (1, 2, 3, 10 ** 15):
            self.assertEqual(m._extract_search(json.dumps(search_json(total)))["total"], 1)
        self.assertEqual(m._extract_search(json.dumps(search_json(0)))["total"], 0)

    def test_a_new_result_between_two_fetches_does_not_change_the_record(self):
        first = m._canonical_content({"search": m._extract_search(json.dumps(search_json(4)))})
        second = m._canonical_content({"search": m._extract_search(json.dumps(search_json(5)))})
        self.assertEqual(first, second)


class TestLenientJson(unittest.TestCase):
    def test_plain_and_wrapped(self):
        self.assertEqual(m._load_json_lenient('{"a": 1}'), {"a": 1})
        self.assertEqual(m._load_json_lenient('xx {"a": 1} yy'), {"a": 1})

    def test_garbage(self):
        for raw in (None, "", "   ", "no braces", "{broken", "} {", "{ not json }"):
            with self.subTest(raw=raw):
                self.assertIsNone(m._load_json_lenient(raw))

    def test_safe_json_obj(self):
        self.assertEqual(m._safe_json_obj({"a": 1}), {"a": 1})
        self.assertEqual(m._safe_json_obj('{"a": 1}'), {"a": 1})
        for raw in (None, "", "[]", "5", "nope", 5, []):
            with self.subTest(raw=raw):
                self.assertEqual(m._safe_json_obj(raw), {})


if __name__ == "__main__":
    unittest.main()
