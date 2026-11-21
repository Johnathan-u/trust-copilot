# Dashboard cards

Operator note for workspace dashboard cards (TC-25-001). No new configuration key.

Built-in cards (Documents, Questionnaires, Exports, Trust Center) are always listed first. They are not rows. They have no id and no `updated_at`.

A custom card is one row in `dashboard_cards` for the current workspace. `updated_at` is the revision. The column is already on the table. This change does not add a migration.

`PATCH /api/dashboard/cards/{card_id}` must send the `updated_at` the editor loaded. A missing value is 422. A value that is not the stored revision is 409, and the stored row is left unchanged. The editor form sends that value and does not treat 409 as a saved card. Reload the card and send the new `updated_at`.

Reorder writes `updated_at` when a card's position changes. An edit that still holds the previous `updated_at` is 409.

`POST /api/dashboard/cards` accepts an `Idempotency-Key`. The same key and the same body return the first card and do not insert another. A later request, including one from a new API process, reads that card from `GET /api/dashboard/cards`. The same key with a different body is 422. A request with no key still inserts a new card. A rejected create does not keep the key.

An editor cannot create, update, delete, or reorder. Another workspace's card is 404. A target route, icon, size, or visibility outside the lists below is 422 and stores nothing.

Allowed target routes (`ALLOWED_ROUTES`):

- `/dashboard/documents`
- `/dashboard/questionnaires`
- `/dashboard/review`
- `/dashboard/requests`
- `/dashboard/exports`
- `/dashboard/compliance-gaps`
- `/dashboard/trust-center`
- `/dashboard/proof-chain`
- `/dashboard/members`
- `/dashboard/notifications`
- `/dashboard/slack`
- `/dashboard/gmail`
- `/dashboard/audit`
- `/dashboard/ai-governance`
- `/dashboard/settings`
- `/dashboard/security`

Visibility is `all` or `admin`. A non-admin sees a custom card only when it is enabled and its visibility is `all`.
