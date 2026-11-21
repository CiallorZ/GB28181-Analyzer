export function inviteLatency(phases) {
  const invite = phases.find(p => p.label === 'INVITE')
  const response = phases.find(p => p.inviteResponse)
  if (!invite || !response || invite.t == null || response.t == null || response.t < invite.t) return null
  return +(response.t - invite.t).toFixed(3)
}
