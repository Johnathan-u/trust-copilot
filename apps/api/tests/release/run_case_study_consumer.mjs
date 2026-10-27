/** Run the web case-study consumer on Node 20 and Node 22.

CI uses Node 20, which has no --experimental-strip-types. This loads the
TypeScript already installed for the web app, erases types, and executes
apps/web/lib/caseStudyConsumer.ts.
*/

import { createRequire } from "node:module"
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { dirname, join } from "node:path"
import { fileURLToPath, pathToFileURL } from "node:url"

const here = dirname(fileURLToPath(import.meta.url))
const webRoot = join(here, "../../../web")
const consumerPath = join(webRoot, "lib/caseStudyConsumer.ts")

function readStdin() {
  return new Promise((resolve, reject) => {
    const chunks = []
    process.stdin.on("data", (chunk) => chunks.push(chunk))
    process.stdin.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")))
    process.stdin.on("error", reject)
  })
}

const require = createRequire(pathToFileURL(join(webRoot, "package.json")))
let typescript
try {
  typescript = require("typescript")
} catch {
  process.stderr.write(
    "typescript is not installed under apps/web. Install web dependencies before this test.\n"
  )
  process.exit(1)
}

const compiled = typescript.transpileModule(readFileSync(consumerPath, "utf8"), {
  compilerOptions: {
    module: typescript.ModuleKind.ES2022,
    target: typescript.ScriptTarget.ES2022,
  },
  fileName: consumerPath,
})

const dir = mkdtempSync(join(tmpdir(), "tc25005-consumer-"))
try {
  const outFile = join(dir, "caseStudyConsumer.mjs")
  writeFileSync(outFile, compiled.outputText)
  const consumer = await import(pathToFileURL(outFile).href)
  const payload = JSON.parse(await readStdin())
  const view = consumer.parseCaseStudyResponse(payload.api)
  const agreement = consumer.outcomesAgree(payload.api, payload.persisted)
  process.stdout.write(JSON.stringify({ view, ...agreement }))
} finally {
  rmSync(dir, { recursive: true, force: true })
}
