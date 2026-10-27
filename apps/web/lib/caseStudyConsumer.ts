/** UI consumer for case-study.v2 (TC-25-005).

The badge and customer-claim flag come only from this module.
A synthetic row, or any row that is not an authorized consented publication,
is not a customer claim.
*/

export const CASE_STUDY_SCHEMA_VERSION = "case-study.v2"

export const PRESERVED_FIELDS = [
  "id",
  "workspace_id",
  "title",
  "company_name",
  "industry",
  "company_size",
  "challenge",
  "solution",
  "results",
  "quote",
  "quote_attribution",
  "metrics",
  "status",
  "published_at",
  "created_at",
] as const

export interface CaseStudyFieldError {
  field: string
  code: string
  organization_name: string | null
}

export interface CaseStudyView {
  id: number
  workspace_id: number
  title: string
  status: string
  schema_version: string
  synthetic: boolean
  data_basis: string
  customer_claim: boolean
  publication_authorized: boolean
  review_status: string
  revision: number
  published_at: string | null
  display_label: string
  quoted_organizations: string[]
  quoted_results: string[]
  blockers: CaseStudyFieldError[]
  company_name: string | null
  quote: string | null
  results: string | null
  metrics: Record<string, unknown> | null
}

export function displayLabel(input: {
  customer_claim: boolean
  synthetic: boolean
  data_basis: string
}): string {
  if (input.customer_claim && !input.synthetic && input.data_basis === "consented_customer") {
    return "Consented publication"
  }
  if (input.synthetic || input.data_basis === "synthetic_example") {
    return "Synthetic example. Not a customer claim."
  }
  return "Not a customer claim."
}

export function parseCaseStudyResponse(body: unknown): CaseStudyView {
  if (!body || typeof body !== "object") {
    throw new Error("case study response must be an object")
  }
  const rec = body as Record<string, unknown>
  if (rec.schema_version !== CASE_STUDY_SCHEMA_VERSION) {
    throw new Error("schema_version mismatch")
  }
  for (const field of PRESERVED_FIELDS) {
    if (!(field in rec)) {
      throw new Error(`missing preserved field ${field}`)
    }
  }
  const synthetic = rec.synthetic === true
  const dataBasis = typeof rec.data_basis === "string" ? rec.data_basis : ""
  const rawClaim = rec.customer_claim === true
  const customerClaim =
    rawClaim &&
    !synthetic &&
    dataBasis === "consented_customer" &&
    rec.status === "published" &&
    rec.publication_authorized === true
  const quotedOrganizations = Array.isArray(rec.quoted_organizations)
    ? rec.quoted_organizations.filter((item): item is string => typeof item === "string")
    : []
  const quotedResults = Array.isArray(rec.quoted_results)
    ? rec.quoted_results.filter((item): item is string => typeof item === "string")
    : []
  const blockers = Array.isArray(rec.blockers)
    ? rec.blockers
        .filter((item): item is Record<string, unknown> => !!item && typeof item === "object")
        .map((item) => ({
          field: typeof item.field === "string" ? item.field : "",
          code: typeof item.code === "string" ? item.code : "",
          organization_name: typeof item.organization_name === "string" ? item.organization_name : null,
        }))
    : []
  return {
    id: Number(rec.id),
    workspace_id: Number(rec.workspace_id),
    title: typeof rec.title === "string" ? rec.title : "",
    status: typeof rec.status === "string" ? rec.status : "",
    schema_version: CASE_STUDY_SCHEMA_VERSION,
    synthetic,
    data_basis: dataBasis,
    customer_claim: customerClaim,
    publication_authorized: rec.publication_authorized === true,
    review_status: typeof rec.review_status === "string" ? rec.review_status : "",
    revision: Number(rec.revision),
    published_at: typeof rec.published_at === "string" ? rec.published_at : null,
    display_label: displayLabel({
      customer_claim: customerClaim,
      synthetic,
      data_basis: dataBasis,
    }),
    quoted_organizations: quotedOrganizations,
    quoted_results: quotedResults,
    blockers,
    company_name: typeof rec.company_name === "string" ? rec.company_name : null,
    quote: typeof rec.quote === "string" ? rec.quote : null,
    results: typeof rec.results === "string" ? rec.results : null,
    metrics: rec.metrics && typeof rec.metrics === "object" ? (rec.metrics as Record<string, unknown>) : null,
  }
}

export function parseCaseStudyError(body: unknown): {
  code: string
  message: string
  retryable: boolean
  field_errors: CaseStudyFieldError[]
} {
  const rec = body && typeof body === "object" ? (body as Record<string, unknown>) : {}
  if (Array.isArray(rec.detail) && rec.detail.length > 0) {
    const first = rec.detail[0] as { msg?: unknown }
    return {
      code: "validation_error",
      message: first && typeof first.msg === "string" ? first.msg : "Request failed",
      retryable: false,
      field_errors: [],
    }
  }
  const detail =
    rec.detail && typeof rec.detail === "object" ? (rec.detail as Record<string, unknown>) : rec
  const message =
    typeof detail.message === "string"
      ? detail.message
      : typeof detail.msg === "string"
        ? detail.msg
        : typeof detail === "string"
          ? detail
          : "Request failed"
  const fieldErrors = Array.isArray(detail.field_errors)
    ? detail.field_errors
        .filter((item): item is Record<string, unknown> => !!item && typeof item === "object")
        .map((item) => ({
          field: typeof item.field === "string" ? item.field : "",
          code: typeof item.code === "string" ? item.code : "",
          organization_name: typeof item.organization_name === "string" ? item.organization_name : null,
        }))
    : []
  return {
    code: typeof detail.code === "string" ? detail.code : "unknown",
    message,
    retryable: detail.retryable === true,
    field_errors: fieldErrors,
  }
}

const AGREE_FIELDS = [
  "id",
  "status",
  "schema_version",
  "synthetic",
  "data_basis",
  "customer_claim",
  "publication_authorized",
  "review_status",
  "revision",
  "published_at",
  "display_label",
] as const

export function outcomesAgree(apiBody: unknown, persisted: unknown): { agrees: boolean; mismatches: string[] } {
  const view = parseCaseStudyResponse(apiBody)
  const api = apiBody as Record<string, unknown>
  const stored = persisted as Record<string, unknown>
  const mismatches: string[] = []
  for (const key of AGREE_FIELDS) {
    const fromView = view[key as keyof CaseStudyView]
    if (fromView !== api[key] || fromView !== stored[key]) {
      mismatches.push(key)
    }
  }
  return { agrees: mismatches.length === 0, mismatches }
}
