-- Synthetic rows for the audited migration snapshot.
-- Schema revision 075, the alembic head at
-- c20f949161ac12a619b396d30904448ffd74d532.
-- No customer content. The password_hash value is a placeholder, not a credential.

SELECT setval(
    pg_get_serial_sequence('workspaces', 'id'),
    (SELECT COALESCE(MAX(id), 1) FROM workspaces)
);

INSERT INTO workspaces (name, slug)
VALUES ('Synthetic Audited Workspace', 'synthetic-audited');

INSERT INTO users (email, password_hash, display_name)
VALUES ('synthetic-audited@example.com', 'synthetic-hash', 'Synthetic Auditor');

INSERT INTO workspace_members (workspace_id, user_id, role)
SELECT w.id, u.id, 'owner'
FROM workspaces w
JOIN users u ON u.email = 'synthetic-audited@example.com'
WHERE w.slug = 'synthetic-audited';

INSERT INTO documents (workspace_id, storage_key, filename, content_type, status)
SELECT id, 'synthetic/audited-snapshot/policy.pdf', 'policy.pdf', 'application/pdf', 'indexed'
FROM workspaces
WHERE slug = 'synthetic-audited';

INSERT INTO questionnaires (workspace_id, document_id, filename, storage_key, status)
SELECT w.id, d.id, 'questionnaire.xlsx', 'synthetic/audited-snapshot/questionnaire.xlsx', 'parsed'
FROM workspaces w
JOIN documents d
  ON d.workspace_id = w.id
 AND d.storage_key = 'synthetic/audited-snapshot/policy.pdf'
WHERE w.slug = 'synthetic-audited';

INSERT INTO questions (questionnaire_id, text, section, source_location)
SELECT qn.id,
       'How often are access reviews completed?',
       'Access',
       '{"sheet":"Controls","row":12,"col":2}'
FROM questionnaires qn
WHERE qn.storage_key = 'synthetic/audited-snapshot/questionnaire.xlsx';

INSERT INTO answers (question_id, text, status)
SELECT q.id, 'Access reviews run each quarter.', 'approved'
FROM questions q
WHERE q.text = 'How often are access reviews completed?';
