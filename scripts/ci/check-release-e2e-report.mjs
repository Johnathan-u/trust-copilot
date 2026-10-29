#!/usr/bin/env node
/**
 * Fail the release e2e job unless the Playwright JSON report and every
 * listed axe directory agree on a clean run.
 *
 * Reads synthetic gate output only (test titles, counts, axe ids). Does not
 * print page content. No dependencies beyond Node.
 *
 * Repeat --require-spec with a matching --min-tests, in the same order.
 * Repeat --axe-dir once per spec that writes axe-*.json. Any violation, or a
 * required spec that did not run, fails the process.
 *
 *   node scripts/ci/check-release-e2e-report.mjs \
 *     --report apps/web/test-results/release-e2e.json \
 *     --html-report apps/web/playwright-report \
 *     --axe-dir artifacts/acceptance/TC-14-001 \
 *     --axe-dir artifacts/acceptance/TC-14-006 \
 *     --axe-dir artifacts/acceptance/TC-14-003a \
 *     --axe-dir artifacts/acceptance/TC-16-BUG-001 \
 *     --axe-dir artifacts/acceptance/TC-14-006b \
 *     --axe-dir artifacts/acceptance/TC-14-005 \
 *     --axe-dir artifacts/acceptance/TC-04-001a-web \
 *     --require-spec e2e/release/design-tokens.spec.ts --min-tests 4 \
 *     --require-spec e2e/release/responsive-shell.spec.ts --min-tests 8 \
 *     --require-spec e2e/release/dialog-toast.spec.ts --min-tests 8 \
 *     --require-spec e2e/release/settings-access.spec.ts --min-tests 3 \
 *     --require-spec e2e/release/state-components.spec.ts --min-tests 9 \
 *     --require-spec e2e/release/drawer-followups.spec.ts --min-tests 3 \
 *     --require-spec e2e/release/workspace-create-denied.spec.ts --min-tests 8
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
  const values = args(name)
  return values[values.length - 1]
}

function args(name) {
  const values = []
  for (let i = 2; i < process.argv.length; i += 1) {
    if (process.argv[i] !== name) continue
    const value = process.argv[i + 1]
    if (!value || value.startsWith('--')) {
      console.error('missing ' + name)
      process.exit(2)
    }
    values.push(value)
    i += 1
  }
  if (values.length === 0) {
    console.error('missing ' + name)
    process.exit(2)
  }
  return values
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
const axeDirs = args('--axe-dir').map((dir) => path.resolve(dir))
const htmlReport = path.resolve(arg('--html-report'))
const requireSpecs = args('--require-spec').map((spec) => spec.replaceAll('\\', '/'))
const minTests = args('--min-tests').map((value) => Number(value))
if (requireSpecs.length !== minTests.length) {
  console.error('ERROR: each --require-spec needs its own --min-tests')
  process.exit(2)
}
for (const count of minTests) {
  if (!Number.isInteger(count) || count < 1) {
    console.error('ERROR: min-tests must be a positive integer')
    process.exit(2)
  }
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

requireSpecs.forEach((requireSpec, index) => {
  const matched = specs.filter((spec) => sameSpec(specFile(spec), requireSpec))
  const counts = countStatus(matched)
  const floor = minTests[index]
  if (matched.length === 0) {
    fail('spec did not run: ' + requireSpec)
    return
  }
  if (counts.unexpected !== 0) fail(requireSpec + ' has ' + counts.unexpected + ' failed test(s)')
  if (counts.skipped !== 0) fail(requireSpec + ' has ' + counts.skipped + ' skipped test(s)')
  if (counts.flaky !== 0) fail(requireSpec + ' has ' + counts.flaky + ' flaky test(s)')
  if (counts.expected < floor) {
    fail(requireSpec + ' passed ' + counts.expected + ' test(s); expected at least ' + floor)
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
      ' flaky'
  )
})

const stats = report.stats || {}
const overallFailed = Number(stats.unexpected || 0)
const overallSkipped = Number(stats.skipped || 0)
if (overallFailed !== 0) fail('Playwright report has ' + overallFailed + ' failed test(s)')
if (overallSkipped !== 0) fail('Playwright report has ' + overallSkipped + ' skipped test(s)')

let violations = 0
for (const axeDir of axeDirs) {
  if (!existsSync(axeDir)) {
    fail('missing axe directory: ' + axeDir)
    continue
  }
  const axeFiles = readdirSync(axeDir)
    .filter((name) => /^axe-.*\.json$/.test(name))
    .sort()
  if (axeFiles.length === 0) {
    fail('no axe reports in ' + axeDir)
    continue
  }
  const seen = new Map()
  let themed = false
  for (const name of axeFiles) {
    const label = path.join(path.basename(axeDir), name)
    let data
    try {
      data = JSON.parse(readFileSync(path.join(axeDir, name), 'utf8'))
    } catch (err) {
      fail(label + ' is not JSON (' + err.message + ')')
      continue
    }
    const count = data.violationCount
    const listed = Array.isArray(data.violations) ? data.violations : null
    if (!Number.isInteger(count) || count < 0 || !listed || listed.length !== count) {
      fail(label + ' is not a usable axe report')
      continue
    }
    violations += count
    if (data.theme != null && data.viewport != null) {
      themed = true
      seen.set(String(data.theme) + ':' + String(data.viewport), name)
    }
    if (count === 0) {
      console.log(label + ': 0 violations')
    } else {
      const detail = listed
        .map((item) => String((item && item.id) || 'unknown') + ':' + String((item && item.impact) || 'unknown'))
        .join(', ')
      console.log(label + ': ' + count + ' violations ' + detail)
      fail(label + ' has ' + count + ' axe violation(s)')
    }
  }
  if (themed) {
    for (const [theme, viewport] of REQUIRED_AXE) {
      const key = theme + ':' + viewport
      if (!seen.has(key)) fail('missing axe report for ' + key + ' in ' + axeDir)
    }
  }
}

console.log('axe violations: ' + violations)
if (errors.length > 0) process.exit(1)
