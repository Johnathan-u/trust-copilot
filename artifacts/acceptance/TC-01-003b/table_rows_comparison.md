| case | pymupdf(old baseline) | pdfplumber | pypdf-plain (PR #11) | branch (TC-01-003b) |
|---|---|---|---|---|
| questionnaire_table_cells | 2/2 | 0/2 (+2 wrong) ✗ | 0/2 (+2 wrong) ✗ | 2/2 |
| table_rows_one_bt_yes_no_na | 3/3 | 1/3 (+2 wrong) ✗ | 1/3 (+2 wrong) ✗ | 3/3 |
| table_rows_tj_kerning | 3/3 | 1/3 (+2 wrong) ✗ | 1/3 (+2 wrong) ✗ | 3/3 |
| table_rows_answers_first_in_stream | 2/2 | 0/2 (+2 wrong) ✗ | 0/2 (+2 wrong) ✗ | 2/2 |
| table_rows_prefilled_answers | 2/2 | 0/2 (+2 wrong) ✗ | 0/2 (+2 wrong) ✗ | 2/2 |
| table_rows_two_question_columns | 4/4 | 0/4 (+2 wrong) ✗ | 0/4 (+2 wrong) ✗ | 4/4 |
| table_rows_numbered | 2/2 | 0/2 ✗ | 0/2 ✗ | 2/2 |
| table_rows_guards_not_split | 0/4 (+1 wrong) ✗ | 4/4 | 4/4 | 4/4 |
| table_rows_two_column_blocks | 4/4 | 0/4 (+2 wrong) ✗ | 4/4 | 4/4 |
| **total** | **22/26** (+1 wrong) | **6/26** (+14 wrong) | **10/26** (+12 wrong) | **26/26** (+0 wrong) |

Per case: expected questions found exactly (text, page, section) / expected;
'wrong' counts extracted questions not in the expected list; ✗ marks any
difference from the expected list, including order.

```json
{
 "questionnaire_table_cells": {
  "pymupdf(old baseline)": [
   "do you encrypt backups at rest",
   "is mfa required for remote access"
  ],
  "pdfplumber": [
   "do you encrypt backups at rest? yes no",
   "is mfa required for remote access? yes no"
  ],
  "pypdf-plain (PR #11)": [
   "do you encrypt backups at rest? yes no",
   "is mfa required for remote access? yes no"
  ],
  "branch (TC-01-003b)": [
   "do you encrypt backups at rest",
   "is mfa required for remote access"
  ]
 },
 "table_rows_one_bt_yes_no_na": {
  "pymupdf(old baseline)": [
   "do you encrypt backups at rest",
   "are encryption keys rotated at least annually",
   "describe how backup restores are tested"
  ],
  "pdfplumber": [
   "do you encrypt backups at rest? yes no n/a",
   "are encryption keys rotated at least annually? [x] [ ] [ ]",
   "describe how backup restores are tested"
  ],
  "pypdf-plain (PR #11)": [
   "do you encrypt backups at rest? yes no n/a",
   "are encryption keys rotated at least annually? [x] [ ] [ ]",
   "describe how backup restores are tested"
  ],
  "branch (TC-01-003b)": [
   "do you encrypt backups at rest",
   "are encryption keys rotated at least annually",
   "describe how backup restores are tested"
  ]
 },
 "table_rows_tj_kerning": {
  "pymupdf(old baseline)": [
   "is mfa required for remote access",
   "is sso enforced for all staff",
   "do you log administrator actions"
  ],
  "pdfplumber": [
   "is mfa required for remote access? yes no",
   "is sso enforced for all staff? yes no",
   "do you log administrator actions"
  ],
  "pypdf-plain (PR #11)": [
   "is mfa required for remote access? yes no",
   "is sso enforced for all staff? yes no",
   "do you log administrator actions"
  ],
  "branch (TC-01-003b)": [
   "is mfa required for remote access",
   "is sso enforced for all staff",
   "do you log administrator actions"
  ]
 },
 "table_rows_answers_first_in_stream": {
  "pymupdf(old baseline)": [
   "are audit logs retained for at least one year",
   "is log access restricted to the security team"
  ],
  "pdfplumber": [
   "are audit logs retained for at least one year? yes no",
   "is log access restricted to the security team? yes no"
  ],
  "pypdf-plain (PR #11)": [
   "yes noare audit logs retained for at least one year",
   "yes nois log access restricted to the security team"
  ],
  "branch (TC-01-003b)": [
   "are audit logs retained for at least one year",
   "is log access restricted to the security team"
  ]
 },
 "table_rows_prefilled_answers": {
  "pymupdf(old baseline)": [
   "is customer data encrypted in transit",
   "how are vendor risks assessed"
  ],
  "pdfplumber": [
   "is customer data encrypted in transit? yes - tls 1.2 or later on all endpoints",
   "how are vendor risks assessed? annual review against the vendor policy"
  ],
  "pypdf-plain (PR #11)": [
   "is customer data encrypted in transit? yes - tls 1.2 or later on all endpoints",
   "how are vendor risks assessed? annual review against the vendor policy"
  ],
  "branch (TC-01-003b)": [
   "is customer data encrypted in transit",
   "how are vendor risks assessed"
  ]
 },
 "table_rows_two_question_columns": {
  "pymupdf(old baseline)": [
   "are data centre visitors escorted",
   "do badges expire after 12 months",
   "is cctv footage kept for 90 days",
   "are server racks locked"
  ],
  "pdfplumber": [
   "are data centre visitors escorted? do badges expire after 12 months",
   "is cctv footage kept for 90 days? are server racks locked"
  ],
  "pypdf-plain (PR #11)": [
   "are data centre visitors escorted? do badges expire after 12 months",
   "is cctv footage kept for 90 days? are server racks locked"
  ],
  "branch (TC-01-003b)": [
   "are data centre visitors escorted",
   "do badges expire after 12 months",
   "is cctv footage kept for 90 days",
   "are server racks locked"
  ]
 },
 "table_rows_numbered": {
  "pymupdf(old baseline)": [
   "do you maintain an asset inventory",
   "are assets assigned an owner"
  ],
  "pdfplumber": [],
  "pypdf-plain (PR #11)": [],
  "branch (TC-01-003b)": [
   "do you maintain an asset inventory",
   "are assets assigned an owner"
  ]
 },
 "table_rows_guards_not_split": {
  "pymupdf(old baseline)": [
   "describe your incident response process"
  ],
  "pdfplumber": [
   "is the backup encryption key rotated annually",
   "describe your incident response process see ir-1",
   "backups tested (yes/no)",
   "restores logged (yes/no)"
  ],
  "pypdf-plain (PR #11)": [
   "is the backup encryption key rotated annually",
   "describe your incident response process see ir-1",
   "backups tested (yes/no)",
   "restores logged (yes/no)"
  ],
  "branch (TC-01-003b)": [
   "is the backup encryption key rotated annually",
   "describe your incident response process see ir-1",
   "backups tested (yes/no)",
   "restores logged (yes/no)"
  ]
 },
 "table_rows_two_column_blocks": {
  "pymupdf(old baseline)": [
   "are firewalls reviewed quarterly",
   "is network traffic segmented",
   "do staff receive security training",
   "are background checks performed"
  ],
  "pdfplumber": [
   "are firewalls reviewed quarterly? do staff receive security training",
   "is network traffic segmented? are background checks performed"
  ],
  "pypdf-plain (PR #11)": [
   "are firewalls reviewed quarterly",
   "is network traffic segmented",
   "do staff receive security training",
   "are background checks performed"
  ],
  "branch (TC-01-003b)": [
   "are firewalls reviewed quarterly",
   "is network traffic segmented",
   "do staff receive security training",
   "are background checks performed"
  ]
 }
}
```
