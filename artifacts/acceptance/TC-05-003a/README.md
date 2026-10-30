# TC-05-003a evidence

Base: `0948b2608b2a8cde142ebfac66b7d7d121411a4d`.
Branch: `codex/TC-05-003a-custom-role-grants`.
Claim: [#85 comment 6514687779](https://github.com/Johnathan-u/trust-copilot/issues/85#issuecomment-6514687779).

The product specification explicitly bounds custom-role grants by creator
authority. Read-only intake reproduced a restricted custom administrator creating
edit authority and enabling edit on its own role; `/api/auth/me` reported the new
permission with the same cookie. Custom flags are independently resolved from
current DB state, so built-in administrator authority does not justify that case.

The new regression first ran against unchanged production code: **11 failed,
13 passed**. Failures covered absent edit/review/export grants on creation,
creation's default review grant, self-promotion, another definition's promotion,
and granting after a trusted administrator revoked authority. They returned 200
instead of 403. Legitimate operations and existing authorization controls passed.

The repair snapshots current permissions before any target mutation. Creation
checks every enabled flag; updates check only newly enabled flags. This avoids
an identity-map/self-update error where authority read after mutation could
approve the actor's newly assigned flag. Unchanged flags, metadata-only changes,
omitted/null values, legitimate grants and revocations remain supported.

All **24 SQLite scenarios pass**. They use real stored human/session records,
signed cookies, memberships, member/auth routes and ORM commits. A deliberately
stale admin cookie resolves to the current restricted membership. A foreign
workspace's same-name role has broader flags and cannot supply local authority.
Successful writes preserve audits; every denied request and owned cleanup must
preserve full baseline row hashes, including audits.

The identical 24 PostgreSQL cases collect (48 total), but PostgreSQL is **not
locally qualified**. Strict full-suite execution exits 3 on localhost:5432
connection refusal during Alembic setup. SQLite foreign keys are enabled; no
PostgreSQL guard, trigger, migration or sequence was bypassed. Actual PostgreSQL,
independent review and final-head CI remain required. See
[verification.txt](verification.txt).

This is only a custom-role definition repair. Assignment, invite and API-key
grant ceilings remain follow-up work. Owner/viewer semantics/migration,
final-owner policy and full TC-05-003 remain open. No claim of complete privilege
escalation prevention or provider qualification is made. No auth/model/schema/UI/
dependency/CI files changed.
