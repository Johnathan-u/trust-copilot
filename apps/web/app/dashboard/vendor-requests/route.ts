export function GET() {
  // The outbound view consumes no URL query parameters. Redirect before the
  // dashboard's client auth shell renders, including on direct bookmarks.
  return new Response(null, {
    status: 307,
    headers: { Location: '/dashboard/requests' },
  })
}
