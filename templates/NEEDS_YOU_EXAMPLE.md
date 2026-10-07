# Needs you — email
Last run: 2026-10-07 12:05 · importer PC: Desktop · items: 3 need you, 2 waiting on others, 1 expected reply

## Needs you
| No. | Topic | Date | From | Subject | What to do | Thread file |
|---|---|---|---|---|---|---|
| NY-0021 | DEV/Financing/Bank | 2026-10-06 | accountant@example.com | Blocked current account | Fund the account before the 10th so the standing orders clear | <library>\Financing\Bank\Input\Emails\Emails\20261006_blocked-current-account_<thread id>.md |
| NY-0013 | DEV/Legal/Closing | 2026-10-01 | billing@lawfirm.example | Pending invoice | Pay invoice 207 or dispute the two extra hours | <library>\Legal\Closing\Input\Emails\Emails\20261001_pending-invoice_<thread id>.md |
| NY-0145 | BANK-PERSONAL | 2026-09-30 | alerts@bank.example | Card in arrears | Pay the card balance; the notice gives five days | |

## Waiting on others (FOLLOW-UP)
| No. | Topic | Date | To | Subject | Waiting for | Thread file |
|---|---|---|---|---|---|---|
| NY-0141 | DEV/Infrastructure/Water | 2026-09-21 | engineer@contractor.example | Updated treatment-plant offer | Revised offer on the new lot count | <library>\Infrastructure\Water\Input\Emails\Emails\20260921_updated-treatment-plant-offer_<thread id>.md |
| NY-0034 | RENTALS/Operations | 2026-09-19 | manager@rentals.example | Supplies list for the villa | Their quote for the approved items | <library>\Operations\Input\Emails\Emails\20260919_supplies-list-for-the-villa_<thread id>.md |

## Expected replies
| No. | Topic | Asked on | From | Pipeline | Expected | Status |
|---|---|---|---|---|---|---|
| EX-0002 | DEV/Sales/Escrow | 2026-09-29 | statements@escrow.example | escrow-extract | escrow export for 2026-08 | waiting · when it arrives, offer to run escrow-extract |

## How to answer
In any session say "mail" to see this list, then "done NY-0021", "snooze NY-0021 2026-10-15" or "correct NY-0021 DEV/Accounting/Tax". Sessions and the board write to NEEDS_YOU_status.csv (columns ts, item, action, value, chat, note; last row per item wins); this file is rewritten by the importer every hour and is never edited by hand. The mail label "__Needs you" mirrors the first table; "done" removes it on the next run.
