# BountyAnchor - Architecture

## 1. Design goals

1. Decide every structured fact in code, never by a model.
2. Use the model only for questions code cannot answer, and never let it override a code-proven fact.
3. Make every verdict path depend on content actually fetched and frozen on-chain.
4. Give every stuck state a permissionless way out.
5. Keep payouts pull-based so no settlement path can be blocked by a recipient.

## 2. Two-tier adjudication

**Tier 1 (`adjudicate`).** Anyone can call it once evidence is locked. The leader fetches each locked GitHub record, the contract parses it, and `_assess` classifies every pull request:

| Verdict | Meaning | Effect |
| --- | --- | --- |
| delivered | right repo, base and author; opened and merged inside [creation, deadline]; closes the issue | DELIVERED unless the model objects (PARTIAL or UNDETERMINED) |
| pending | same, opened in time, not a draft, still open or merged late | PARTIALLY_DELIVERED by code |
| ambiguous | would be delivered or pending but has no closing link | blocks NOT_DELIVERED |
| rejected | the contributor's pull request opened in time but closed unmerged, retargeted or a draft | UNDETERMINED; a maintainer can cause each of these |
| failed | the contributor's pull request opened after the deadline | supports NOT_DELIVERED |
| unrelated | anyone else's, another repository, or opened before the bounty existed | ignored |

NOT_DELIVERED needs code-supported non-delivery (a failed pull request, or the anchored search showing no pull request between creation and deadline, ruled at least 24 hours after the deadline) and the model's agreement. Anything else is UNDETERMINED.

Validators re-fetch and re-run the same code and compare the outcome, whether the model was used, the full assessment and a manifest of decisive fields. They never compare raw page hashes. Full-content hashes are audit-only, and an evidence root commits to the manifest plus those hashes.

**Model window.** The model is consulted only until 3 days after the deadline. If validators keep disagreeing on a model answer, a later call rules in code only: a proven delivery stands and NOT_DELIVERED becomes impossible. This keeps a case from being stuck until the 7-day refund.

**Tier 2 (appeal).** Either party may appeal within the window by posting a bond, but only if the frozen evidence permits a different outcome (`get_jury_options`). The juror pool is snapshotted at appeal time and the jury is drawn from a drand round that did not exist yet, using integer-only weighted sampling anyone can replay (`verify_jury_selection`). Jurors commit a hash bound to their address and the bounty, then reveal. A strict majority of the selected jurors stands only if it is one of the permitted outcomes, checked in code on every validator against the frozen evidence:

| Frozen evidence shows | Jury may choose |
| --- | --- |
| a delivered pull request | DELIVERED, PARTIAL, UNDETERMINED |
| maintainer silence (pending) | PARTIAL only, so no appeal |
| a rejected pull request | NOT_DELIVERED, PARTIAL, UNDETERMINED |
| an unlinked pull request | PARTIAL, UNDETERMINED |
| code-supported non-delivery | NOT_DELIVERED, UNDETERMINED |
| nothing decisive | UNDETERMINED |

So the jury can correct Tier 1, but can never award DELIVERED without a pull request that passed every structured check, and can never turn maintainer silence into breach.

**Jury pay is neutral.** With a verified majority, half the appeal bond is the jury fee and goes to the majority jurors whichever way they voted. The other half goes back to the appellant if the outcome changes, or to the other party if it stands. Jurors therefore earn the same for confirming or overturning. Non-revealers and minority voters are slashed; the slashed stake also goes to the majority.

## 3. Maintainer actions and maintainer silence

A sponsor may also maintain the repository. Silence (not merging) never counts against the contributor: a pending pull request resolves PARTIALLY_DELIVERED. Actions a maintainer can take on someone else's pull request (close it, retarget its base, convert it to a draft, edit its description) never produce an automatic NOT_DELIVERED either: such a pull request is "rejected", Tier 1 rules UNDETERMINED (each side refunded), and either party may ask the jury. Only facts the contributor alone controls support breach: no pull request opened in time, or a pull request opened after the deadline.

## 4. Claim registry

`pr_claims` maps `<repo>#<number>` to a bounty id. A delivered or partial outcome claims the pull request. Priority between bounties that name the same pull request follows the contract's own creation counter (`bounty_<n>`), never a timestamp: an unsettled claim held by a later bounty is taken over by an earlier one, and the displaced bounty is settled as UNDETERMINED (each side refunded). A later bounty facing an earlier claim is ruled UNDETERMINED. A settled claim is final and no payout is ever reversed. The claim is released if the final outcome is not a claim outcome (for example after an overturned appeal).

## 5. Money

- Reward is escrowed by the sponsor, bond (reward x bond_bps / 10000, 5% to 100%) by the contributor.
- Payouts are credited to `pending_withdrawals` and moved only by `withdraw`, which zeroes the ledger before the transfer.
- Rounding on a partial split goes to the sponsor, and totals are conserved for every outcome.
- Appeal bond: 20% of the reward; half is the jury fee (see section 2).
- A payable call rejected while GEN is attached credits the GEN back to the sender instead of reverting.

## 6. Recovery paths

| Stuck state | Way out |
| --- | --- |
| Posted, never accepted | `cancel_bounty` (sponsor) |
| Active, no evidence | `expire_no_evidence` |
| Active, one side silent | `lock_evidence` after the grace period |
| Evidence locked, validators disagree on the model | code-only `adjudicate` after the 3-day model window |
| Evidence locked, nobody rules | `expire_unruled` after the timeout |
| Ruled, no appeal | `settle_unappealed` |
| Appeal filed, never drawn | `recover_stuck_appeal` |
| Jury voting, never settled | `recover_stuck_appeal` |

## 7. Platform rules this contract follows

- Deploy file is two header lines then code, generated with `ast` and `tokenize` (never regex) and verified by comparing syntax trees.
- Storage types are class-level annotations; nothing assigns `{}` or `[]` to a storage container in `__init__`.
- `run_nondet_unsafe` takes leader and validator positionally, both defined without capturing `self`.
- Errors such as a 404 are caught inside the nondeterministic closure and returned as plain values.
- Caller identity comes from `gl.message.sender_address`; time comes from a single clock function that reads the transaction timestamp (`gl.message_raw["datetime"]`) and falls back to `datetime.now()`. Timestamps ending in `Z` are accepted.

## 8. Lessons from earlier GenLayer projects, applied here

| Earlier finding | How this contract handles it |
| --- | --- |
| Sensitive writes callable by anyone | Party-only and juror-only writes check `gl.message.sender_address`; an AST test classifies every public write |
| Verdict reasoned over a bare URL, never fetched | Every Tier-1 path fetches and parses the record; Tier 2 re-derives from the frozen fetched content |
| Validator only re-checked the leader's numbers for consistency | Tier 1 validators re-fetch, re-parse and re-decide on their own; Tier 2 is pure code over the frozen evidence |
| Numeric tolerance let leader and validator reach different decisions | Only categorical outcomes and exact facts are compared |
| Byte-exact hash of live pages never reached consensus | Only parsed, decisive fields are compared; a search total is reduced to zero or non-zero; raw page hashes are audit-only |
| Naive host parsing (`host:443@attacker`) | `urlsplit`, https only, no userinfo, exact host `api.github.com` |
| Same-domain source reordering, duplicate sources counted twice | Evidence is canonicalised and de-duplicated into a sorted set |
| No way out of a stuck evaluation | Every state has a permissionless recovery path |
| Exceptions inside a non-deterministic block crashed the call | Fetch and model errors are caught inside the closure and returned as plain values |
| `exec_prompt(response_format="json")` already returns an object | The answer is read as an object, never `.strip()`ed |
| `run_nondet_unsafe` keyword arguments, closures capturing `self`, `.value` instead of `.calldata` | Positional leader and validator defined at module level; validator reads `gl.vm.Return.calldata` |
| Storage assigned `{}` in `__init__`, `inmem_allocate`, `datetime.min` sentinels | Not used; storage is declared by class annotations |
| GEN attached to a reverted payable call stayed in the contract with no sender record | A rejected payable call with GEN attached does not revert: it credits the GEN back to the sender's withdrawable balance and returns the reason |
| Settling before the event | Only a proven delivery can be ruled before the deadline |
| Comments and docstrings broke Studio's schema loader; regex stripping gutted a real string | `contract_deploy.py` is built with `ast` and `tokenize` and verified by syntax-tree equality |
| Frontend with manual ID lookup and no routing | Hash routes, an Explore page fed by `list_bounties`, contextual actions per state |

## 9. Known limitations (disclosed)

1. **No wallet-to-GitHub binding (claim griefing, reduced not removed).** Nothing proves a wallet controls a GitHub login, and the platform offers no way to verify that on-chain. Policy for several bounties over the same pull request: priority goes to the bounty with the lowest creation counter (`bounty_<n>`, assigned by the contract, strict and not influenced by any caller input; one-second timestamps are never used). An unsettled claim held by a later bounty is taken over by an earlier one, and the displaced bounty is refunded (UNDETERMINED) when it settles. A claim that is already settled is final: no payout is ever reversed. Remaining attacks: (a) an attacker who creates a bounty for the same repository, issue and login before the real one exists has priority; (b) a copycat that is ruled and then left to settle (appeal window of 2 days) before the earlier bounty is ruled keeps the claim, so the genuine sponsor and contributor should submit evidence promptly and adjudicate early. In both cases the genuine bounty is refunded, not lost, but the contributor is not paid.
2. **Evidence is frozen by URL at lock, by content at adjudication.** The lock fixes which records are judged. Their content is fetched when `adjudicate` runs, validators re-fetch it, and the result is then stored and hashed. A pull request title, body or state edited between lock and adjudication changes what is judged. Decisive fields are compared across validators, so a disagreement fails consensus instead of recording a wrong value. Anyone can call `adjudicate` as soon as evidence is locked, which narrows the window.
3. **Unauthenticated GitHub API.** Rate limits can make a fetch fail, which produces UNDETERMINED rather than a wrong verdict, but can delay resolution.
4. **Search index lag and unreadable evidence (mitigated).** An empty "no pull request" search counts toward NOT_DELIVERED only if the ruling is at least 24 hours after the deadline. `adjudicate` does not record UNDETERMINED when the only reason is immature or unreadable evidence (an empty search inside the lag window, a fetch error, a rate-limit reply, invalid JSON, an incomplete search): it reverts, nothing is stored, and the same case can be ruled later. A closed, unmerged pull request by the contributor needs no wait. If evidence stays unreadable forever, `expire_unruled` refunds both sides 7 days after the later of the lock and the deadline. Search can still miss a pull request during a long GitHub index outage.
5. **Pull requests opened before the bounty never count.** The bounty pays for work started after it was posted. A policy that accepts earlier work would need an explicit anchor; none exists in this version.
6. **Merit is judged by a model.** Code proves the structure (author, base, merge window, closing link). Whether the change meets the completion criteria is a model judgment over the title, body and size, not a test run. It can only downgrade a proven delivery, never create one. CI status and commit checks are not used.
7. **Closing keyword regex.** It cannot see negation or code blocks ("does not fix #42" or a quoted example).
8. **Stake model.** Juror weight is capped and reputation-scaled, but several wallets controlled by one person are not detected.
9. **Jury threshold.** A strict majority of the selected jurors is needed. Low participation means the Tier-1 outcome stands and the appeal bond is returned.
10. **drand and clock.** The jury draw trusts the public drand beacon for that round and relies on the validators' pinned transaction time.
11. **Single evidence host.** Source diversity is replaced by distinct evidence items. Same-host duplicates are rejected, but all evidence still comes from api.github.com.
12. **Claim held until settlement.** A claimed pull request stays claimed until the bounty is finally settled, unless an earlier bounty takes it over.
13. **Stricter pending rule than the minimum.** A pending pull request must close the anchored issue and must not be a draft. A correct but unlinked pull request is "ambiguous" and resolves UNDETERMINED, not partial.
14. **Late merge.** A pull request opened on time but merged after the deadline resolves PARTIALLY_DELIVERED, not delivered.
15. **Evidence revisions.** Each party can replace its list up to 3 times until the snapshot locks (which happens as soon as both have submitted).
16. **A maintainer can cap a good delivery at PARTIALLY_DELIVERED by not merging before the deadline.** This follows from the rule that only a pull request merged inside the window is DELIVERED. Contributors should only accept bounties whose partial share they find acceptable, and the share is shown before acceptance.
17. **A GitHub username change breaks the author match.** The login is anchored at creation; a renamed account no longer matches.
18. **A junk pull request can force PARTIALLY_DELIVERED.** By design a correct-looking open pull request (right author and base, opened in the window, not a draft, closes the issue) is never NOT_DELIVERED. A contributor can open a trivial one to secure the partial split. The defence is the maintainer closing it unmerged before the ruling, which makes it a failed pull request.
19. **Juror Sybil resistance comes from stake, not identity.** Registration needs only the minimum stake and is refundable. Selection is stake-weighted (so splitting one stake across many wallets gains nothing below the cap), jurors must register before the bounty is accepted, and the draw uses a future drand round, but one owner of many wallets is not detected.
20. **A maintainer can edit a merged pull request's description to sway the model.** The model can then only downgrade a proven delivery (to PARTIAL or UNDETERMINED), never create one or turn it into breach; the contributor's remedy is an appeal, where the jury may restore DELIVERED.
21. **An appeal delays settlement by about five days** (draw after the window, two days to commit, one to reveal). If the jury fails to form a majority the appellant gets the bond back, so an appeal costs little more than time.
22. **Live coverage is partial.** The contract has run on GenLayer Studio (see the live test results in the README), but only through Studio calls. The frontend has not been exercised with a real wallet, `recover_stuck_appeal` has not been run live, and the waiting periods of the production build (48-hour appeal window, 2-day commit, 1-day reveal) were exercised through a short-window variant, `contract_testnet_deploy.py`, whose only difference is the time constants.

## 10. Testing

Offline tests run against a self-written SDK stub that reproduces the real SDK's habits: empty storage containers, range-checked `u256`, a JSON round trip of the leader result, and a validator that receives `gl.vm.Return`. A controllable clock replaces the contract's single clock function. The whole suite runs against both `contract.py` and `contract_deploy.py`. The stub does not simulate real networks, real models or multi-validator consensus.
