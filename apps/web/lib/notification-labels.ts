export type NotificationSeverity = 'high' | 'medium' | 'low'
export type NotificationCategory = 'compliance' | 'system' | 'team'

export type NotificationMeta = {
  title: string
  description: string
  severity: NotificationSeverity
  category: NotificationCategory
}

export const NOTIFICATION_LABELS: Record<string, NotificationMeta> = {
  'compliance.coverage_drop': {
    title: 'Coverage dropped below threshold',
    description: 'Your compliance coverage has fallen below the configured minimum.',
    severity: 'high',
    category: 'compliance',
  },
  'compliance.blind_spot': {
    title: 'Blind spots detected',
    description: 'Areas with no supporting evidence were found in your compliance coverage.',
    severity: 'high',
    category: 'compliance',
  },
  'compliance.high_insufficient': {
    title: 'High number of insufficient answers',
    description: 'Many questions lack sufficient evidence to meet compliance requirements.',
    severity: 'medium',
    category: 'compliance',
  },
  'compliance.weak_evidence': {
    title: 'Weak evidence areas',
    description: 'Some areas have low-confidence supporting evidence that may need attention.',
    severity: 'medium',
    category: 'compliance',
  },
  'questionnaire.uploaded': {
    title: 'Questionnaire uploaded',
    description: 'A new questionnaire has been uploaded and is ready for processing.',
    severity: 'low',
    category: 'system',
  },
  'questionnaire.generated': {
    title: 'Answers generated',
    description: 'AI-generated answers are ready for review.',
    severity: 'low',
    category: 'system',
  },
  'export.completed': {
    title: 'Export ready',
    description: 'Your requested export has finished and is available for download.',
    severity: 'low',
    category: 'system',
  },
  'document.indexed': {
    title: 'Document processed',
    description: 'A document has been indexed and is now searchable as evidence.',
    severity: 'low',
    category: 'system',
  },
  'member.invited': {
    title: 'Member invited',
    description: 'A new team member has been invited to the workspace.',
    severity: 'low',
    category: 'team',
  },
  'member.joined': {
    title: 'Member joined',
    description: 'A new team member has accepted their invitation and joined.',
    severity: 'low',
    category: 'team',
  },
  'member.removed': {
    title: 'Member removed',
    description: 'A team member has been removed from the workspace.',
    severity: 'medium',
    category: 'team',
  },
  'member.suspended': {
    title: 'Member suspended',
    description: 'A team member\'s access has been suspended.',
    severity: 'medium',
    category: 'team',
  },
  'member.role_changed': {
    title: 'Role changed',
    description: 'A team member\'s role has been updated.',
    severity: 'low',
    category: 'team',
  },
  'role.created': {
    title: 'Role created',
    description: 'A new custom role has been created.',
    severity: 'low',
    category: 'team',
  },
  'role.updated': {
    title: 'Role updated',
    description: 'A custom role\'s permissions have been updated.',
    severity: 'low',
    category: 'team',
  },
  'role.deleted': {
    title: 'Role deleted',
    description: 'A custom role has been removed.',
    severity: 'medium',
    category: 'team',
  },
  'slack.test': {
    title: 'Slack test sent',
    description: 'A test notification was sent to Slack.',
    severity: 'low',
    category: 'system',
  },
}

export const CATEGORY_META: Record<NotificationCategory, { label: string; icon: string }> = {
  compliance: { label: 'Compliance Alerts', icon: '🛡' },
  system:     { label: 'System Events',     icon: '⚙' },
  team:       { label: 'Team Activity',     icon: '👥' },
}

const FALLBACK: NotificationMeta = {
  title: 'System Notification',
  description: 'A system event occurred.',
  severity: 'low',
  category: 'system',
}

export function getNotificationMeta(eventType: string): NotificationMeta {
  return NOTIFICATION_LABELS[eventType] ?? FALLBACK
}

export function getNotificationTitle(eventType: string): string {
  return NOTIFICATION_LABELS[eventType]?.title ?? FALLBACK.title
}

export function getNotificationCategory(eventType: string): NotificationCategory {
  return NOTIFICATION_LABELS[eventType]?.category ?? FALLBACK.category
}
