import { describe, expect, it } from 'vitest'
import { inviteLatency } from '../src/utils/sipPhases'

describe('INVITE response latency', () => {
  it('does not use a BYE response when the INVITE response is missing', () => {
    expect(inviteLatency([{ label: 'INVITE', t: 0 }, { label: '200 OK', t: 5 }])).toBeNull()
  })
  it('uses the INVITE response and rejects missing or reversed timestamps', () => {
    expect(inviteLatency([{ label: 'INVITE', t: 0 }, { inviteResponse: true, t: 0.1234 }])).toBe(0.123)
    expect(inviteLatency([{ label: 'INVITE', t: 2 }, { inviteResponse: true, t: 1 }])).toBeNull()
    expect(inviteLatency([{ label: 'INVITE', t: null }, { inviteResponse: true, t: 1 }])).toBeNull()
  })
})
