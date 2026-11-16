# TC-23-001a: deal room `access_token` is not a credential, and it is no longer returned below `can_review`

The parent room read stays accepted. This note does not accept TC-23-001 or TC-23-001a.

## What the token grants

Nothing. `GET /api/deals/{id}/room` (`apps/api/app/api/routes/deals.py:333`) calls `generate_deal_room` (`apps/api/app/services/deal_room_service.py:21`). That function mints `secrets.token_urlsafe(32)` on the read (`deal_room_service.py:92-93`) and puts it in the JSON (`deal_room_service.py:99`). It does not insert a row, set an expiry, or record a hash.

No route looks the value up. The public token routes that do accept a secret are different stored credentials:

| Route | What it checks | Expiry / revocation |
| --- | --- | --- |
| `GET /api/shareable-spaces/access` (`shareable_spaces.py:71-77`) | `ShareableSpace.access_token` (`shareable_space_service.py:78-97`) | `expires_at`, and `is_active` false after deactivate |
| `GET /api/nda-access/validate` (`nda_access.py:94-100`) | `NdaAccessRequest.access_token` (`nda_access_service.py:98-110`) | `expires_at`, and status `revoked` / not `approved` (`nda_access_service.py:83-95`) |
| `GET /public/buyer-portal/{token}/manifest` (`buyer_portal.py:135-138`) | `BuyerPortal.portal_token` where `active` (`buyer_portal_service.py:61-65`) | inactive portal is 404; this column is not the room marker |
| `GET /api/vendor-response` (`vendor_response.py:15-21`) | hashed or legacy vendor link (`vendor_request_service.py:350-366`) | missing, revoked, or expired grant is 404 |

`test_room_marker_is_not_stored_or_accepted` submits the room marker to those four routes and queries those four columns. The public routes reject it, the columns do not contain it, and a second read of the same room returns a different string. There is nothing to revoke and nothing that expires, because the value is discarded when the response is sent.

`Deal.room_id` (`deal.py:51`) is a foreign key to `shareable_spaces`, which is the stored buyer-space token above. The package route does not read that row and does not return that token.

The marker was described as a sharing token in `TICKETS.md` (E1-05). That sharing path was never connected. PR #234's page requires a non-blank string only so a partial body fails, then drops it so the page cannot render it (`apps/web/lib/dealConsumer.ts:259-265`, `DealLinksPanel.tsx:180-186`).

The room body itself still includes linked questionnaire text, truncated to 200 characters (`deal_room_service.py:63-68`), and published trust-center article ids. That read stays available to any signed-in member. This ticket gates the marker, not the room.

## Fix

The room route stays on `require_session` (`auth_deps.py:204`). `access_token` is a non-empty string only when the caller has `can_review` or `can_admin`. Otherwise the field is JSON `null`, and `generate_deal_room` is told not to mint a secret.

The check is `_room_token_visible` (`deals.py:321-330`). It calls `_resolve_permission` (`auth_deps.py:235`), the same helper `require_can_review` and `require_can_admin` use (`auth_deps.py:281-283`). Built-in roles come from `roles.py:36-41`: admin, editor, and reviewer all have `can_review`. A custom role is looked up by name in the caller's workspace. `can_admin` is included so a custom role that sets admin without review still receives the marker ("can_review or above"). `can_edit` and `can_export` do not.

API keys enter through `get_api_key_context` (`auth_deps.py:143-165`) and use the key's `role` in that same check.

## Other responses

These deal routes do not include this marker. Tests cover create, list, detail, and risk:

- `POST /api/deals` returns `deal_service._serialize` (`deal_service.py:380`). No `access_token` key.
- `GET /api/deals`, `GET /api/deals/{id}`, and `GET /api/deals/{id}/risk` likewise. There is no separate room-create route for this marker.

A different secret, not changed here: `GET /api/shareable-spaces` is `require_session` (`shareable_spaces.py:50-55`) and `_serialize` includes the stored space token (`shareable_space_service.py:109`). That value is accepted by the public access route above. Create and deactivate of a space stay on `require_can_admin`. NDA approval, which mints the NDA token, is also `require_can_admin`.

## Frontend

`parseDealRoom` used to reject a missing or blank marker for every caller, then omit it from the parsed room. Built-in admin, editor, and reviewer still receive a string, so their pages were unaffected. A custom role without `can_review` and without `can_admin` can open Links and risk (`docs/release/tickets/TC-15-049.md`: any signed-in session reads the room). For that caller the API now sends `null`. The parser accepts `null` or a missing field, still rejects a blank string, and still drops a real token so the page cannot render it (`dealConsumer.ts:259-265`).

## Tests

Local, Python 3.12, Postgres 16 `trustcopilot_test`. Base before the gate: `af6e742f85f8aa9c1115bfe2776e1bdd2d0041da`.

| Run | Result |
| --- | --- |
| `pytest tests/test_deal_room_token_gate.py` before the gate | 4 failed, 8 passed (`before.txt`). Member, edit-only, export-only, and a member API key received a marker. |
| Same file plus `tests/test_deals.py` after the gate | 32 passed (`after.txt`). Low roles and the member key get `null`. Reviewer, editor, admin, custom `can_review`, and custom `can_admin` still get a string. No session is 401. |
| Those files plus `tests/release/test_deal_questionnaire_link_scope.py` and `tests/release/test_domain_deals.py` | 70 passed (`pytest.txt`). |
| `npx vitest run lib/dealConsumer.test.ts tests/unit/deals-page.test.ts` | 2 files, 95 passed (`vitest.txt`). A reader with `access_token: null` still sees the empty room. |

`screen-deals` still mocks a room body that includes a marker. The parser still accepts that body, so the spec's contract is unchanged. CI `web-release-e2e` is the browser run.

## Security notes

The marker grants no access today. It is still withheld below `can_review` because it is shaped like the real shareable-space and NDA tokens, and the deals page was written so it would not render. Returning it on every session read put that value in the browser and in any client that stores the JSON.

Questionnaire excerpts and published articles on this route remain visible to any signed-in workspace member. That is the existing room read. The shareable-space list still returns a real public token to any session; that is a different credential and is not part of this change.

Needs Claude's pre-merge review (auth/security). Not merging.
