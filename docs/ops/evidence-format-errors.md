# Evidence format errors

Operator notes for evidence that cannot be indexed (TC-08-002). No new setting.
The stored text is a fixed reason and a next action. It does not include the
file bytes, the storage key, or a server path. The server log records the
exception class name only.

The document list returns that text as `index_error`. The index job returns
the same text as `error`, with `error_code` `bad_input` and `retryable` false.
The documents page shows `index_error` when the row status is `failed`. Status
is `failed`. It is not `indexed`.

## Reason codes

| Code | When | Stored text |
|---|---|---|
| `pdf_no_text` | PDF with no text layer (a scan). There is no OCR. | This PDF has no text layer; OCR isn't supported. Upload a text-based PDF, DOCX or XLSX instead. |
| `pdf_encrypted` | PDF that needs a password. | PDF is encrypted or corrupt: it is password-protected. Upload an unencrypted copy. |
| `pdf_unreadable` | PDF that is not a readable PDF. | PDF is encrypted or corrupt: the file could not be read. Re-export it and upload it again. |
| `workbook_corrupt` | `.xlsx` that cannot be opened, or whose every sheet fails to read. | Workbook is corrupt or unreadable. Re-export it as an .xlsx file and upload it again. |
| `legacy_office` | `.doc` or `.xls`, whether or not python-docx or another parser library is installed. | Legacy .doc and .xls files are not supported. Save the file as .docx or .xlsx and upload that copy. |
| `docx_unreadable` | `.docx` package the reader cannot open. | This Word file could not be read. Re-save it as a .docx file and upload it again. |
| `empty_evidence` | A file the parser opens and that has no text, including an empty or whitespace `.docx`, `.xlsx`, `.txt`, or `.csv`. | This file has no extractable text. Upload a file that contains text. |

The PDF rows are the messages from TC-01-003a. The other rows are TC-08-002.
`code` on the office and empty errors is the value in the first column. The
PDF failures use the same stored-text shape and the job code `bad_input`.

A readable `.xlsx`, `.docx`, or `.txt` that contains text is still indexed.
An empty readable workbook is `empty_evidence`, not `workbook_corrupt`.

`.csv` is not an accepted upload extension, so the upload route refuses it
before it creates a document. A `.csv` or any other unread extension that
already reaches indexing is not indexed. The stored message is
`empty_evidence`, and it does not quote the file.

These failures are terminal. Retrying the job does not change the file. Ask
the user to upload the copy named in the next action.

No migration is involved. Do not change a table to make a failed document
indexed.
