/**
 * Verb forms for a confirmed action.
 *
 * The idle label is the bare verb. The pending label is the same verb in
 * progress. The success label is the past form and is only for a response
 * the server has already accepted. Pending copy never uses the success form
 * or the word "Done".
 */

export const CONFIRMED_ACTIONS = [
  'save',
  'upload',
  'generate',
  'export',
  'approve',
] as const

export type ConfirmedAction = (typeof CONFIRMED_ACTIONS)[number]

export type ActionPhase = 'idle' | 'pending' | 'success'

export const ACTION_VERBS: Record<
  ConfirmedAction,
  Record<ActionPhase, string>
> = {
  save: { idle: 'Save', pending: 'Saving', success: 'Saved' },
  upload: { idle: 'Upload', pending: 'Uploading', success: 'Uploaded' },
  generate: { idle: 'Generate', pending: 'Generating', success: 'Generated' },
  export: { idle: 'Export', pending: 'Exporting', success: 'Exported' },
  approve: { idle: 'Approve', pending: 'Approving', success: 'Approved' },
}

/** Detail shown with a success title. It does not claim why the result is correct. */
export const ACTION_SUCCESS_DETAIL: Record<ConfirmedAction, string> = {
  save: 'The change is stored.',
  upload: 'The file is stored.',
  generate: 'Draft answers are ready to review.',
  export: 'The file is ready to download.',
  approve: 'The selected answers are marked approved.',
}

export function actionVerb(
  action: ConfirmedAction,
  phase: ActionPhase
): string {
  return ACTION_VERBS[action][phase]
}

export function confirmedActionNotice(action: ConfirmedAction): {
  title: string
  message: string
} {
  return {
    title: actionVerb(action, 'success'),
    message: ACTION_SUCCESS_DETAIL[action],
  }
}

export type RowSavePhase = 'saving' | 'saved' | 'approving' | 'approved'

/** Row label for an answer that has not yet been confirmed, or for one that has. */
export function rowSaveLabel(phase: RowSavePhase | undefined): string {
  if (phase === 'saving') return actionVerb('save', 'pending')
  if (phase === 'saved') return actionVerb('save', 'success')
  if (phase === 'approving') return actionVerb('approve', 'pending')
  if (phase === 'approved') return actionVerb('approve', 'success')
  return 'Not saved yet'
}
