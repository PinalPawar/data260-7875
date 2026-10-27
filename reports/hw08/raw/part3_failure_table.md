| Failure scenario | Before fix | After fix |
|---|---|---|
| Duplicate delivery | same task sent twice -> 2 model calls, 2 drafts (extra side effect) | 1 model call, 1 draft, 1 DUPLICATE-SKIP |
| Consumer killed mid-work | offset committed on receipt (committed=6 > msg offset 5); after restart redelivered=False -> LOST (never completed) | commit after send (committed=1 at kill); redelivered=True -> completed after restart |
| Poison message | Writer crashed 3x on the same offset; good message processed=False (blocked) | 3 attempts -> s7875_dead_letter (1 record); good message processed=True |
| Two partitions/two consumers | no key: 2/4 notices processed out of order (2 inversions) | key=notice_code: 0/4 out of order; each notice on one partition |
