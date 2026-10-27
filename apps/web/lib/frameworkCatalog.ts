/**
 * UI consumer for GET /api/compliance/frameworks and POST /api/compliance/frameworks/enable.
 *
 * A catalog is a production catalog only when rights, licence, enablement, and a
 * licensed content version all say so, and the row is not dev/test. Until
 * TC-01-007 clears content rights, the API reports every advertised framework
 * as blocked. This module does not treat a blocked or dev row as enabled.
 */

export const FRAMEWORK_CATALOG_CONTRACT_VERSION = 'framework-catalog/v1'
export const FRAMEWORK_CATALOG_ERROR_CONTRACT_VERSION =
  'framework-catalog-error/v1'

export type FrameworkCatalogItem = {
  id: number | null
  name: string
  version: string | null
  created_at: string | null
  catalog_key?: string | null
  source_provenance?: Record<string, unknown> | null
  rights_status?: string | null
  licence_status?: string | null
  enablement_state?: string | null
  catalog_kind?: string | null
  production_catalog?: boolean
  rights_ticket?: string | null
  contract_version?: string | null
  content_version?: string | null
  content_origin?: string | null
  blocked_reason?: string | null
  synthetic_dev_content_present?: boolean
  dev_test_only?: boolean
  stored_control_count?: number
  controls_are_production_catalog?: boolean
}

export type FrameworkCatalogError = {
  contract_version: string
  code: string
  message: string
  request_id: string
  retryable: boolean
  field_errors?: Record<string, string> | null
  catalog_key?: string | null
  rights_status?: string | null
  licence_status?: string | null
  enablement_state?: string | null
  rights_ticket?: string | null
  partial_failure?: boolean
  steps?: Array<Record<string, string>> | null
}

export type CatalogDisplayState =
  'blocked_pending_rights' | 'dev_test_only' | 'blocked' | 'enabled'

export function isDevTestOnly(item: FrameworkCatalogItem): boolean {
  return Boolean(
    item.dev_test_only ||
    item.synthetic_dev_content_present ||
    item.catalog_kind === 'dev_synthetic' ||
    item.enablement_state === 'dev_only' ||
    item.rights_status === 'dev_test_only' ||
    item.licence_status === 'dev_test_only' ||
    item.content_origin === 'dev_seed'
  )
}

/**
 * True only for a cleared, licensed, enabled production catalog.
 * A stored version string alone is not a licensed content version.
 */
export function isProductionCatalogEnabled(
  item: FrameworkCatalogItem
): boolean {
  if (isDevTestOnly(item)) return false
  if (
    item.controls_are_production_catalog === true &&
    item.production_catalog !== true
  )
    return false
  if (item.production_catalog !== true) return false
  if (item.rights_status !== 'cleared') return false
  if (item.licence_status !== 'cleared') return false
  if (item.enablement_state !== 'enabled') return false
  if (!item.content_version) return false
  return true
}

export function catalogDisplayState(
  item: FrameworkCatalogItem
): CatalogDisplayState {
  if (isDevTestOnly(item)) return 'dev_test_only'
  if (isProductionCatalogEnabled(item)) return 'enabled'
  if (
    item.rights_status === 'blocked_pending_rights' ||
    item.enablement_state === 'blocked'
  ) {
    return 'blocked_pending_rights'
  }
  return 'blocked'
}

/** Rights column. Never render the stored rights_status enum. */
export function catalogRightsLabel(_item: FrameworkCatalogItem): string {
  return 'Pending content licensing'
}

export function catalogStatusLabel(item: FrameworkCatalogItem): string {
  const state = catalogDisplayState(item)
  if (state === 'dev_test_only')
    return 'Dev / test only — not a production catalog'
  if (state === 'enabled') return 'Enabled'
  if (state === 'blocked_pending_rights') {
    return 'Pending content licensing'
  }
  return 'Blocked — not a production catalog'
}

export function parseCatalogList(body: unknown): FrameworkCatalogItem[] {
  if (!Array.isArray(body)) return []
  return body.filter((item): item is FrameworkCatalogItem => {
    return (
      Boolean(item) &&
      typeof item === 'object' &&
      typeof (item as FrameworkCatalogItem).name === 'string'
    )
  })
}

/** Enable posts catalog_key only. Dev rows and rows without a key are not sent. */
export function enableRequestBody(
  item: FrameworkCatalogItem
): { catalog_key: string } | null {
  if (isDevTestOnly(item) || !item.catalog_key) return null
  return { catalog_key: item.catalog_key }
}

export function parseEnableError(body: unknown): {
  message: string
  contract: FrameworkCatalogError | null
} {
  const detail =
    body && typeof body === 'object' && 'detail' in body
      ? (body as { detail: unknown }).detail
      : body
  if (typeof detail === 'string' && detail.trim()) {
    return { message: detail, contract: null }
  }
  if (
    detail &&
    typeof detail === 'object' &&
    typeof (detail as FrameworkCatalogError).message === 'string'
  ) {
    return {
      message: (detail as FrameworkCatalogError).message,
      contract: detail as FrameworkCatalogError,
    }
  }
  return { message: 'Framework enablement was refused.', contract: null }
}
