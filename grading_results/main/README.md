# Grades for the main run

These are the grades for every main run answer, one line per answer, written by scripts/grading/grade_study.py. The live files are not committed, so I commit compressed copies.

- graded.jsonl.gz holds what the judges produced, before my review. 3402 lines: 3150 main runs and 252 side check runs. The sha256 of the uncompressed file is fda0a131e12b91156262567de1835cda8074557574a517ddf992ef71b10c068f.
- final.jsonl.gz holds the same grades with my tiebreaker review applied. These are the grades the analysis uses. 3402 lines, sha256 of the uncompressed file 9867e199d27cf01a98b49124fcd74b0dd537d4eea84b8c6a1906c55d6192a30a.
- tiebreak_review.blank_backup.md is the review sheet as the grader wrote it, and tiebreak_review.md is the same sheet with my calls. review_map.json links its items to the runs.
- hand/ holds the blind sample of 20 answers and the stand-in check.

The two grade files differ only where my review changed 35 values in 29 answers, in what follows from those values (item scores in 15 answers, labels in 18, grounding in 7 and pass results in 3), and in a reviewed flag on the 73 answers I reviewed. I committed both before running any of the planned statistics.

How grading went, and the checks around it, is in docs/study_log.md.
