#!/usr/bin/env node
/**
 * Fail the release e2e job unless the Playwright JSON report and the
 * design-tokens axe JSON agree on a clean run.
 *
 * Reads synthetic gate output only (test titles, counts, axe ids). Does not
 * print page content. No dependencies beyond Node.
 *
 *   node scripts/ci/check-release-e2e-report.mjs \
 *     --report apps/web/test-results/release-e2e.json \
 *     --axe-dir artifacts/acceptance/TC-14-001 \
 *     --html-report apps/web/playwright-report \
 *     --require-spec e2e/release/design-tokens.spec.ts \
 *     --min-tests 4
 */
import { existsSync, readFileSync, readdirSync } from 'node:fs'
import path from 'node:path'

// Theme and viewport pairs the design-tokens spec analyzes. A later release
// spec that writes more axe-*.json files into the same directory is checked
// too: any violationCount above zero fails the job.
const REQUIRED_AXE = [
  ['dark', 360],
  ['dark', 768],
  ['dark', 1440],
  ['light', 360],
  ['light', 768],
  ['light', 1440],
]

function arg(name) {
  const index = process.argv.indexOf(name)
  const value = index === -1 ? undefined : process.argv[index + 1]
  if (!value || value.startsWith('--')) {
    console.error('missing ' + name)
    process.exit(2)
  }
  return value
}

function walkSpecs(suite, acc) {
  if (!suite || typeof suite !== 'object') return
  for (const spec of suite.specs || []) acc.push(spec)
  for (const child of suite.suites || []) walkSpecs(child, acc)
}

function specFile(spec) {
  return String(spec.file || '').replaceAll('\\', '/')
}

// Playwright's JSON report stores paths relative to the test directory
// (`release/design-tokens.spec.ts`). The workflow passes the path from
// apps/web (`e2e/release/design-tokens.spec.ts`). Either form may contain the other.
function sameSpec(reported, required) {
  if (!reported || !required) return false
  if (reported === required) return true
  return reported.endsWith('/' + required) || required.endsWith('/' + reported)
}

function countStatus(specs) {
  const counts = { expected: 0, unexpected: 0, skipped: 0, flaky: 0 }
  for (const spec of specs) {
    const tests = Array.isArray(spec.tests) && spec.tests.length > 0 ? spec.tests : [spec]
    for (const test of tests) {
      const status = test.status || (spec.ok === false ? 'unexpected' : 'expected')
      if (Object.prototype.hasOwnProperty.call(counts, status)) counts[status] += 1
      else counts.unexpected += 1
    }
  }
  return counts
}

const errors = []
function fail(message) {
  errors.push(message)
  console.error('ERROR: ' + message)
}

const reportPath = path.resolve(arg('--report'))
const axeDir = path.resolve(arg('--axe-dir'))
const htmlReport = path.resolve(arg('--html-report'))
const requireSpec = arg('--require-spec').replaceAll('\\', '/')
const minTests = Number(arg('--min-tests'))
if (!Number.isInteger(minTests) || minTests < 1) {
  console.error('ERROR: min-tests must be a positive integer')
  process.exit(2)
}

if (!existsSync(reportPath)) {
  console.error('ERROR: missing Playwright JSON report: ' + reportPath)
  process.exit(1)
}
const htmlIndex = path.join(htmlReport, 'index.html')
if (!existsSync(htmlIndex)) fail('missing Playwright HTML report: ' + htmlIndex)

const report = JSON.parse(readFileSync(reportPath, 'utf8'))
const specs = []
for (const suite of report.suites || []) walkSpecs(suite, specs)
const design = specs.filter((spec) => sameSpec(specFile(spec), requireSpec))
const counts = countStatus(design)

if (design.length === 0) fail('spec did not run: ' + requireSpec)
if (counts.unexpected !== 0) fail(requireSpec + ' has ' + counts.unexpected + ' failed test(s)')
if (counts.skipped !== 0) fail(requireSpec + ' has ' + counts.skipped + ' skipped test(s)')
if (counts.flaky !== 0) fail(requireSpec + ' has ' + counts.flaky + ' flaky test(s)')
if (counts.expected < minTests) {
  fail(requireSpec + ' passed ' + counts.expected + ' test(s); expected at least ' + minTests)
}

const stats = report.stats || {}
const overallFailed = Number(stats.unexpected || 0)
const overallSkipped = Number(stats.skipped || 0)
if (overallFailed !== 0) fail('Playwright report has ' + overallFailed + ' failed test(s)')
if (overallSkipped !== 0) fail('Playwright report has ' + overallSkipped + ' skipped test(s)')

let violations = 0
if (!existsSync(axeDir)) {
  fail('missing axe directory: ' + axeDir)
} else {
  const axeFiles = readdirSync(axeDir)
    .filter((name) => /^axe-.*\.json$/.test(name))
    .sort()
  const seen = new Map()
  for (const name of axeFiles) {
    let data
    try {
      data = JSON.parse(readFileSync(path.join(axeDir, name), 'utf8'))
    } catch (err) {
      fail(name + ' is not JSON (' + err.message + ')')
      continue
    }
    const count = data.violationCount
    const listed = Array.isArray(data.violations) ? data.violations : null
    if (!Number.isInteger(count) || count < 0 || !listed || listed.length !== count) {
      fail(name + ' is not a usable axe report')
      continue
    }
    violations += count
    seen.set(String(data.theme) + ':' + String(data.viewport), name)
    if (count === 0) {
      console.log(name + ': 0 violations')
    } else {
      const detail = listed
        .map((item) => String((item && item.id) || 'unknown') + ':' + String((item && item.impact) || 'unknown'))
        .join(', ')
      console.log(name + ': ' + count + ' violations ' + detail)
      fail(name + ' has ' + count + ' axe violation(s)')
    }
  }
  for (const [theme, viewport] of REQUIRED_AXE) {
    const key = theme + ':' + viewport
    if (!seen.has(key)) fail('missing axe report for ' + key)
  }
}

const specLabel = requireSpec.slice(requireSpec.lastIndexOf('/') + 1)
console.log(
  specLabel +
    ': ' +
    counts.expected +
    ' passed, ' +
    counts.unexpected +
    ' failed, ' +
    counts.skipped +
    ' skipped, ' +
    counts.flaky +
    ' flaky, ' +
    violations +
    ' axe violations'
)

if (errors.length > 0) process.exit(1)
