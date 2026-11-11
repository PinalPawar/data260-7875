**Planner → Writer coordination is strong.** On the end-to-end test question the plan was built from the recall notice and scored 4/5; the Writer followed it almost sentence for sentence and its draft scored 5/5. Most of the answer's quality is decided at the Planner.

**The Reviewer is a gate, not an editor.** It approves or rejects and forwards the Writer's text unchanged, so the final answer is identical to the draft and the final-vs-draft improvement is **0** (5 → 5). In this design the Reviewer cannot make an answer better, only stop a bad one (and only approved answers are cached). To see an improvement, the Reviewer would have to return a revised answer or send rejected drafts back to the Writer.

**Weak spot:** the Planner applies the "never eat it" safety rule to every recall, including a supply-shortage (incorrect fill level) notice, and nothing downstream checks the plan against the notice.

**Read these scores with care.** The judge (qwen3:8b, the same model as the Reviewer) failed validation in Part 3: Spearman −0.54 against my labels, mean |diff| 1.0, perfectly repeatable (0/20 changes). It rewards drafts that repeat the recall checklist rather than drafts that answer the question, so it should not gate a deployment on its own.
