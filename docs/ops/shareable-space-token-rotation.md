# Shareable-space token rotation

Operator runbook for rotating buyer links on shareable spaces (TC-17-005a AC4).
It does not contain a token, a hash, or buyer contact details. Do not paste a
raw token, its SHA-256, or a buyer email into this file, a ticket, a log, or a
shell history that is retained.

There is no bulk rotation script. Rotate one space at a time. Do not write a
script that prints tokens.

## Why

Every space that was live before commit `8e264ec` (pull request #257) is
treated as exposed. Before that change, `GET /api/shareable-spaces` returned
the stored plaintext token to every signed-in member. The migration hashed
those values and left the same raw token working. Anyone who listed spaces,
and any backup or log of those responses, should be treated as holding a live
buyer link until the space expires, is deactivated, or an admin rotates it.

Rotation replaces the stored hash and keeps the space id. Contents,
`expires_at`, `is_active`, and a deal's `room_id` link stay as they are. The
old raw token stops matching immediately. Deactivating the space and creating
a new one is not the procedure: that would drop the deal's room link.

## List the live spaces

A live space has `is_active` true and `expires_at` null or later than now.
Inactive and expired spaces are not rotated. Rotation refuses them and does
not turn them back on.

### In the UI

Sign in as an admin. Open **Shareable spaces** in the Admin section
(`/dashboard/shareable-spaces`). The list is the current workspace. Each row
is **Live**, **Inactive**, or **Expired**. The list never shows a raw token.
`Rotate link` is on Live rows only, and only for an admin.

### Via the API

`GET /api/shareable-spaces` with the admin's session cookie (or an admin API
key). The body is `{ "spaces": [ ... ] }`. `access_token` is null. An admin
also receives `has_access_token`. Keep a space when `is_active` is true and
`expires_at` is null or in the future. Do not log the response if you have
any doubt a token is in it; this route does not return one.

## Rotate one space

Do this for each live space. Copy the new link before you leave the screen
or the response. It is not stored, and a later read cannot show it again.

### In the UI

1. On a Live row, choose **Rotate link**.
2. Confirm the dialog. It says the old link will stop working immediately.
   Cancel leaves the current link in place.
3. The new buyer link appears once, in the **New buyer link** dialog, with
   **Copy link**. It is not written to the list, to browser storage, or to a
   log by this screen.
4. Copy it, then close the dialog. Closing removes it from the page.

### Via the endpoint

`POST /api/shareable-spaces/{id}/rotate` with no body, as an admin in the
space's workspace.

- `200` returns the same shape as create. `access_token` is the new raw token
  and is the only time it is returned. `has_access_token` is true. The id,
  name, buyer fields, `expires_at`, and `is_active` are unchanged.
- `403` means the caller is not an admin.
- `404` means the id is not in the caller's workspace. A miss and another
  workspace look the same.
- `409` means the space is inactive or expired. The row is unchanged.

Copy `access_token` out of the response into the operator secret store or
straight into the message you send the buyer. Do not write the response body
to a log, a CI transcript, or a ticket.

The buyer link is the application origin the buyer already uses, plus the
path `/api/shareable-spaces/access`, with the query name `token` set to the
new raw value from that response.

## Tell the buyer

The owner sends each buyer the new link and tells them the old link no longer
works. The product does not send that message. One buyer, one space, one new
link. Do not put the link in a ticket.

## Check that the old link is dead

Call the public access route with the previous token. Do not log the query
string.

Call `GET /api/shareable-spaces/access` and pass the previous raw value as the
`token` query parameter. Do not write that value into the command transcript.

A rotated token comes back as `{"valid": false, "reason": "Space not found"}`.
The new token, until the space expires or is deactivated, comes back with
`"valid": true` and the same space id. The public space object has
`access_token` null.

Confirm the deal that pointed at the space still has the same `room_id`.
Rotation does not create a new space.
