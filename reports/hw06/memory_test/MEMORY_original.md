# MEMORY.md - durable facts (file-based memory)
<!-- last_consolidated: 2026-10-10T18:00:00+00:00 -->
<!-- HW6 Part 4.5 test file: 55 non-empty, non-comment lines (9 headings + 46 facts), written by hand.
     Planted duplicates (7): user.name x2, allergy.user x3, allergy.son x2, store.main x2,
       store.day x2, home.food spinach x2, recall.returned turkey x2.
     Planted contradictions (5) and the TRUE answer:
       user.city       San Jose (user)  vs Fresno (dream, from the sister's sentence)   -> true: San Jose
       family.son_age  3 years old      vs 4 years old (after his birthday)              -> true: 4
       allergy.son     allergic to eggs (user) vs no food allergies (assistant guess)    -> true: eggs
       store.main      Safeway (user)   vs Costco (user, really the neighbour's store)  -> true: Safeway
       alert.channel   email            vs text message (user changed it)                -> true: text message -->
## Profile
- [2026-09-02] user.name = Pinal (source: user)
- [2026-09-02] user.city = San Jose, California (source: user)
- [2026-09-02] user.language = English (source: user)
- [2026-09-02] user.household = family of three (source: user)
- [2026-10-01] user.name = Pinal Pawar (source: user)
- [2026-10-13] user.city = Fresno (source: dream)
## Health
- [2026-09-02] allergy.user = allergic to peanuts (source: user)
- [2026-09-10] allergy.user = peanut allergy, reads every label (source: user)
- [2026-10-03] allergy.user = Allergic to peanuts. (source: user)
- [2026-09-12] health.user = no other health conditions mentioned (source: user)
- [2026-09-12] pref.diet = avoids very spicy food (source: user)
## Family
- [2026-09-02] family.son_name = Arjun (source: user)
- [2026-09-02] family.son_age = 3 years old (source: user)
- [2026-09-02] allergy.son = allergic to eggs (source: user)
- [2026-09-20] allergy.son = egg allergy (source: user)
- [2026-10-02] family.sister = Meera, lives in Fresno, pregnant (source: user)
- [2026-10-05] family.son_age = 4 years old (source: user)
- [2026-10-14] allergy.son = no food allergies (source: assistant)
- [2026-09-18] family.son_school = preschool on weekdays (source: user)
## Shopping
- [2026-09-05] store.main = Safeway (source: user)
- [2026-09-05] store.day = Saturday morning (source: user)
- [2026-09-26] store.main = Safeway, because it is closer (source: user)
- [2026-09-26] store.day = Saturdays (source: user)
- [2026-10-12] store.main = Costco (source: user)
- [2026-09-05] store.loyalty = has a Safeway club card (source: user)
- [2026-09-14] store.budget = about 150 dollars a week (source: user)
- [2026-09-14] store.delivery = never uses grocery delivery (source: user)
## Home
- [2026-10-01] home.food = organic baby spinach (source: user)
- [2026-10-01] home.food = frozen blueberries for Arjun's breakfast (source: user)
- [2026-10-04] home.food = whole cantaloupe (source: user)
- [2026-10-06] home.food = baby spinach, organic (source: user)
- [2026-09-20] home.fridge_temp = set to 37 F (source: user)
- [2026-09-20] home.freezer = chest freezer in the garage (source: user)
## Recalls
- [2026-09-15] recall.returned = peanut butter jar, Salmonella recall (source: user)
- [2026-10-08] recall.returned = deli turkey to Safeway, Listeria recall (source: user)
- [2026-10-09] recall.returned = deli turkey because of Listeria (source: user)
- [2026-09-15] recall.checks = checks FDA.gov/recalls every Sunday (source: user)
- [2026-09-22] recall.receipts = keeps grocery receipts for 30 days (source: user)
## Preferences
- [2026-09-05] alert.channel = email (source: user)
- [2026-10-08] alert.channel = text message (source: user)
- [2026-09-05] pref.answer_style = short answers (source: user)
- [2026-09-05] pref.units = Fahrenheit (source: user)
## Project
- [2026-09-01] project.repo = github.com/PinalPawar/data260-7875 (source: user)
- [2026-09-01] project.port = 8675 (source: user)
- [2026-09-01] project.model = qwen3:1.7b through Ollama (source: user)
- [2026-09-01] project.database = MongoDB s7875_doc and MySQL s7875_rel (source: user)
