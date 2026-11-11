/**
 * Browser client for the question-to-control mapping routes.
 * Responses are accepted only after the reader validates them.
 */

import {
  mappingSuggestPath,
  parseMappingDecision,
  parseMappingSuggestion,
  type MappingDecision,
  type MappingSuggestion,
} from './controlMappingConsumer'
import { readSectionJson } from './section-load'

export async function fetchMappingSuggestion(
  question: string,
  signal?: AbortSignal
): Promise<MappingSuggestion> {
  const response = await fetch(mappingSuggestPath(question), {
    credentials: 'include',
    cache: 'no-store',
    signal,
  })
  return parseMappingSuggestion(await readSectionJson(response))
}

export async function postMappingDecision(
  action: 'confirm' | 'override' | 'rollback',
  body: { question: string; control_ids?: number[]; rationale?: string },
  idempotencyKey: string,
  signal?: AbortSignal
): Promise<MappingDecision> {
  const response = await fetch(`/api/compliance/control-mappings/${action}`, {
    method: 'POST',
    credentials: 'include',
    cache: 'no-store',
    signal,
    headers: {
      'Content-Type': 'application/json',
      'Idempotency-Key': idempotencyKey,
    },
    body: JSON.stringify(body),
  })
  return parseMappingDecision(await readSectionJson(response))
}
