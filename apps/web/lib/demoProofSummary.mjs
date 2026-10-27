/**
 * UI consumer for demonstration proof summaries (schema version 1).
 * The dashboard page imports this module. Release tests execute the same file.
 * Synthetic placeholders and unsupported facts are not rendered as numbers.
 */

export const PROOF_SUMMARY_SCHEMA_VERSION = '1'

const TRACTION_LABEL = 'Not commercial traction'

export function presentDemoProof(payload) {
  if (!payload || typeof payload !== 'object') {
    return emptyPresentation('unavailable', 'The summary response was empty.')
  }
  const summary =
    payload.proof_summary && typeof payload.proof_summary === 'object'
      ? payload.proof_summary
      : payload
  if (summary.schema_version !== PROOF_SUMMARY_SCHEMA_VERSION) {
    return emptyPresentation(
      'unsupported_schema',
      'This screen reads proof summary schema version 1 only.'
    )
  }
  const metrics = Array.isArray(summary.metrics) ? summary.metrics : []
  const synthetic = Array.isArray(summary.synthetic_placeholders)
    ? summary.synthetic_placeholders
    : []
  const unsupported = Array.isArray(summary.unsupported)
    ? summary.unsupported
    : []
  const partialFailures = Array.isArray(summary.partial_failures)
    ? summary.partial_failures
    : []
  const facts = [...metrics, ...synthetic, ...unsupported]
  const labeled = facts.every(
    (fact) => fact && fact.commercial_traction === false
  )
  if (summary.commercial_traction !== false || !labeled) {
    return emptyPresentation(
      'rejected',
      'This summary claimed commercial traction or omitted the traction label. It is not shown.'
    )
  }
  return {
    schemaVersion: summary.schema_version,
    summaryId: summary.summary_id ?? null,
    contentHash: summary.content_hash ?? null,
    status: summary.status ?? null,
    state: summary.status ?? null,
    reason: null,
    commercialTraction: false,
    tractionLabel: TRACTION_LABEL,
    dataWindow: summary.data_window ?? null,
    rows: metrics.map(presentMetric),
    synthetic: synthetic.map((item) => ({
      name: item.name,
      origin: item.origin ?? null,
      basis: item.basis ?? null,
      state: item.state ?? 'synthetic_placeholder',
      value: null,
      commercialTraction: false,
      label: 'Synthetic placeholder',
    })),
    unsupported: unsupported.map((item) => ({
      name: item.name,
      state: item.state ?? 'unsupported',
      value: null,
      displayValue: 'Unsupported',
      commercialTraction: false,
      reason: item.reason ?? null,
    })),
    partialFailures: partialFailures.map((item) => ({
      code: item.code ?? null,
      source: item.source ?? null,
      count: item.count ?? null,
      message: item.message ?? '',
      retryable: item.retryable === true,
    })),
  }
}

function presentMetric(metric) {
  return {
    name: metric.name,
    value: metric.value === undefined ? null : metric.value,
    displayValue: displayValue(metric),
    origin: metric.origin ?? null,
    basis: metric.basis ?? null,
    state: metric.state ?? null,
    unit: metric.unit ?? null,
    commercialTraction: false,
    tractionLabel: TRACTION_LABEL,
    windowStart: metric.data_window ? (metric.data_window.start ?? null) : null,
    windowEnd: metric.data_window ? (metric.data_window.end ?? null) : null,
    timezone: metric.data_window ? (metric.data_window.timezone ?? null) : null,
  }
}

function displayValue(metric) {
  if (!metric || metric.state === 'unavailable') return 'Unavailable'
  if (metric.state === 'unsupported') return 'Unsupported'
  if (metric.state === 'no_data') return 'No data'
  if (metric.value === null || metric.value === undefined) return 'Unavailable'
  return String(metric.value)
}

function emptyPresentation(state, reason) {
  return {
    schemaVersion: null,
    summaryId: null,
    contentHash: null,
    status: state,
    state,
    reason,
    commercialTraction: false,
    tractionLabel: TRACTION_LABEL,
    dataWindow: null,
    rows: [],
    synthetic: [],
    unsupported: [],
    partialFailures: [],
  }
}
