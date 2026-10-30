# TC-04-006a evidence

Tested base: `7b3ea6e5369a550960ae7d98f7565c7897c2087f` (#131 final).
Branch: `codex/TC-04-006a-session-persistence`.
This evidence describes the accompanying source/test commit, not a passed CI run.
The coordinator alone publishes and merges after independent review and the four
exact-head gates.

## Separate defect controls

The initial temporary intake used the real password/MFA routes, production
authorization/signing, stored SQLite users/memberships/sessions, and actual
workspace endpoints. All reissues retained SID and `UserSession.created_at`, and
the resulting `/auth/me` requests succeeded.

| Flow                        | Original Max-Age | Reissued Max-Age | Expected persistence result |
| --------------------------- | ---------------- | ---------------- | --------------------------- |
| Password false → switch     | absent           | 86400            | failed                      |
| Password false → create     | absent           | 604800           | failed                      |
| MFA false → switch          | absent           | 86400            | failed                      |
| Pending onboarding → create | absent           | 604800           | failed                      |
| Password true → switch      | 86400            | 86400            | passed                      |
| Password true → create      | 86400            | 604800           | passed for persistence only |

A separate creation test showed a 518400-second extension of the signed expiry,
and `/auth/me` still returned 200 at the original expiry plus one second. The
temporary run therefore had five intended contract failures and two positive
controls. These are two defects: cookie persistence and absolute expiry.

## Source boundary

All seven production `sign_session` call sites are covered:

| Call site                          | Signed persistence choice                                     |
| ---------------------------------- | ------------------------------------------------------------- |
| Password login without a workspace | false, as its current cookie behavior requires                |
| Password login with membership     | submitted remember choice; false for restricted re-enrollment |
| Common OAuth/SSO issuer            | true, preserving its existing behavior                        |
| Workspace switch                   | inherited exact signed true only                              |
| MFA re-enrollment completion       | false, preserving its current behavior                        |
| MFA login completion               | submitted remember choice                                     |
| Workspace creation                 | inherited exact signed true only                              |

The new field is additive signed metadata, not a new credential or permission.
Legacy missing/malformed values remain authenticated, but are never inferred to
be persistent. The tests cover missing, null, strings, integers, collections,
false and true through real stored auth and both reissue routes.

Creation resolves the current deadline before mutation, obtains the actual new
workspace policy inside the transaction, signs the minimum absolute deadline,
and rechecks time before commit. It saves the response fields before commit,
avoiding the former post-commit refresh. A failed target-policy read now rolls
back the staged workspace. Source recheck failure, expired credentials, revoked
sessions, inactive membership and expiry during real signing all preserve full
rows and produce no cookie.

## Verification

`verification.txt` records commands, counts and limits. The new matrix supplies
48 local SQLite controls and 48 corresponding migrated PostgreSQL cases. All
174 selected local cases pass, including the existing policy/principal/session/
MFA suites. Full unit selection passes 714 tests, with 11 existing skips.

The first new-matrix run produced 42 failures and five passes. Its late-policy
failure additionally triggered the fixture's unchanged-external-row assertion
because the old route committed a workspace before failing; cleanup ownership
bookkeeping was corrected, and the focused baseline rerun had four intended
failures, one pass and no teardown error. No assertion was weakened to permit
the partial commit. The final target-policy case asserts full database equality.

An existing signing-clock test initially failed twice because its fixture had
unknown persistence but asserted Max-Age. Under approved scope extension, only
that setup now uses a real remembered password login. All eight original
assertion ASTs are preserved; one login-success assertion was added.

The fresh HTTP-client cookie-jar discard test validates emitted cookie metadata;
it is not evidence of browser restart behavior. The common OAuth issuer test
does not qualify provider callbacks or live provider exchanges. The PostgreSQL
attempt fails closed with exit 3 because local PostgreSQL is absent. Independent
review, actual PostgreSQL CI and all four exact-head jobs remain required.

Parent TC-04-006 stays open for idle behavior and full multi-browser warning/
logout acceptance. Existing provider, owner and blocked-publication gates are
unchanged. No database migration, new dependency, new setting, CI or frontend
edit is included.
