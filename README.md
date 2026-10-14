# BountyAnchor

Dispute resolution for GitHub code bounties, built as a GenLayer Intelligent Contract.

A sponsor escrows a reward. A contributor posts a performance bond. When the deadline arrives, the contract reads the pull request itself from the GitHub API and decides in code whether the work was delivered. A model is consulted only for questions code cannot answer. A staked, commit-reveal jury can overturn the automated outcome, but never without independent verification against the frozen evidence.

The central rule: **a maintainer who stays silent is not a contributor who failed.** A correct pull request by the right author, opened in time and still unmerged, is never resolved as not delivered. It resolves as partially delivered when a merit check affirms that the work substantively addresses the completion criteria, and otherwise as undetermined with both deposits refunded and the jury still available.

## What is anchored on-chain at creation

| Anchor | Example |
| --- | --- |
| Repository | `owner/name` |
| Base branch | `main` |
| Issue number | `42` |
| Contributor GitHub login | `octodev` |
| Deadline | ISO timestamp |
| Evidence host | `api.github.com` only |
| Bond and partial split | basis points |

The contributor sees every anchor before posting the bond.

## How a delivery is proven

The contract parses `https://api.github.com/repos/<repo>/pulls/<n>` itself. A pull request proves delivery only if all of these hold:

1. The pull request was opened at or after the bounty was created
2. `base.repo.full_name` equals the anchored repository
3. `base.ref` equals the anchored branch
4. `user.login` equals the contributor login (case-insensitive)
5. `merged` is true
6. `merged_at` falls inside the window between creation and deadline (integer time math)
7. The title or body has a closing keyword plus the anchored issue number

A code backstop forces any "delivered" claim down to undetermined unless every check passed. Passing the checks is necessary, not sufficient: full payment also needs an affirmative merit answer, and the silence or failure of the model never authorises payment. One merged pull request can settle only one bounty.

## Outcomes and payouts

| Outcome | Contributor receives | Sponsor receives |
| --- | --- | --- |
| BOUNTY_DELIVERED | reward + bond | nothing |
| PARTIALLY_DELIVERED | bond + reward x partial share | rest of the reward |
| NOT_DELIVERED | nothing | reward + bond |
| UNDETERMINED | bond | reward |

Not delivered needs both proof from the evidence (a pull request the contributor opened only after the deadline, or a verified empty GitHub search between creation and deadline, ruled at least 24 hours after the deadline) and agreement from the model. A pull request a maintainer closed, retargeted or turned into a draft is never automatic breach: Tier 1 refunds both sides and either party may ask the jury.

## Rules worth knowing

- **Early or immature rulings are rejected, not recorded.** If evidence cannot be read yet, or an empty search is less than 24 hours after the deadline, `adjudicate` reverts and the case stays open for a later attempt.
- **Rejected payments are refunded, not stranded.** A payable call that is rejected while GEN is attached credits that GEN to the sender's withdrawable balance and returns the reason instead of reverting.
- **The jury is bounded by the evidence.** `get_jury_options` lists what a jury may decide; it can never award delivery without a fully checked merged pull request, and jurors earn the same fee whichever way they vote.
- **Unjudged work is never paid.** If the model gives no usable answer, `adjudicate` reverts and can be retried. After 3 days past the deadline it rules in code only: delivered and pending pull requests become undetermined (each side refunded) and the jury can still decide.
- **Trivial work earns nothing automatically.** A pending pull request must carry a non-empty change and pass the merit check before any partial reward is paid.
- **One pull request, one reward.** When several bounties name the same pull request, the earliest created (by the contract's own counter) wins while the others are unsettled; the rest are refunded.

## Lifecycle

`posted` -> `active` -> `evidence_locked` -> `ruled` -> (`appeal_filed` -> `jury_voting`) -> `settled`

Every state has a way out: cancel, expire without evidence, expire unruled, settle unappealed, recover a stuck appeal. All payouts are credited to a ledger and moved only by `withdraw`.

## Repository layout

| Path | Purpose |
| --- | --- |
| `contract.py` | Documented contract |
| `contract_deploy.py` | Generated file to paste into GenLayer Studio |
| `contract_testnet_deploy.py` | Same contract with short time windows, used for the live tests |
| `TESTNET_TESTS.md` | Record of the live tests: wallets, results and transaction hashes |
| `tools/make_deploy.py` | Builds the deploy file using `ast` and `tokenize` |
| `tools/make_testnet_deploy.py` | Builds the short-window test copy from the deploy file |
| `index.html` | Single-file frontend (genlayer-js from esm.sh) |
| `tests/` | Offline tests with a self-written SDK stub |
| `ARCHITECTURE.md` | Design and disclosed limitations |

## Run the tests

No installs are needed.

```
python3 -m unittest discover -s tests
BA_CONTRACT=contract_deploy.py python3 -m unittest discover -s tests
python3 tools/make_deploy.py --check
```

## Deploy

1. Run `python3 tools/make_deploy.py` after any change to `contract.py`.
2. In GenLayer Studio, create a new contract file and paste the full content of `contract_deploy.py`. The file begins with exactly two header lines and contains no comments or docstrings, which Studio requires.
3. Deploy with no constructor arguments.
4. Open `index.html?contract=<deployed address>` once. The address is remembered in the browser.

## Methods

Writes: `create_bounty`, `accept_bounty`, `cancel_bounty`, `submit_evidence`, `lock_evidence`, `adjudicate`, `settle_unappealed`, `expire_no_evidence`, `expire_unruled`, `recover_stuck_appeal`, `register_juror`, `unstake_juror`, `file_appeal`, `draw_jury`, `commit_vote`, `reveal_vote`, `settle_jury`, `withdraw`.

Views: `get_bounty`, `list_bounties`, `get_stats`, `total_bounties`, `get_pr_claim`, `get_jury_options`, `count_eligible_jurors`, `get_juror`, `get_pending_withdrawal`, `get_contract_balance`, `verify_jury_selection`.

## Status

Deployed contracts: revision 2 (production windows) `0xe90E6535b7319101128aEC98b98602f7335739a2` on GenLayer Studio. The first revision `0x2608a47d0b6A2e7606cd4C89d23Db12f14B1bc97` and the short-window test builds (`0x1d53e9A4ADE1D751d9403ccfeC5eA2393ffF1aa8` first revision, `0xCDB499963a6796cF0A450D0eA8EC7B20be270BDE` revision 2) are kept for the test record.

Offline tests (552) cover the state machine, the GitHub extraction and assessment logic, payouts and the jury, including adversarial regression tests for the steward review (`tests/test_steward_corrections.py`): unavailable or negative model answers never authorise full payment, and unverified or trivial work never earns a partial reward automatically. The contract has also been run live on GenLayer Studio with real GitHub evidence, real consensus and real GEN transfers.

### Live test results

Revision note: the live results in the table below were recorded on the first revision. Revision 2 changes only the payout rules described in "Outcomes and payouts" and "Rules worth knowing" (merit check required for delivered and pending pull requests, non-empty change required for pending). It was tested live on a short-window build (`0xCDB499963a6796cF0A450D0eA8EC7B20be270BDE`): an open pull request with real work was ruled PARTIALLY_DELIVERED, and an open one-character pull request was ruled UNDETERMINED and refunded (see `TESTNET_TESTS.md`).

The time-gated paths were run on `contract_testnet_deploy.py`, a copy of the contract with short windows (5-minute appeal window, 15-minute commit and reveal, 1-hour resolution timeout). Only the time constants differ.

| Path | Result |
| --- | --- |
| Appeal, jury draw, commit-reveal, `settle_jury` | Passed, payouts matched the rules to the wei |
| `settle_unappealed` and `withdraw` | Passed |
| Open pull request that closes the issue | PARTIALLY_DELIVERED, pull request claimed |
| Pull request without a closing link | UNDETERMINED |
| `expire_no_evidence` | UNDETERMINED, both deposits refunded |
| `expire_unruled` | UNDETERMINED, both deposits refunded |
| One pull request offered to two bounties | Earlier bounty took the claim; the later one was refunded at settlement |
| `recover_stuck_appeal` | Not run live, reviewed in code only |

After every run the contract balance returned to zero. The frontend was tested live on the production contract with two throwaway test-session accounts (create, cancel, balance, withdraw, accept); it has not been tested with a browser-extension wallet. The full record, including transaction hashes, is in `TESTNET_TESTS.md`. See `ARCHITECTURE.md` for known limitations.

## License

MIT
