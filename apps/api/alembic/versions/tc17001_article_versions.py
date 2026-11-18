"""Immutable trust-article versions and versioned policy acknowledgments.

SCHEMA CHANGE. Review this migration before it is applied.

Publishing stores a row in trust_article_versions. trust_articles.published_version_id
points at the approved row and is not a foreign key, so deleting an article can
cascade to its versions without a cycle. policy_acknowledgments gain
article_version_id, workspace_id, and revoked_at. The old unique index on
(user_id, trust_article_id) becomes a unique constraint on
(user_id, article_version_id), which is what lets a new version be acknowledged
while the previous acknowledgment stays on file.

Existing published articles that belong to a workspace are copied into version 1.
Acknowledgments of those articles are bound to that version. An acknowledgment
with nothing viewable to bind is marked revoked.

A database trigger rejects UPDATE of a version row. DELETE still cascades from
the article.

Downgrade copies versions, publication pointers, and acknowledgment bindings
into archive tables with no foreign keys, then restores the previous
policy_acknowledgments shape. Extra acknowledgment rows that would break the
old unique index are archived in full and removed. Re-upgrade puts them back
when the user, article, and version still exist. Archive rows whose parents
are gone stay in the archive.

The revision id is 24 characters and fits alembic_version.version_num
(varchar(32)). down_revision is the single alembic head on master when this
file is parented. This revision does not import the application package.

Revision ID: tc17001_article_versions
Revises: tc04005a_member_revoked_at
"""

import sqlalchemy as sa
from alembic import op

revision = "tc17001_article_versions"
down_revision = "tc04005a_member_revoked_at"
branch_labels = None
depends_on = None

_VERSIONS = "trust_article_versions"
_VERSION_ARCHIVE = "tc17001_version_archive"
_PUB_ARCHIVE = "tc17001_article_pub_archive"
_ACK_ARCHIVE = "tc17001_ack_binding_archive"
_ACK_ROWS = "tc17001_ack_row_archive"
_TRIGGER = "trg_tc17001_version_immutable"
_FUNCTION = "tc17001_version_immutable"


def _setval(table: str) -> None:
    op.execute(
        sa.text(
            f"""
            SELECT setval(
                pg_get_serial_sequence('{table}', 'id'),
                GREATEST(COALESCE((SELECT MAX(id) FROM {table}), 1), 1),
                (SELECT MAX(id) IS NOT NULL FROM {table})
            )
            """
        )
    )


def upgrade() -> None:
    op.create_table(
        _VERSIONS,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "trust_article_id",
            sa.Integer(),
            sa.ForeignKey("trust_articles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            sa.Integer(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(128), nullable=False),
        sa.Column("category", sa.String(64), nullable=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("is_policy", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "trust_article_id",
            "version_number",
            name="uq_trust_article_versions_article_number",
        ),
        sa.CheckConstraint("version_number >= 1", name="ck_trust_article_versions_number"),
    )
    op.create_index(
        "ix_trust_article_versions_trust_article_id", _VERSIONS, ["trust_article_id"]
    )
    op.create_index("ix_trust_article_versions_workspace_id", _VERSIONS, ["workspace_id"])
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {_FUNCTION}() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'trust_article_versions rows are immutable';
        END
        $$;
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {_TRIGGER}
        BEFORE UPDATE ON {_VERSIONS}
        FOR EACH ROW EXECUTE FUNCTION {_FUNCTION}();
        """
    )
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table(_VERSION_ARCHIVE):
        op.execute(
            sa.text(f"""
            INSERT INTO {_VERSIONS} (
                id, trust_article_id, workspace_id, version_number, slug, category,
                title, content, is_policy, created_at
            )
            SELECT a.id, a.trust_article_id, a.workspace_id, a.version_number, a.slug,
                   a.category, a.title, a.content, a.is_policy, a.created_at
            FROM {_VERSION_ARCHIVE} a
            JOIN trust_articles t ON t.id = a.trust_article_id
            JOIN workspaces w ON w.id = a.workspace_id
            ON CONFLICT (id) DO NOTHING
            """)
        )
        _setval(_VERSIONS)
        op.execute(
            sa.text(f"""
            DELETE FROM {_VERSION_ARCHIVE} a
            USING {_VERSIONS} v
            WHERE v.id = a.id
            """)
        )
    op.add_column(
        "trust_articles",
        sa.Column("published_version_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_trust_articles_published_version_id",
        "trust_articles",
        ["published_version_id"],
    )
    if inspector.has_table(_PUB_ARCHIVE):
        op.execute(
            sa.text(f"""
            UPDATE trust_articles t
            SET published_version_id = a.published_version_id
            FROM {_PUB_ARCHIVE} a
            JOIN {_VERSIONS} v ON v.id = a.published_version_id
            WHERE t.id = a.trust_article_id
            """)
        )
        op.execute(
            sa.text(f"""
            DELETE FROM {_PUB_ARCHIVE} a
            USING trust_articles t
            WHERE t.id = a.trust_article_id
              AND t.published_version_id IS NOT DISTINCT FROM a.published_version_id
            """)
        )
    op.execute(
        sa.text(f"""
        INSERT INTO {_VERSIONS} (
            trust_article_id, workspace_id, version_number, slug, category,
            title, content, is_policy, created_at
        )
        SELECT t.id, t.workspace_id, 1, t.slug, t.category, t.title,
               COALESCE(t.content, ''), COALESCE(t.is_policy, false),
               COALESCE(t.updated_at, t.created_at, now())
        FROM trust_articles t
        WHERE t.published = 1
          AND t.workspace_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM {_VERSIONS} v WHERE v.trust_article_id = t.id
          )
        """)
    )
    op.execute(
        sa.text(f"""
        UPDATE trust_articles t
        SET published_version_id = v.id
        FROM {_VERSIONS} v
        WHERE v.trust_article_id = t.id
          AND t.published = 1
          AND t.published_version_id IS NULL
          AND v.version_number = (
              SELECT MIN(version_number) FROM {_VERSIONS}
              WHERE trust_article_id = t.id
          )
        """)
    )
    op.add_column(
        "policy_acknowledgments",
        sa.Column("article_version_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "policy_acknowledgments",
        sa.Column("workspace_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "policy_acknowledgments",
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_policy_acknowledgments_article_version_id",
        "policy_acknowledgments",
        ["article_version_id"],
    )
    op.create_index(
        "ix_policy_acknowledgments_workspace_id",
        "policy_acknowledgments",
        ["workspace_id"],
    )
    op.create_foreign_key(
        "fk_policy_ack_version",
        "policy_acknowledgments",
        _VERSIONS,
        ["article_version_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_policy_ack_workspace",
        "policy_acknowledgments",
        "workspaces",
        ["workspace_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_index("ix_policy_ack_user_article", table_name="policy_acknowledgments")
    if inspector.has_table(_ACK_ARCHIVE):
        op.execute(
            sa.text(f"""
            UPDATE policy_acknowledgments p
            SET article_version_id = a.article_version_id,
                workspace_id = a.workspace_id,
                revoked_at = a.revoked_at
            FROM {_ACK_ARCHIVE} a
            JOIN {_VERSIONS} v ON v.id = a.article_version_id
            WHERE p.id = a.acknowledgment_id
            """)
        )
        op.execute(
            sa.text(f"""
            DELETE FROM {_ACK_ARCHIVE} a
            USING policy_acknowledgments p
            WHERE p.id = a.acknowledgment_id
              AND p.article_version_id IS NOT DISTINCT FROM a.article_version_id
            """)
        )
    if inspector.has_table(_ACK_ROWS):
        op.execute(
            sa.text(f"""
            INSERT INTO policy_acknowledgments (
                id, user_id, trust_article_id, acknowledged_at, created_at,
                article_version_id, workspace_id, revoked_at
            )
            SELECT a.id, a.user_id, a.trust_article_id, a.acknowledged_at, a.created_at,
                   CASE WHEN v.id IS NOT NULL THEN a.article_version_id END,
                   CASE WHEN w.id IS NOT NULL THEN a.workspace_id END,
                   a.revoked_at
            FROM {_ACK_ROWS} a
            JOIN users u ON u.id = a.user_id
            JOIN trust_articles t ON t.id = a.trust_article_id
            LEFT JOIN {_VERSIONS} v ON v.id = a.article_version_id
            LEFT JOIN workspaces w ON w.id = a.workspace_id
            ON CONFLICT (id) DO NOTHING
            """)
        )
        _setval("policy_acknowledgments")
        op.execute(
            sa.text(f"""
            DELETE FROM {_ACK_ROWS} a
            USING policy_acknowledgments p
            WHERE p.id = a.id
            """)
        )
        op.execute(
            sa.text("""
            UPDATE policy_acknowledgments p
            SET article_version_id = t.published_version_id,
                workspace_id = t.workspace_id
            FROM trust_articles t
            WHERE p.trust_article_id = t.id
              AND p.article_version_id IS NULL
              AND t.published = 1
              AND t.published_version_id IS NOT NULL
            """)
        )
    op.execute(
        sa.text("""
        UPDATE policy_acknowledgments
        SET revoked_at = now()
        WHERE article_version_id IS NULL
          AND revoked_at IS NULL
        """)
    )
    op.create_unique_constraint(
        "uq_policy_ack_user_version",
        "policy_acknowledgments",
        ["user_id", "article_version_id"],
    )
    for archive in (_VERSION_ARCHIVE, _PUB_ARCHIVE, _ACK_ARCHIVE, _ACK_ROWS):
        if inspector.has_table(archive):
            op.execute(
                sa.text(f"""
                DO $$
                BEGIN
                    IF to_regclass('public.{archive}') IS NOT NULL
                       AND NOT EXISTS (SELECT 1 FROM {archive}) THEN
                        DROP TABLE {archive};
                    END IF;
                END $$
                """)
            )


def downgrade() -> None:
    op.execute(
        sa.text(f"""
        CREATE TABLE IF NOT EXISTS {_VERSION_ARCHIVE} (
            id integer PRIMARY KEY,
            trust_article_id integer NOT NULL,
            workspace_id integer NOT NULL,
            version_number integer NOT NULL,
            slug varchar(128) NOT NULL,
            category varchar(64),
            title varchar(255) NOT NULL,
            content text NOT NULL,
            is_policy boolean NOT NULL,
            created_at timestamp NOT NULL,
            archived_at timestamp NOT NULL DEFAULT now()
        )
        """)
    )
    op.execute(
        sa.text(f"""
        INSERT INTO {_VERSION_ARCHIVE} (
            id, trust_article_id, workspace_id, version_number, slug, category,
            title, content, is_policy, created_at
        )
        SELECT id, trust_article_id, workspace_id, version_number, slug, category,
               title, content, is_policy, created_at
        FROM {_VERSIONS}
        ON CONFLICT (id) DO UPDATE SET
            trust_article_id = EXCLUDED.trust_article_id,
            workspace_id = EXCLUDED.workspace_id,
            version_number = EXCLUDED.version_number,
            slug = EXCLUDED.slug,
            category = EXCLUDED.category,
            title = EXCLUDED.title,
            content = EXCLUDED.content,
            is_policy = EXCLUDED.is_policy,
            created_at = EXCLUDED.created_at,
            archived_at = now()
        """)
    )
    op.execute(
        sa.text(f"""
        CREATE TABLE IF NOT EXISTS {_PUB_ARCHIVE} (
            trust_article_id integer PRIMARY KEY,
            published_version_id integer,
            archived_at timestamp NOT NULL DEFAULT now()
        )
        """)
    )
    op.execute(
        sa.text(f"""
        INSERT INTO {_PUB_ARCHIVE} (trust_article_id, published_version_id)
        SELECT id, published_version_id
        FROM trust_articles
        WHERE published_version_id IS NOT NULL
        ON CONFLICT (trust_article_id) DO UPDATE SET
            published_version_id = EXCLUDED.published_version_id,
            archived_at = now()
        """)
    )
    op.execute(
        sa.text(f"""
        CREATE TABLE IF NOT EXISTS {_ACK_ARCHIVE} (
            acknowledgment_id integer PRIMARY KEY,
            article_version_id integer,
            workspace_id integer,
            revoked_at timestamp,
            archived_at timestamp NOT NULL DEFAULT now()
        )
        """)
    )
    op.execute(
        sa.text(f"""
        INSERT INTO {_ACK_ARCHIVE} (
            acknowledgment_id, article_version_id, workspace_id, revoked_at
        )
        SELECT id, article_version_id, workspace_id, revoked_at
        FROM policy_acknowledgments
        ON CONFLICT (acknowledgment_id) DO UPDATE SET
            article_version_id = EXCLUDED.article_version_id,
            workspace_id = EXCLUDED.workspace_id,
            revoked_at = EXCLUDED.revoked_at,
            archived_at = now()
        """)
    )
    op.execute(
        sa.text(f"""
        CREATE TABLE IF NOT EXISTS {_ACK_ROWS} (
            id integer PRIMARY KEY,
            user_id integer NOT NULL,
            trust_article_id integer NOT NULL,
            acknowledged_at timestamp NOT NULL,
            created_at timestamp,
            article_version_id integer,
            workspace_id integer,
            revoked_at timestamp,
            archived_at timestamp NOT NULL DEFAULT now()
        )
        """)
    )
    op.execute(
        sa.text(f"""
        INSERT INTO {_ACK_ROWS} (
            id, user_id, trust_article_id, acknowledged_at, created_at,
            article_version_id, workspace_id, revoked_at
        )
        SELECT id, user_id, trust_article_id, acknowledged_at, created_at,
               article_version_id, workspace_id, revoked_at
        FROM policy_acknowledgments p
        WHERE EXISTS (
            SELECT 1 FROM policy_acknowledgments newer
            WHERE newer.user_id = p.user_id
              AND newer.trust_article_id = p.trust_article_id
              AND newer.id > p.id
        )
        ON CONFLICT (id) DO NOTHING
        """)
    )
    op.execute(
        sa.text("""
        DELETE FROM policy_acknowledgments p
        USING policy_acknowledgments newer
        WHERE newer.user_id = p.user_id
          AND newer.trust_article_id = p.trust_article_id
          AND newer.id > p.id
        """)
    )
    op.drop_constraint("uq_policy_ack_user_version", "policy_acknowledgments", type_="unique")
    op.drop_constraint("fk_policy_ack_version", "policy_acknowledgments", type_="foreignkey")
    op.drop_constraint("fk_policy_ack_workspace", "policy_acknowledgments", type_="foreignkey")
    op.drop_index("ix_policy_acknowledgments_article_version_id", table_name="policy_acknowledgments")
    op.drop_index("ix_policy_acknowledgments_workspace_id", table_name="policy_acknowledgments")
    op.drop_column("policy_acknowledgments", "revoked_at")
    op.drop_column("policy_acknowledgments", "workspace_id")
    op.drop_column("policy_acknowledgments", "article_version_id")
    op.create_index(
        "ix_policy_ack_user_article",
        "policy_acknowledgments",
        ["user_id", "trust_article_id"],
        unique=True,
    )
    op.drop_index("ix_trust_articles_published_version_id", table_name="trust_articles")
    op.drop_column("trust_articles", "published_version_id")
    op.execute(f"DROP TRIGGER IF EXISTS {_TRIGGER} ON {_VERSIONS}")
    op.drop_index("ix_trust_article_versions_workspace_id", table_name=_VERSIONS)
    op.drop_index("ix_trust_article_versions_trust_article_id", table_name=_VERSIONS)
    op.drop_table(_VERSIONS)
    op.execute(f"DROP FUNCTION IF EXISTS {_FUNCTION}()")
