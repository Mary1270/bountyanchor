"""
Shared test bootstrap: wires up the offline genlayer SDK stub, loads the
contract once (contract.py by default, or the file named by the
BA_CONTRACT environment variable, which is how the stripped deploy file is
tested), replaces the contract's single clock with a controllable one, and
provides builders for bounties, GitHub pull request records and flows.
"""
import datetime as _dt
import hashlib as _hashlib
import importlib.util
import json as _json
import os
import sys
from unittest.mock import patch as _patch

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_STUB_DIR = os.path.join(_THIS_DIR, "genlayer_stub")
if _STUB_DIR not in sys.path:
    sys.path.insert(0, _STUB_DIR)

CONTRACT_PATH = os.environ.get("BA_CONTRACT") or os.path.join(os.path.dirname(_THIS_DIR), "contract.py")
_spec = importlib.util.spec_from_file_location("bountyanchor_contract", CONTRACT_PATH)
_contract_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_contract_module)

m = _contract_module
BountyAnchor = m.BountyAnchor
gl = m.gl
Address = m.Address
u256 = m.u256

# Production floors are 1e15 wei; tests use tiny amounts.
BountyAnchor.MIN_STAKE = u256(1)
BountyAnchor.MIN_BOND = u256(1)
BountyAnchor.MIN_JUROR_STAKE = u256(1)
BountyAnchor.MIN_APPEAL_BOND = u256(1)

REAL_NOW_UTC = BountyAnchor.__dict__["_now_utc"]

UTC = _dt.timezone.utc
BASE = _dt.datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
DAY = 86400


class Clock:
    """The contract's only clock, replaced for tests."""

    def __init__(self):
        self.now = BASE

    def reset(self):
        self.now = BASE

    def set(self, moment):
        self.now = moment

    def advance(self, seconds):
        self.now = self.now + _dt.timedelta(seconds=seconds)


CLOCK = Clock()
BountyAnchor._now_utc = staticmethod(lambda: CLOCK.now)

PARTY_A_ADDRESS = "0x" + "11" * 20
PARTY_B_ADDRESS = "0x" + "22" * 20
STRANGER_ADDRESS = "0x" + "33" * 20
JUROR_ADDRESSES = ["0x" + hex(0xa0 + i)[2:].rjust(2, "0") * 20 for i in range(12)]

REPO = "acme/widgets"
BRANCH = "main"
ISSUE = 42
LOGIN = "OctoDev"
REWARD = 10000
BOND_BPS = 2000
BOND = REWARD * BOND_BPS // 10000
PARTIAL_BPS = 5000


def make_contract():
    CLOCK.reset()
    reset_transfers()
    return BountyAnchor()


def set_caller(address_str):
    gl.message.sender_address = Address(address_str)


def reset_transfers():
    gl.evm.transfers.clear()


class PaymentRejected(gl.vm.UserError):
    """Raised by the test helper when a payable call was rejected and its
    GEN refunded to the sender (the contract does not revert in that case,
    so it can never keep GEN with no record of the sender)."""


def _state(contract):
    return (dict(contract.bounties), int(contract.bounty_count), dict(contract.jurors), dict(contract.pr_claims),
            int(contract.settled_count), int(contract.cancelled_count))


def call_payable(contract, method_name, value, *args, **kwargs):
    """Invoke a payable method as if `value` wei were sent with the call.

    - The value is credited to the contract balance first; if the method
      raises (only possible with no GEN attached) the credit is rolled
      back, like a reverted transaction.
    - If the method returns a rejection, the helper checks that the exact
      value was credited back to the sender and that nothing else changed,
      then raises PaymentRejected so tests can assert the rejection."""
    gl.message.value = u256(value)
    contract.balance = contract.balance + u256(value)
    sender = str(gl.message.sender_address).lower()
    before_state = _state(contract)
    before_owed = int(contract.pending_withdrawals[sender]) if sender in contract.pending_withdrawals else 0
    try:
        result = getattr(contract, method_name)(*args, **kwargs)
    except Exception:
        contract.balance = contract.balance - u256(value)
        raise
    finally:
        gl.message.value = u256(0)
    if isinstance(result, str) and result.startswith('{"refunded_wei"'):
        data = _json.loads(result)
        after_owed = int(contract.pending_withdrawals[sender]) if sender in contract.pending_withdrawals else 0
        assert data["refunded_wei"] == str(int(value)), data
        assert after_owed - before_owed == int(value), (before_owed, after_owed, value)
        assert _state(contract) == before_state, "a rejected payable call changed state"
        raise PaymentRejected(data["rejected"])
    return result


def iso(moment):
    return moment.isoformat()


def gh_ts(epoch):
    """GitHub-style timestamp for epoch seconds."""
    return _dt.datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


BASE_EPOCH = int(BASE.timestamp())
DEFAULT_DEADLINE = BASE + _dt.timedelta(days=3)
DEADLINE_EPOCH = int(DEFAULT_DEADLINE.timestamp())


def pr_url(number, repo=REPO):
    return f"https://api.github.com/repos/{repo}/pulls/{number}"


def search_url(c=None, **over):
    b = {"repo_key": REPO.lower(), "contributor_key": LOGIN.lower(),
         "search_after": "2026-03-01T12:00:00+00:00", "search_before": "2026-03-04T12:00:00+00:00"}
    b.update(over)
    return "https://api.github.com/search/issues?q=" + m.quote(m._search_query(b), safe="") + "&per_page=1"


def pr_json(number=7, **over):
    """A GitHub pull request record. By default: merged one day after the
    bounty was posted, by the anchored contributor, on the anchored base,
    closing the anchored issue."""
    data = {
        "number": number,
        "state": "closed",
        "merged": True,
        "draft": False,
        "title": "Add widget sorting",
        "body": f"Implements sorting.\n\nFixes #{ISSUE}",
        "created_at": gh_ts(BASE_EPOCH + 3600),
        "merged_at": gh_ts(BASE_EPOCH + DAY),
        "user": {"login": LOGIN},
        "base": {"ref": BRANCH, "repo": {"full_name": REPO}},
        "changed_files": 3,
        "additions": 120,
        "deletions": 8,
        "comments": 5,
        "updated_at": gh_ts(BASE_EPOCH + DAY + 60),
    }
    for key, value in over.items():
        if value is KeyError:
            data.pop(key, None)
        else:
            data[key] = value
    return data


def open_pr_json(number=7, **over):
    """A pull request that is still open: maintainer has not acted."""
    base = dict(state="open", merged=False, merged_at=None)
    base.update(over)
    return pr_json(number, **base)


def late_pr_json(number=7, **over):
    """The contributor's pull request opened only after the deadline: the
    one pull request fact that only the contributor controls, so it
    supports NOT_DELIVERED."""
    base = dict(created_at=gh_ts(DEADLINE_EPOCH + 3600), state="closed", merged=False, merged_at=None)
    base.update(over)
    return pr_json(number, **base)


def search_json(total=0, incomplete=False):
    return {"total_count": total, "incomplete_results": incomplete, "items": []}


def create_bounty(c, reward=REWARD, deadline=None, party_a=PARTY_A_ADDRESS, party_b=PARTY_B_ADDRESS,
                  repo=REPO, branch=BRANCH, issue=ISSUE, login=LOGIN, terms="Add widget sorting",
                  criteria="Sorting works and has tests", bond_bps=BOND_BPS, partial_bps=PARTIAL_BPS):
    set_caller(party_a)
    return call_payable(
        c, "create_bounty", reward, party_b, repo, branch, issue, login, terms, criteria,
        iso(deadline or DEFAULT_DEADLINE), bond_bps, partial_bps,
    )


def accept_bounty(c, bounty_id, bond=BOND, party_b=PARTY_B_ADDRESS):
    set_caller(party_b)
    return call_payable(c, "accept_bounty", bond, bounty_id)


def get(c, bounty_id):
    return _json.loads(c.get_bounty(bounty_id))


def submit_and_lock(c, bounty_id, urls, party=PARTY_B_ADDRESS):
    """Submit evidence as `party`; if the counterparty has not answered,
    move past the grace period and lock, as a real caller would."""
    set_caller(party)
    c.submit_evidence(bounty_id, urls)
    if get(c, bounty_id)["status"] == "active":
        CLOCK.set(_dt.datetime.fromisoformat(get(c, bounty_id)["evidence_lock_at"]) + _dt.timedelta(seconds=1))
        c.lock_evidence(bounty_id)


def pass_deadline(c, bounty_id):
    b = get(c, bounty_id)
    deadline = _dt.datetime.fromisoformat(b["deadline"])
    if CLOCK.now <= deadline:
        CLOCK.set(deadline + _dt.timedelta(seconds=5))


def web_for(pages):
    """A render replacement: url -> text (dict values are JSON-encoded)."""
    def render(url, mode="text"):
        value = pages.get(url)
        if value is None:
            raise RuntimeError("404")
        return value if isinstance(value, str) else _json.dumps(value)
    return render


def adjudicate(c, bounty_id, pages, model=None, prompts=None, caller=STRANGER_ADDRESS):
    """Run adjudicate with the given fetch results and model answer.
    `model` is a dict, an Exception instance to raise, or None (the model
    must then not be called). Returns the bounty dict."""
    calls = prompts if prompts is not None else []

    def exec_prompt(prompt, response_format="json"):
        calls.append(prompt)
        if model is None:
            raise AssertionError("the model must not be called here")
        if isinstance(model, Exception):
            raise model
        return model

    set_caller(caller)
    with _patch.object(gl.nondet.web, "render", side_effect=web_for(pages)), \
            _patch.object(gl.nondet, "exec_prompt", side_effect=exec_prompt):
        c.adjudicate(bounty_id)
    return get(c, bounty_id)


def active_bounty(c, **over):
    """A bounty posted and accepted at the base time."""
    bounty_id = create_bounty(c, **over)
    reward = over.get("reward", REWARD)
    bond_bps = over.get("bond_bps", BOND_BPS)
    accept_bounty(c, bounty_id, bond=reward * bond_bps // 10000)
    return bounty_id


def locked_bounty(c, urls=None, both=False, **over):
    """An accepted bounty whose evidence is locked. With `both` the sponsor
    answers too, so the lock happens at once and the clock does not move;
    otherwise the clock moves past the counterparty grace period."""
    urls = urls or [pr_url(7)]
    bounty_id = active_bounty(c, **over)
    if both:
        set_caller(PARTY_B_ADDRESS)
        c.submit_evidence(bounty_id, urls)
        set_caller(PARTY_A_ADDRESS)
        c.submit_evidence(bounty_id, urls)
    else:
        submit_and_lock(c, bounty_id, urls)
    return bounty_id


def ruled_bounty(c, pages=None, model=None, urls=None, after_deadline=True, **over):
    """A bounty carried through Tier 1."""
    pages = pages if pages is not None else {pr_url(7): pr_json(7)}
    bounty_id = locked_bounty(c, urls=urls or list(pages.keys()), **over)
    if after_deadline:
        pass_deadline(c, bounty_id)
    adjudicate(c, bounty_id, {u: v for u, v in pages.items()}, model=model)
    return bounty_id


def register_jurors(c, count=6, base_stake=1000):
    for i, addr in enumerate(JUROR_ADDRESSES[:count]):
        set_caller(addr)
        call_payable(c, "register_juror", base_stake + i * 100)


def pass_appeal_window(c, bounty_id):
    b = get(c, bounty_id)
    CLOCK.set(_dt.datetime.fromisoformat(b["appeal_deadline"]) + _dt.timedelta(seconds=120))


def draw_jury(c, bounty_id, beacon="fixed-test-beacon"):
    pass_appeal_window(c, bounty_id)
    b = get(c, bounty_id)
    page = _json.dumps({"round": b["appeal"]["draw_round"], "randomness": beacon})
    with _patch.object(gl.nondet.web, "render", return_value=page):
        c.draw_jury(bounty_id)


def commit_hash(vote, salt, bounty_id, juror):
    return _hashlib.sha256(f"{vote}:{salt}:{str(juror).lower()}:{bounty_id}".encode()).hexdigest()


def pending(c, address):
    return int(c.get_pending_withdrawal(address))


def expect_user_error(testcase, fn, *args, **kwargs):
    with testcase.assertRaises(gl.vm.UserError) as ctx:
        fn(*args, **kwargs)
    return str(ctx.exception)


def anchors(**over):
    """The anchor fields the module-level helpers read, as a plain dict."""
    b = {
        "repo": REPO, "repo_key": REPO.lower(), "base_branch": BRANCH, "issue_number": ISSUE,
        "contributor_login": LOGIN, "contributor_key": LOGIN.lower(),
        "created_epoch": BASE_EPOCH, "deadline_epoch": DEADLINE_EPOCH,
        "search_after": "2026-03-01T12:00:00+00:00", "search_before": "2026-03-04T12:00:00+00:00",
        "bounty_terms": "Add widget sorting", "completion_criteria": "Sorting works and has tests",
        "created_at": iso(BASE), "deadline": iso(DEFAULT_DEADLINE),
    }
    b.update(over)
    return b


def gather(mapping, b=None):
    """Run the contract's page gathering over a url -> content mapping."""
    with _patch.object(gl.nondet.web, "render", side_effect=web_for(mapping)):
        return m._gather_pages(list(mapping.keys()), b or anchors())


def assess(mapping, b=None):
    b = b or anchors()
    return m._assess(gather(mapping, b), b)
