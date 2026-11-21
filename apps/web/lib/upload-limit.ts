/**
 * Upload cap shared with the API setting MAX_UPLOAD_BYTES.
 * The default is 50 MiB (52428800), the same number as apps/api Settings.
 * Bracket access stays a runtime read so a production env value is not baked
 * in at build time.
 */

export const DEFAULT_MAX_UPLOAD_BYTES = 50 * 1024 * 1024

export class UploadTooLargeError extends Error {
  constructor() {
    super('upload exceeds the configured limit')
    this.name = 'UploadTooLargeError'
  }
}

export function maxUploadBytes(): number {
  const raw = process.env['MAX_UPLOAD_BYTES']
  if (raw == null || raw.trim() === '') return DEFAULT_MAX_UPLOAD_BYTES
  if (!/^[0-9]+$/.test(raw.trim())) return 0
  const parsed = Number(raw.trim())
  if (!Number.isSafeInteger(parsed) || parsed <= 0) return 0
  return parsed
}

export function uploadLimitDetail(maxBytes: number): string {
  const mib = Math.floor(maxBytes / (1024 * 1024))
  if (mib > 0 && mib * 1024 * 1024 === maxBytes) {
    return `File exceeds max size (${mib}MB)`
  }
  return `File exceeds max size (${maxBytes} bytes)`
}

export function isUploadTooLarge(err: unknown): boolean {
  if (err instanceof UploadTooLargeError) return true
  if (err && typeof err === 'object' && 'cause' in err) {
    return isUploadTooLarge((err as { cause?: unknown }).cause)
  }
  return false
}

/** Forward the body, and stop without enqueueing the chunk that crosses the cap. */
export function limitRequestBody(
  source: ReadableStream<Uint8Array>,
  maxBytes: number
): ReadableStream<Uint8Array> {
  const reader = source.getReader()
  let seen = 0
  return new ReadableStream<Uint8Array>({
    async pull(controller) {
      const { done, value } = await reader.read()
      if (done) {
        controller.close()
        return
      }
      if (seen + value.byteLength > maxBytes) {
        await reader.cancel()
        controller.error(new UploadTooLargeError())
        return
      }
      seen += value.byteLength
      controller.enqueue(value)
    },
    cancel(reason) {
      return reader.cancel(reason)
    },
  })
}
