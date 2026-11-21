# Salesforce pipeline sync

Salesforce deal sync reads one selected pipeline from `SALESFORCE_API_BASE_URL` and stores it as deals. The value is an `http` or `https` origin with no user info, query, or path. Unset refuses the sync. Hostnames of Salesforce are refused. The variable is not a credential. The client sends no authorization header and does not follow redirects.

Tests and local qualification point the variable at a fixture server on `127.0.0.1`. That server returns Salesforce query pages (`totalSize`, `done`, `nextRecordsUrl`, `records`). This build does not call Salesforce. Real-provider sandbox evidence is N/A under that ruling. HubSpot is still the labeled example until TC-20-053.

## Run a sync

An admin sends `POST /api/crm/sync/salesforce` with `pipeline_id` (letters, digits, `_`, `-`, at most 64 characters) and an optional `connection_id`. The call queues a `crm_sync` job and returns the job id. The same pipeline already queued returns that job.

The worker walks query pages. Each committed page stores the cursor on `crm_connections`. `cursor_kind = page` means the next attempt reads that page again. `cursor_kind = complete` means the pass finished and `cursor` is the newest `LastModifiedDate` seen. A finished pass tombstones deals for that connection that were not in the page set (`crm_removed_at`). The deal row stays. A later pass that includes the id clears the tombstone.

A retry of a page does not insert a second deal. The unique key is workspace, connection, provider, and `crm_external_id`. The stable id on the deal is `{workspace}:{connection}:salesforce:{external id}` and is kept.

## Manual edits

A deal update records the fields that changed. The next sync does not write those fields. Amount and currency stay together, and the two close dates stay together. A stage change and notes survive. Other fields still update from the provider.

## Jobs history

`crm_sync` is the only CRM sync kind. Salesforce and HubSpot share it. The payload `provider` selects which one runs. HubSpot is not executed yet. The jobs page shows the kind, the record counts, cancel, retry, and a link to `/dashboard/deals?connection_id=<id>`. Reload reads the stored job and the current connection in the same workspace.

## Migration

Revision `tc20050_crm_pipeline_sync`. Upgrade dedupes existing rows that share a workspace, provider, and external id (a missing connection matches another missing connection). The oldest row keeps that identity. Later rows remain as deals, with the CRM identity cleared into `tc20050_deal_identity_hold`. Downgrade restores that identity when the external id is still empty, then drops the new columns and the connection table. See `docs/release/tickets/TC-20-050.md`.
