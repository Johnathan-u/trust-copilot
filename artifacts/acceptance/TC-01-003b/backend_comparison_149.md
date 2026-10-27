invalid pdf header: b'this '
EOF marker not found
EOF marker not found
| case | pymupdf(baseline) | pypdf | pdfplumber |
|---|---|---|---|
| multipage_blank_page | 8/8 | 8/8 | 8/8 |
| spans_and_offsets | 41/41 | 41/41 | 41/41 |
| two_column | 26/26 | 26/26 | 14/26 (LEFT-1 merged with another marker; LEFT-2 merged with another marker; LEFT-3 merged with another marker; LEFT-4 merged w) |
| two_column_stream_right_first | 26/26 | 26/26 | 14/26 (LEFT-1 merged with another marker; LEFT-2 merged with another marker; LEFT-3 merged with another marker; LEFT-4 merged w) |
| table_grid | 13/17 (row CTRL-ID not on one line in order; row T1C1-CC1.1 not on one line in order; row T2C1-CC2.1 not on one line in order; ) | 17/17 | 17/17 |
| questionnaire_two_pages | 9/9 | 9/9 | 9/9 |
| questionnaire_numbered | 3/3 | 3/3 | 3/3 |
| questionnaire_table_cells | 4/4 | 4/4 | 4/4 |
| latin1_punctuation | 2/2 | 2/2 | 2/2 |
| image_only_scan | 3/3 | 3/3 | 3/3 |
| vector_only_no_text | 2/2 | 2/2 | 2/2 |
| whitespace_only_text | 2/2 | 2/2 | 2/2 |
| corrupt_not_pdf | 1/1 | 1/1 | 1/1 |
| truncated_pdf | 1/1 | 1/1 | 1/1 |
| repo_fixture_security_policy | 2/2 | 2/2 | 2/2 |
| encrypted_owner_only_empty_user_pw | 1/1 | 1/1 | 1/1 |
| encrypted_user_password_required | 1/1 | 1/1 | 1/1 |
| **total** | **145/149** | **149/149** | **125/149** |
