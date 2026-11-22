/**
 * Print one Playwright JSON-report stat for the CI evidence block.
 * A missing or unparsable report exits non-zero and prints nothing.
 * No report body is written.
 *
 *   node scripts/ci/read-playwright-stat.mjs <report.json> <field>
 */
import { readFileSync } from 'node:fs'

const file = process.argv[2]
const field = process.argv[3]
if (!file || !field) {
  process.stderr.write('missing report path or field\n')
  process.exit(2)
}

let text
try {
  text = readFileSync(file, 'utf8')
} catch {
  process.stderr.write('missing report\n')
  process.exit(1)
}

let parsed
try {
  parsed = JSON.parse(text)
} catch {
  process.stderr.write('unreadable report\n')
  process.exit(1)
}

const stats = parsed && parsed.stats
if (!stats || typeof stats !== 'object') {
  process.stderr.write('unreadable report\n')
  process.exit(1)
}

const value = Number(stats[field] ?? 0)
if (!Number.isFinite(value)) {
  process.stderr.write('unreadable report\n')
  process.exit(1)
}
process.stdout.write(String(value))
