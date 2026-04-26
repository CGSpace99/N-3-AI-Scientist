import { NextRequest } from 'next/server'

const API_URL = process.env.API_URL || 'http://localhost:8000'

export async function POST(req: NextRequest) {
  try {
    const body = await req.json()
    const response = await fetch(`${API_URL}/api/frontend/chat/faith`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    const payload = await response.text()
    const contentType = response.headers.get('content-type') || ''
    if (contentType.includes('application/json')) {
      return new Response(payload, {
        status: response.status,
        headers: { 'Content-Type': 'application/json' },
      })
    }
    return Response.json(
      { detail: payload || 'Backend returned a non-JSON error response.' },
      { status: response.status },
    )
  } catch (error) {
    return Response.json(
      { detail: `Failed to reach backend Faith endpoint: ${String(error)}` },
      { status: 502 },
    )
  }
}
