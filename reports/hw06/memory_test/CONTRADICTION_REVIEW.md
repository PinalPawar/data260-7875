# HW6 Part 4.5 - review of the consolidation result

Input `MEMORY_original.md`: 55 non-empty, non-comment lines (46 facts).
Output `MEMORY_consolidated.md`: 39 lines (30 active facts + resolution history), run 2026-10-16 07:03 UTC.

## Duplicates (7 planted, 7 merged)

| Key | Lines merged | Kept wording | Correct? |
|---|---|---|---|
| user.name | 2 | Pinal Pawar | yes |
| allergy.user | 3 | Allergic to peanuts. | yes |
| allergy.son | 2 | egg allergy | yes |
| store.main | 2 | Safeway, because it is closer | yes |
| store.day | 2 | Saturdays | yes |
| home.food | 2 (spinach) | baby spinach, organic | yes |
| recall.returned | 2 (turkey) | deli turkey because of Listeria | yes |

The merged count is kept on the line (`merged 3`), so the history of how often a fact was stated is not lost.

## Contradictions (5 planted)

| Key | Conflict | Result | True answer | Verdict |
|---|---|---|---|---|
| family.son_age | 3 years old (Sep 2) vs 4 years old (Oct 5) | newest wins: 4 | 4 | correct |
| alert.channel | email (Sep 5) vs text message (Oct 8) | newest wins: text message | text message | correct |
| user.city | San Jose (user) vs Fresno (dream) | flagged: newest-wins would be wrong (weaker source); San Jose kept, sent to Needs review | San Jose | correct, caught by the check |
| allergy.son | eggs (user) vs no food allergies (assistant) | flagged: newest-wins would be wrong (weaker source); egg allergy kept, sent to Needs review | eggs | correct, caught by the check |
| **store.main** | **Safeway (user) vs Costco (user)** | **newest wins: Costco** | **Safeway** | **INCORRECT** |

## The contradiction that was resolved incorrectly: store.main

The user's own words were "My neighbor shops at Costco, but I prefer Safeway." A later fact
`store.main = Costco (source: user)` was recorded from that sentence, i.e. the neighbour's
store was attributed to the user. Both lines have the same source rank (user), so the
"stronger source" check does not fire, the key is not safety-critical, and newest-wins
picks Costco.

Three other facts in the file contradict the result and were not used: `store.loyalty = has a
Safeway club card`, `recall.returned = deli turkey to Safeway`, and the reason "because it is
closer". The rule only compares lines with the same key, so it cannot see this
cross-key evidence.

What makes this acceptable rather than silent data loss: the replaced value is recorded under
"## Resolved contradictions" with its date and source, so a person reading MEMORY.md can see
the conflict and restore it. A fix would be a cross-key check (for example, a store.main value
must agree with store.loyalty / recall store), or treating any same-rank conflict on a
preference key as "Needs review" instead of auto-resolving it.

## Nothing deleted silently

Every one of the 46 original facts is still represented: as an active fact, merged into an
active fact (count kept), or as a replaced value under "Resolved contradictions" /
"Needs review". One honest caveat: merging keeps only the newest wording, so small details of
older duplicates are dropped (for example "Saturday morning" became "Saturdays", and
"reads every label" disappeared from the peanut-allergy line). Running the consolidation a
second time changes nothing (39 -> 39 lines).
