# Live test record

All runs were made in GenLayer Studio with `contract_testnet_deploy.py`, which differs from `contract_deploy.py` only in its time constants (see the diff table below). Contract address of the test deployment: `0x1d53e9A4ADE1D751d9403ccfeC5eA2393ffF1aa8`. The production-window deployment is `0x2608a47d0b6A2e7606cd4C89d23Db12f14B1bc97`.

## Time constants

| Constant | Production | Test build |
| --- | --- | --- |
| Absence lag after deadline | 24 hours | 5 minutes |
| Model window after deadline | 3 days | 1 hour |
| Minimum deadline lead | 1 hour | 5 minutes |
| Evidence window | 3 days | 1 hour |
| Evidence grace | 24 hours | 5 minutes |
| Appeal window | 2 days | 5 minutes |
| Jury commit window | 2 days | 15 minutes |
| Jury reveal window | 1 day | 15 minutes |
| Resolution timeout | 7 days | 1 hour |

## Wallets

| Role | Address |
| --- | --- |
| Sponsor (party A) | `0xf73699c4A8C35a10fBFa74ca07CbEcA99b148Ffd` |
| Contributor (party B) | `0x72BE82aD9d8800d45e5cc22b4f2C29BBeDF73bc6` |

Five further wallets were registered as jurors with 1 GEN each for the jury run.

## Results

| Path | Bounties | Outcome |
| --- | --- | --- |
| Appeal, jury draw, commit-reveal vote, `settle_jury` | bounty_1 to bounty_3 era | Passed. Jury fee, minority slash split and forfeited appeal bond matched the rules to the wei. Contract balance returned to 0. |
| `settle_unappealed` and `withdraw` | bounty_1 (second run) | Passed |
| Open pull request without a closing link | bounty_4 | UNDETERMINED, as designed |
| Open pull request that closes the issue | bounty_5 | PARTIALLY_DELIVERED, pull request claimed |
| `expire_no_evidence` | bounty_2 | UNDETERMINED, both deposits refunded |
| `expire_unruled` | bounty_3 | UNDETERMINED, both deposits refunded |
| One pull request offered to two bounties | bounty_6, bounty_7 | Both ruled PARTIALLY_DELIVERED. At settlement bounty_6 (earlier) kept the claim and paid 2 GEN to the contributor and 1 GEN to the sponsor. bounty_7 (later) was refunded: 1 GEN to the contributor, 2 GEN to the sponsor. |
| `recover_stuck_appeal` | none | Not run live, reviewed in code only |

After the final withdrawals the contract balance was 0 GEN.

## Transactions

Hashes are shortened exactly as GenLayer Studio displays them. Full hashes are visible on the contract page in Studio.

### Expiry paths and final withdrawals (bounty_2, bounty_3)

| Step | Hash |
| --- | --- |
| `expire_unruled` bounty_3 | `0xd36c2ddf...4ba08964` |
| `expire_no_evidence` bounty_2 | `0x2f46dee6...b1503a0f` |

### Pull request ambiguity and partial delivery (bounty_4, bounty_5)

| Step | Hash |
| --- | --- |
| `adjudicate` bounty_4 | `0xc94fbcbf...c9c6aabc` |
| `adjudicate` bounty_5 | `0xe812dc97...262d6b05` |
| `settle_unappealed` bounty_4 | `0xad5f6151...ad536511` |
| `settle_unappealed` bounty_5 | `0x61766f79...32aab8f9` |

### Claim conflict (bounty_6, bounty_7)

| Step | Hash |
| --- | --- |
| `create_bounty` bounty_6 | `0xc9234840...f5aaeae8` |
| `create_bounty` bounty_7 | `0x7a9fb8ee...9601fc72` |
| `accept_bounty` bounty_6 | `0x4ec81a4e...9562589c` |
| `accept_bounty` bounty_7 | `0xd5ccb791...e080edf5` |
| `submit_evidence` bounty_6, sponsor | `0x95d4322f...a7de11bf` |
| `submit_evidence` bounty_6, contributor | `0x08b8868a...6e7dfbce` |
| `submit_evidence` bounty_7, sponsor | `0x0109afa1...8f5e6e1d` |
| `submit_evidence` bounty_7, contributor | `0x02787113...d65dd0b9` |
| `adjudicate` bounty_7 (first, takes the claim) | `0x233c7ada...049b7830` |
| `adjudicate` bounty_6 (second, takes it over) | `0xcf1012c6...2161c203` |
| `settle_unappealed` bounty_7 (refunded) | `0x08e03b77...c57c3c89` |
| `settle_unappealed` bounty_6 | `0x74bd8bd7...2c3d6360` |
| `withdraw` sponsor, 3 GEN | `0x91f64afc...4e3b68e7` |
| `withdraw` contributor, 3 GEN | `0xf63b0c13...a93f1f31` |

### Notes

- A `cancel_bounty` call (`0x2be464dc...2d9cb320`) was sent by mistake before the bounties were created. It reverted with "No bounty found with this id" and changed nothing.
- A second `withdraw` by the contributor after an earlier full withdrawal ended in ERROR and moved no funds.
