/**
 * UI consumer for the public security page (schema version 2, TC-17-003).
 * The dashboard page imports this module. Release tests execute the same file
 * against real API responses.
 *
 * Fail-safe rule: a certification is shown as attested, and a contact detail as
 * available, only when the API also lists a matching verified claim backed by a
 * proof reference. Anything else is shown with the conservative wording.
 * Infrastructure lines are rendered as the API words them: the API words a line
 * as verified only while its claim's proof is current.
 */

export const SECURITY_PAGE_SCHEMA_VERSION = 2

const REASON_LABELS = {
  verified: 'Verified with approved evidence',
  not_claimed: 'Not claimed',
  proof_unavailable: 'Proof is missing or no longer approved',
  value_unavailable: 'No valid value is approved',
}

function text(value) {
  return typeof value === 'string' ? value : ''
}

function emptyPage(state, reason) {
  return {
    state,
    reason,
    title: 'Security & Data Handling',
    subtitle: '',
    notice: '',
    certifications: [],
    highlights: [],
    contact: {
      securityEmail: null,
      dpaAvailable: false,
      subprocessorListAvailable: false,
    },
    sections: [],
  }
}

function verifiedClaims(payload) {
  const claims = Array.isArray(payload.claims) ? payload.claims : []
  const byName = new Map()
  const byKey = new Map()
  for (const claim of claims) {
    if (!claim || typeof claim !== 'object' || claim.verified !== true) continue
    byName.set(claim.name, claim)
    byKey.set(claim.key, claim)
  }
  return { byName, byKey }
}

function hasProof(proof) {
  return (
    !!proof &&
    typeof proof === 'object' &&
    Number.isInteger(proof.evidence_item_id) &&
    proof.evidence_item_id > 0
  )
}

export function presentSecurityPage(payload) {
  if (!payload || typeof payload !== 'object') {
    return emptyPage('unavailable', 'The security page response was empty.')
  }
  if (payload.schema_version !== SECURITY_PAGE_SCHEMA_VERSION) {
    return emptyPage(
      'unsupported_schema',
      'This screen reads security page schema version 2 only.'
    )
  }
  const verified = verifiedClaims(payload)
  const certifications = (
    Array.isArray(payload.certifications) ? payload.certifications : []
  )
    .filter((item) => item && typeof item === 'object')
    .map((item) => {
      const claim = verified.byName.get(item.name)
      const attested =
        item.status === 'attested' &&
        hasProof(item.proof) &&
        !!claim &&
        hasProof(claim.proof) &&
        claim.proof.evidence_item_id === item.proof.evidence_item_id
      return {
        name: text(item.name),
        attested,
        label: attested ? 'Attested' : 'Not attested',
        description: text(item.description),
        proofTitle: attested ? text(item.proof.title) : null,
      }
    })
  const highlights = (
    Array.isArray(payload.infrastructure_highlights)
      ? payload.infrastructure_highlights
      : []
  ).filter((item) => typeof item === 'string')
  const contact =
    payload.contact && typeof payload.contact === 'object'
      ? payload.contact
      : {}
  const contactClaim = verified.byKey.get('security_contact')
  const securityEmail =
    contactClaim &&
    typeof contact.security_email === 'string' &&
    contact.security_email === contactClaim.value
      ? contact.security_email
      : null
  return {
    state: 'ready',
    reason: null,
    title: text(payload.title) || 'Security & Data Handling',
    subtitle: text(payload.subtitle),
    notice: text(payload.notice),
    certifications,
    highlights,
    contact: {
      securityEmail,
      dpaAvailable: contact.dpa_available === true && verified.byKey.has('dpa'),
      subprocessorListAvailable:
        contact.subprocessor_list_available === true &&
        verified.byKey.has('subprocessor_list'),
    },
    sections: Array.isArray(payload.sections) ? payload.sections : [],
  }
}

export function presentClaims(payload) {
  if (!payload || typeof payload !== 'object') {
    return {
      state: 'unavailable',
      reason: 'No claims were returned.',
      rows: [],
    }
  }
  if (payload.schema_version !== SECURITY_PAGE_SCHEMA_VERSION) {
    return {
      state: 'unsupported_schema',
      reason: 'This screen reads security page schema version 2 only.',
      rows: [],
    }
  }
  const rows = (Array.isArray(payload.claims) ? payload.claims : [])
    .filter((item) => item && typeof item === 'object')
    .map((item) => ({
      key: text(item.key),
      name: text(item.name),
      group: text(item.group),
      status: item.status === 'claimed' ? 'claimed' : 'not_claimed',
      verified: item.verified === true,
      reasonLabel: REASON_LABELS[item.reason] || 'Unknown state',
      revision: Number.isInteger(item.revision) ? item.revision : 0,
      statement: text(item.stored_statement),
      value: text(item.stored_value),
      evidenceItemId: Number.isInteger(item.evidence_item_id)
        ? item.evidence_item_id
        : null,
      proofRequired: item.proof_required !== false,
    }))
  return { state: 'ready', reason: null, rows }
}
