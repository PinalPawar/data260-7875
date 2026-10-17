# MEMORY.md - durable facts (file-based memory)
<!-- last_consolidated: 2026-10-16T07:03:12+00:00 -->
<!-- format: - [YYYY-MM-DD] key = value (source: user|doctor|dream|assistant) -->
## Facts
- [2026-10-08] alert.channel = text message (source: user)
- [2026-09-20] allergy.son = egg allergy (source: user) (merged 2; under review)
- [2026-10-03] allergy.user = Allergic to peanuts. (source: user) (merged 3)
- [2026-10-02] family.sister = Meera, lives in Fresno, pregnant (source: user)
- [2026-10-05] family.son_age = 4 years old (source: user)
- [2026-09-02] family.son_name = Arjun (source: user)
- [2026-09-18] family.son_school = preschool on weekdays (source: user)
- [2026-09-12] health.user = no other health conditions mentioned (source: user)
- [2026-10-06] home.food = frozen blueberries for Arjun's breakfast; whole cantaloupe; baby spinach, organic (source: user) (merged 4)
- [2026-09-20] home.freezer = chest freezer in the garage (source: user)
- [2026-09-20] home.fridge_temp = set to 37 F (source: user)
- [2026-09-05] pref.answer_style = short answers (source: user)
- [2026-09-12] pref.diet = avoids very spicy food (source: user)
- [2026-09-05] pref.units = Fahrenheit (source: user)
- [2026-09-01] project.database = MongoDB s7875_doc and MySQL s7875_rel (source: user)
- [2026-09-01] project.model = qwen3:1.7b through Ollama (source: user)
- [2026-09-01] project.port = 8675 (source: user)
- [2026-09-01] project.repo = github.com/PinalPawar/data260-7875 (source: user)
- [2026-09-15] recall.checks = checks FDA.gov/recalls every Sunday (source: user)
- [2026-09-22] recall.receipts = keeps grocery receipts for 30 days (source: user)
- [2026-10-09] recall.returned = peanut butter jar, Salmonella recall; deli turkey because of Listeria (source: user) (merged 3)
- [2026-09-14] store.budget = about 150 dollars a week (source: user)
- [2026-09-26] store.day = Saturdays (source: user) (merged 2)
- [2026-09-14] store.delivery = never uses grocery delivery (source: user)
- [2026-09-05] store.loyalty = has a Safeway club card (source: user)
- [2026-10-12] store.main = Costco (source: user)
- [2026-09-02] user.city = San Jose, California (source: user) (under review)
- [2026-09-02] user.household = family of three (source: user)
- [2026-09-02] user.language = English (source: user)
- [2026-10-01] user.name = Pinal Pawar (source: user) (merged 2)
## Resolved contradictions
- family.son_age: kept "4 years old" (2026-10-05, user); replaced "3 years old" (2026-09-02, user) - rule: newest wins [2026-10-16]
- store.main: kept "Costco" (2026-10-12, user); replaced "Safeway, because it is closer" (2026-09-26, user) - rule: newest wins [2026-10-16]
- alert.channel: kept "text message" (2026-10-08, user); replaced "email" (2026-09-05, user) - rule: newest wins [2026-10-16]
## Needs review
- user.city: newest-wins would keep "Fresno" (2026-10-13, dream) - LIKELY INCORRECT because the replaced value came from a stronger source; kept "San Jose, California" (2026-09-02, user) active; conflicting: "Fresno" (2026-10-13, dream); confirm with the user [2026-10-16]
- allergy.son: newest-wins would keep "no food allergies" (2026-10-14, assistant) - LIKELY INCORRECT because the replaced value came from a stronger source; kept "egg allergy" (2026-09-20, user) active; conflicting: "no food allergies" (2026-10-14, assistant); confirm with the user [2026-10-16]
