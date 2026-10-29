"""Reviewed FAQ lifecycle and source ownership; lossless rollback archives.

Revision ID: tc17004_faq_review
Revises: bug018c_one_open_gap
"""

from alembic import op
import sqlalchemy as sa

revision = "tc17004_faq_review"
down_revision = "bug018c_one_open_gap"
branch_labels = None
depends_on = None

FIELDS = (
    "revision",
    "publication_state",
    "synthetic",
    "reviewed_by_user_id",
    "reviewed_at",
    "reviewed_revision",
    "reviewed_evidence_digest",
    "published_at",
    "published_revision",
)
FINGERPRINT = "md5(json_build_array(category, question, answer, framework_tags, is_default)::text)"


def upgrade():
    for name, typ in (
        ("revision", sa.Integer()),
        ("publication_state", sa.String(16)),
        ("synthetic", sa.Boolean()),
        ("reviewed_by_user_id", sa.Integer()),
        ("reviewed_at", sa.DateTime(timezone=True)),
        ("reviewed_revision", sa.Integer()),
        ("reviewed_evidence_digest", sa.String(64)),
        ("published_at", sa.DateTime(timezone=True)),
        ("published_revision", sa.Integer()),
    ):
        op.add_column("security_faq", sa.Column(name, typ, nullable=True))
    op.create_foreign_key(
        "fk_security_faq_reviewer",
        "security_faq",
        "users",
        ["reviewed_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_security_faq_revision", "security_faq", "revision IS NULL OR revision >= 1"
    )
    op.create_check_constraint(
        "ck_security_faq_publication_state",
        "security_faq",
        "publication_state IS NULL OR publication_state IN ('draft','approved','published','withdrawn')",
    )
    # Existing unbounded legacy content is not rewritten or certified. New writes are bounded.
    op.execute(
        "ALTER TABLE security_faq ADD CONSTRAINT ck_security_faq_content_bounds CHECK (char_length(question) <= 2000 AND char_length(answer) <= 20000) NOT VALID"
    )
    op.create_table(
        "security_faq_sources",
        sa.Column(
            "faq_id",
            sa.Integer(),
            sa.ForeignKey("security_faq.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "evidence_item_id",
            sa.Integer(),
            sa.ForeignKey("evidence_items.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    op.create_index(
        "ix_security_faq_sources_evidence_item_id", "security_faq_sources", ["evidence_item_id"]
    )
    op.create_table(
        "security_faq_revisions",
        sa.Column(
            "faq_id",
            sa.Integer(),
            sa.ForeignKey("security_faq.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("revision", sa.Integer(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Integer(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("question", sa.String(2000), nullable=False),
        sa.Column("answer", sa.String(20000), nullable=False),
        sa.Column("framework_tags", sa.String(512), nullable=True),
        sa.Column("source_evidence_ids_json", sa.String(512), nullable=False),
        sa.Column("synthetic", sa.Boolean(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("revision >= 1", name="ck_security_faq_history_revision"),
    )
    op.create_index(
        "ix_security_faq_revisions_workspace_id", "security_faq_revisions", ["workspace_id"]
    )
    # Restoring is guarded by identity, ownership and retained content; edits during a rollback
    # cannot inherit an older review. History remains a historical snapshot, never live approval.
    op.execute(f"""
    DO $$ BEGIN
      IF to_regclass('public.tc17004_faq_state_archive') IS NOT NULL THEN
        UPDATE security_faq f SET
          revision = CASE WHEN a.fingerprint = {FINGERPRINT.replace('category', 'f.category').replace('question', 'f.question').replace('answer', 'f.answer').replace('framework_tags', 'f.framework_tags').replace('is_default', 'f.is_default')} THEN a.revision ELSE COALESCE(a.revision,0)+1 END,
          publication_state = CASE WHEN a.fingerprint = {FINGERPRINT.replace('category', 'f.category').replace('question', 'f.question').replace('answer', 'f.answer').replace('framework_tags', 'f.framework_tags').replace('is_default', 'f.is_default')} THEN a.publication_state ELSE 'draft' END,
          synthetic = a.synthetic,
          reviewed_by_user_id = CASE WHEN a.fingerprint = {FINGERPRINT.replace('category', 'f.category').replace('question', 'f.question').replace('answer', 'f.answer').replace('framework_tags', 'f.framework_tags').replace('is_default', 'f.is_default')} AND EXISTS(SELECT 1 FROM users u WHERE u.id=a.reviewed_by_user_id) THEN a.reviewed_by_user_id END,
          reviewed_at = CASE WHEN a.fingerprint = {FINGERPRINT.replace('category', 'f.category').replace('question', 'f.question').replace('answer', 'f.answer').replace('framework_tags', 'f.framework_tags').replace('is_default', 'f.is_default')} THEN a.reviewed_at END,
          reviewed_revision = CASE WHEN a.fingerprint = {FINGERPRINT.replace('category', 'f.category').replace('question', 'f.question').replace('answer', 'f.answer').replace('framework_tags', 'f.framework_tags').replace('is_default', 'f.is_default')} THEN a.reviewed_revision END,
          reviewed_evidence_digest = CASE WHEN a.fingerprint = {FINGERPRINT.replace('category', 'f.category').replace('question', 'f.question').replace('answer', 'f.answer').replace('framework_tags', 'f.framework_tags').replace('is_default', 'f.is_default')} THEN a.reviewed_evidence_digest END,
          published_at = CASE WHEN a.fingerprint = {FINGERPRINT.replace('category', 'f.category').replace('question', 'f.question').replace('answer', 'f.answer').replace('framework_tags', 'f.framework_tags').replace('is_default', 'f.is_default')} THEN a.published_at END,
          published_revision = CASE WHEN a.fingerprint = {FINGERPRINT.replace('category', 'f.category').replace('question', 'f.question').replace('answer', 'f.answer').replace('framework_tags', 'f.framework_tags').replace('is_default', 'f.is_default')} THEN a.published_revision END
        FROM tc17004_faq_state_archive a WHERE f.id=a.id AND f.workspace_id=a.workspace_id AND a.revision IS NOT NULL AND char_length(f.question)<=2000 AND char_length(f.answer)<=20000;
        INSERT INTO security_faq_revisions SELECT a.* FROM tc17004_faq_history_archive a JOIN security_faq f ON f.id=a.faq_id AND f.workspace_id=a.workspace_id;
        INSERT INTO security_faq_sources SELECT a.* FROM tc17004_faq_source_archive a JOIN security_faq f ON f.id=a.faq_id JOIN evidence_items e ON e.id=a.evidence_item_id AND e.workspace_id=f.workspace_id;
        INSERT INTO security_faq_revisions (faq_id, revision, workspace_id, category, question, answer, framework_tags, source_evidence_ids_json, synthetic)
          SELECT f.id, f.revision, f.workspace_id, f.category, f.question, f.answer, f.framework_tags,
            COALESCE((SELECT json_agg(s.evidence_item_id ORDER BY s.evidence_item_id)::text FROM security_faq_sources s WHERE s.faq_id=f.id),'[]'), f.synthetic
          FROM security_faq f WHERE f.revision IS NOT NULL AND NOT EXISTS (SELECT 1 FROM security_faq_revisions h WHERE h.faq_id=f.id AND h.revision=f.revision);
        DROP TABLE tc17004_faq_history_archive, tc17004_faq_source_archive, tc17004_faq_state_archive;
      END IF;
    END $$;
    """)
    op.execute("""
    CREATE FUNCTION tc17004_check_faq_source() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE fw integer; ew integer;
    BEGIN
      SELECT workspace_id INTO fw FROM security_faq WHERE id=NEW.faq_id FOR UPDATE;
      SELECT workspace_id INTO ew FROM evidence_items WHERE id=NEW.evidence_item_id FOR SHARE;
      IF fw IS NULL OR ew IS NULL OR fw <> ew THEN
        RAISE EXCEPTION 'FAQ source must belong to the same workspace' USING ERRCODE='23514';
      END IF;
      IF (SELECT count(*) FROM security_faq_sources WHERE faq_id=NEW.faq_id AND (faq_id,evidence_item_id) <> (NEW.faq_id,NEW.evidence_item_id)) >= 20 THEN
        RAISE EXCEPTION 'Too many FAQ sources' USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER tc17004_faq_source_guard BEFORE INSERT OR UPDATE ON security_faq_sources FOR EACH ROW EXECUTE FUNCTION tc17004_check_faq_source();
    CREATE FUNCTION tc17004_check_parent_workspace() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.workspace_id IS DISTINCT FROM OLD.workspace_id THEN
        IF TG_TABLE_NAME='security_faq' THEN
          IF EXISTS(SELECT 1 FROM security_faq_sources s JOIN evidence_items e ON e.id=s.evidence_item_id WHERE s.faq_id=OLD.id AND e.workspace_id <> NEW.workspace_id)
             OR EXISTS(SELECT 1 FROM security_faq_revisions h WHERE h.faq_id=OLD.id AND h.workspace_id <> NEW.workspace_id) THEN
            RAISE EXCEPTION 'FAQ source workspace change blocked' USING ERRCODE='23514';
          END IF;
        ELSE
          IF EXISTS(SELECT 1 FROM security_faq_sources s JOIN security_faq f ON f.id=s.faq_id WHERE s.evidence_item_id=OLD.id AND f.workspace_id <> NEW.workspace_id) THEN
            RAISE EXCEPTION 'FAQ source workspace change blocked' USING ERRCODE='23514';
          END IF;
        END IF;
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER tc17004_faq_parent_guard BEFORE UPDATE OF workspace_id ON security_faq FOR EACH ROW EXECUTE FUNCTION tc17004_check_parent_workspace();
    CREATE TRIGGER tc17004_evidence_parent_guard BEFORE UPDATE OF workspace_id ON evidence_items FOR EACH ROW EXECUTE FUNCTION tc17004_check_parent_workspace();
    CREATE FUNCTION tc17004_check_faq_history() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE fw integer;
    BEGIN
      SELECT workspace_id INTO fw FROM security_faq WHERE id=NEW.faq_id FOR SHARE;
      IF fw IS NULL OR fw <> NEW.workspace_id THEN
        RAISE EXCEPTION 'FAQ revision must belong to the same workspace' USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER tc17004_faq_history_guard BEFORE INSERT OR UPDATE ON security_faq_revisions FOR EACH ROW EXECUTE FUNCTION tc17004_check_faq_history();
    """)


def downgrade():
    op.execute(f"""
    CREATE TABLE tc17004_faq_state_archive AS SELECT id, workspace_id, CAST({FINGERPRINT} AS varchar(32)) AS fingerprint, {', '.join(FIELDS)} FROM security_faq;
    CREATE TABLE tc17004_faq_history_archive AS TABLE security_faq_revisions;
    CREATE TABLE tc17004_faq_source_archive AS TABLE security_faq_sources;
    DROP TRIGGER tc17004_faq_history_guard ON security_faq_revisions;
    DROP TRIGGER tc17004_evidence_parent_guard ON evidence_items;
    DROP TRIGGER tc17004_faq_parent_guard ON security_faq;
    DROP TRIGGER tc17004_faq_source_guard ON security_faq_sources;
    DROP FUNCTION tc17004_check_parent_workspace();
    DROP FUNCTION tc17004_check_faq_source();
    DROP FUNCTION tc17004_check_faq_history();
    """)
    op.drop_table("security_faq_sources")
    op.drop_table("security_faq_revisions")
    for name in (
        "ck_security_faq_content_bounds",
        "ck_security_faq_publication_state",
        "ck_security_faq_revision",
    ):
        op.drop_constraint(name, "security_faq", type_="check")
    op.drop_constraint("fk_security_faq_reviewer", "security_faq", type_="foreignkey")
    for field in reversed(FIELDS):
        op.drop_column("security_faq", field)
