export const COMPLIANCE_ALERTS_SCHEMA = 'compliance-alerts/v1'

export type ComplianceAlert = {
  id: number
  severity: string
  title: string
  description: string
  metric: number | null
  type: string
  status: string
  condition: string
  source_ref: string
  source_revision: string | null
  control_id: number | null
  control_revision: string | null
  reason: string | null
  snoozed_until: string | null
}

export type ComplianceAlertResponse = {
  schema_version: typeof COMPLIANCE_ALERTS_SCHEMA
  alerts: ComplianceAlert[]
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function nullableNumber(value: unknown): number | null | undefined {
  if (value === null || value === undefined) return null
  if (typeof value === 'number' && Number.isFinite(value)) return value
  return undefined
}

function nullableString(value: unknown): string | null | undefined {
  if (value === null || value === undefined) return null
  if (typeof value === 'string') return value
  return undefined
}

function alert(value: unknown): ComplianceAlert | null {
  if (!isRecord(value)) return null
  if (typeof value.id !== 'number' || !Number.isFinite(value.id)) return null
  if (typeof value.severity !== 'string' || typeof value.title !== 'string')
    return null
  if (typeof value.description !== 'string' || typeof value.type !== 'string')
    return null
  if (typeof value.status !== 'string' || typeof value.condition !== 'string')
    return null
  if (typeof value.source_ref !== 'string') return null
  const metric = nullableNumber(value.metric)
  const sourceRevision = nullableString(value.source_revision)
  const controlId = nullableNumber(value.control_id)
  const controlRevision = nullableString(value.control_revision)
  const reason = nullableString(value.reason)
  const snoozedUntil = nullableString(value.snoozed_until)
  if (
    metric === undefined ||
    sourceRevision === undefined ||
    controlId === undefined ||
    controlRevision === undefined ||
    reason === undefined ||
    snoozedUntil === undefined
  ) {
    return null
  }
  return {
    id: value.id,
    severity: value.severity,
    title: value.title,
    description: value.description,
    metric,
    type: value.type,
    status: value.status,
    condition: value.condition,
    source_ref: value.source_ref,
    source_revision: sourceRevision,
    control_id: controlId,
    control_revision: controlRevision,
    reason,
    snoozed_until: snoozedUntil,
  }
}

export function parseComplianceAlerts(body: unknown): ComplianceAlertResponse {
  if (!isRecord(body)) throw new Error('compliance alerts response is missing')
  if (body.schema_version !== COMPLIANCE_ALERTS_SCHEMA) {
    throw new Error('compliance alerts schema is not recognized')
  }
  if (!Array.isArray(body.alerts))
    throw new Error('compliance alerts are missing')
  return {
    schema_version: COMPLIANCE_ALERTS_SCHEMA,
    alerts: body.alerts
      .map(alert)
      .filter((item): item is ComplianceAlert => item !== null),
  }
}
