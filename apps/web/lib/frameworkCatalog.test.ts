import { describe, expect, it } from 'vitest'
import {
  FRAMEWORK_CATALOG_ERROR_CONTRACT_VERSION,
  FRAMEWORK_RIGHTS_TICKET,
  catalogDisplayState,
  catalogStatusLabel,
  enableRequestBody,
  hasLegacyListFields,
  isProductionCatalogEnabled,
  parseCatalogList,
  parseEnableError,
  type FrameworkCatalogItem,
} from '@/lib/frameworkCatalog'

function item(
  overrides: Partial<FrameworkCatalogItem> = {}
): FrameworkCatalogItem {
  return {
    id: 1,
    name: 'SOC 2',
    version: 'rights-pending',
    created_at: '2026-10-27T00:00:00',
    catalog_key: 'SOC2',
    source_provenance: {
      kind: 'scaffold',
      content_included: false,
      rights_ticket: FRAMEWORK_RIGHTS_TICKET,
    },
    rights_status: 'blocked_pending_rights',
    licence_status: 'not_cleared',
    enablement_state: 'blocked',
    catalog_kind: 'advertised_blocked',
    production_catalog: false,
    rights_ticket: FRAMEWORK_RIGHTS_TICKET,
    contract_version: 'framework-catalog/v1',
    content_version: null,
    blocked_reason: 'Pending content licensing. No licensed catalog is loaded.',
    dev_test_only: false,
    synthetic_dev_content_present: false,
    controls_are_production_catalog: false,
    ...overrides,
  }
}

describe('framework catalog consumer', () => {
  it('keeps the historical list fields and treats the blocked payload as not enabled', () => {
    const row = item()
    expect(hasLegacyListFields(row)).toBe(true)
    expect(isProductionCatalogEnabled(row)).toBe(false)
    expect(catalogDisplayState(row)).toBe('blocked_pending_rights')
    expect(catalogStatusLabel(row)).toBe('Pending content licensing')
    expect(catalogStatusLabel(row)).not.toContain('TC-01-007')
  })

  it('does not treat a version string or a dev row as a production catalog', () => {
    expect(
      isProductionCatalogEnabled(
        item({ version: '2024', content_version: null })
      )
    ).toBe(false)
    const dev = item({
      name: 'HITRUST',
      catalog_key: null,
      catalog_kind: 'dev_synthetic',
      enablement_state: 'dev_only',
      rights_status: 'dev_test_only',
      licence_status: 'dev_test_only',
      dev_test_only: true,
      version: 'CSF-dev',
      production_catalog: true,
      content_version: 'CSF-dev',
    })
    expect(isProductionCatalogEnabled(dev)).toBe(false)
    expect(catalogDisplayState(dev)).toBe('dev_test_only')
  })

  it('requires every production gate before reporting enabled', () => {
    const cleared = item({
      production_catalog: true,
      rights_status: 'cleared',
      licence_status: 'cleared',
      enablement_state: 'enabled',
      content_version: 'licensed-v1',
      rights_ticket: null,
    })
    expect(isProductionCatalogEnabled(cleared)).toBe(true)
    expect(
      isProductionCatalogEnabled({
        ...cleared,
        rights_status: 'blocked_pending_rights',
      })
    ).toBe(false)
  })

  it('parses the versioned enablement error and never counts it as success', () => {
    const body = {
      detail: {
        contract_version: FRAMEWORK_CATALOG_ERROR_CONTRACT_VERSION,
        code: 'framework_rights_not_cleared',
        message:
          'SOC 2 cannot be enabled. Pending content licensing. No licensed catalog is loaded.',
        request_id: 'req-1',
        retryable: false,
        partial_failure: false,
        rights_status: 'blocked_pending_rights',
        enablement_state: 'blocked',
      },
    }
    const parsed = parseEnableError(body)
    expect(parsed.contract?.code).toBe('framework_rights_not_cleared')
    expect(parsed.message).toContain('Pending content licensing')
    expect(parsed.message).not.toContain('TC-01-007')
  })

  it('sends catalog_key only and does not enable a dev row', () => {
    expect(enableRequestBody(item())).toEqual({ catalog_key: 'SOC2' })
    expect(
      enableRequestBody(
        item({
          catalog_key: null,
          dev_test_only: true,
          catalog_kind: 'dev_synthetic',
          enablement_state: 'dev_only',
        })
      )
    ).toBeNull()
    const body = enableRequestBody(item({ name: 'SOC2', catalog_key: 'SOC2' }))
    expect(body).toEqual({ catalog_key: 'SOC2' })
    expect(body && 'name' in body).toBe(false)
  })

  it('reads a list payload and keeps blocked and dev rows distinct', () => {
    const rows = parseCatalogList([
      item(),
      item({
        id: 2,
        name: 'HITRUST',
        catalog_key: null,
        dev_test_only: true,
        catalog_kind: 'dev_synthetic',
        enablement_state: 'dev_only',
      }),
    ])
    expect(rows).toHaveLength(2)
    expect(rows.every((row) => !isProductionCatalogEnabled(row))).toBe(true)
    expect(catalogDisplayState(rows[1])).toBe('dev_test_only')
  })
})
