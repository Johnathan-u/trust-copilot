/**
 * Print one Playwright JSON-report stat for the CI evidence block.
 * Missing files and unreadable JSON print 0. No report body is written.
 *
 *   node scripts/ci/read-playwright-stat.mjs <report.json> <field>
 */
import { readFileSync } from 'node:fs'

const file = process.argv[2]
const field = process.argv[3]
let value = 0
try {
  const stats = JSON.parse(readFileSync(file, 'utf8')).stats || {}
  value = Number(stats[field] || 0)
} catch {
  value = 0
}
if (!Number.isFinite(value)) value = 0
process.stdout.write(String(value))
