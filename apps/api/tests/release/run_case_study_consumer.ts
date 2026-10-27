/** Compare one API body with the persisted projection. Used by TC-25-005. */

import { outcomesAgree, parseCaseStudyResponse } from "../../../web/lib/caseStudyConsumer.ts"

function readStdin(): Promise<string> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = []
    process.stdin.on("data", (chunk) => chunks.push(Buffer.from(chunk)))
    process.stdin.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")))
    process.stdin.on("error", reject)
  })
}

const raw = await readStdin()
const payload = JSON.parse(raw) as { api?: unknown; persisted?: unknown }
const view = parseCaseStudyResponse(payload.api)
const agreement = outcomesAgree(payload.api, payload.persisted)
process.stdout.write(JSON.stringify({ view, ...agreement }))
