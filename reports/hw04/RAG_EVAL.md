# HW4 Part 4 - RAG Evaluation

Model: Ollama `qwen3:1.7b` | Chunking: TokenTextSplitter(chunk_size=500, chunk_overlap=50) | Vector store: LlamaIndex in-memory VectorStoreIndex | basic_rag k=3 | context_engineered: retrieve k=5 then filter (relevance floor 0.35, dup threshold 0.6) down to <= 3

## k-sweep summary

- Q1: top-1 score k=1:0.7047 k=3:0.7047 k=5:0.7047; irrelevant chunk first appears at rank None within k=5
- Q2: top-1 score k=1:0.7649 k=3:0.7649 k=5:0.7649; irrelevant chunk first appears at rank None within k=5
- Q3: top-1 score k=1:0.7049 k=3:0.7049 k=5:0.7049; irrelevant chunk first appears at rank None within k=5
- Q4: top-1 score k=1:0.6339 k=3:0.6339 k=5:0.6339; irrelevant chunk first appears at rank None within k=5
- Q5: top-1 score k=1:0.6282 k=3:0.6282 k=5:0.6282; irrelevant chunk first appears at rank None within k=5
- Q6: top-1 score k=1:0.1506 k=3:0.1506 k=5:0.1506; irrelevant chunk first appears at rank 1 within k=5

## Evaluation table

| Q | Category | Config | Refused? | Correct retrieval | Sources used |
|---|---|---|---|---|---|
| Q1 | one_chunk | no_rag | False | n/a | (none, no_rag) |
| Q1 | one_chunk | basic_rag | False | True | fda_outbreak_ecoli_spinach_2021.txt, fda_outbreak_ecoli_spinach_2021.txt, fda_outbreak_ecoli_spinach_2021.txt |
| Q1 | one_chunk | context_engineered | False | True | fda_outbreak_ecoli_spinach_2021.txt, fda_outbreak_ecoli_spinach_2021.txt, fda_outbreak_ecoli_spinach_2021.txt |
| Q2 | two_chunks | no_rag | False | n/a | (none, no_rag) |
| Q2 | two_chunks | basic_rag | False | True | fda_recall_byheart_infant_formula_2025.txt, cdc_outbreak_infant_botulism_formula_2026.txt, fda_recall_nara_organics_infant_formula_2026.txt |
| Q2 | two_chunks | context_engineered | False | True | fda_recall_byheart_infant_formula_2025.txt, cdc_outbreak_infant_botulism_formula_2026.txt, fda_recall_nara_organics_infant_formula_2026.txt |
| Q3 | similar_across_docs | no_rag | False | n/a | (none, no_rag) |
| Q3 | similar_across_docs | basic_rag | False | True | cdc_about_listeria.txt, fsis_chicken_caesar_wrap_listeria.txt, cdc_outbreak_deli_meats_listeria.txt |
| Q3 | similar_across_docs | context_engineered | False | True | cdc_about_listeria.txt, fsis_chicken_caesar_wrap_listeria.txt, cdc_outbreak_deli_meats_listeria.txt |
| Q4 | ambiguous | no_rag | False | n/a | (none, no_rag) |
| Q4 | ambiguous | basic_rag | False | n/a | fda_outbreak_salmonella_cantaloupes_2023.txt, openfda_enforcement_bulk_records.txt, openfda_enforcement_bulk_records.txt |
| Q4 | ambiguous | context_engineered | True | n/a | fda_outbreak_salmonella_cantaloupes_2023.txt, openfda_enforcement_bulk_records.txt, openfda_enforcement_bulk_records.txt |
| Q5 | not_in_documents | no_rag | False | n/a | (none, no_rag) |
| Q5 | not_in_documents | basic_rag | False | True | fda_recall_peanut_butter_smucker_2022.txt, openfda_enforcement_bulk_records.txt, fda_recall_peanut_butter_smucker_2022.txt |
| Q5 | not_in_documents | context_engineered | True | True | fda_recall_peanut_butter_smucker_2022.txt, openfda_enforcement_bulk_records.txt, fda_recall_peanut_butter_smucker_2022.txt |
| Q6 | unrelated | no_rag | False | n/a | (none, no_rag) |
| Q6 | unrelated | basic_rag | False | True | openfda_enforcement_bulk_records.txt, fda_recall_peanut_butter_smucker_2022.txt, fda_outbreaks_investigations_index.txt |
| Q6 | unrelated | context_engineered | True | True | (none, no_rag) |
