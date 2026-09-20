export function formatTime(ts?: string | null): string {
  if (!ts) return ''
  try {
    const hasTz = ts.endsWith('Z') || /[+-]\d{2}:?\d{2}$/.test(ts)
    const cleanTs = hasTz ? ts : ts.replace(/\.\d+$/, '')
    const d = new Date(cleanTs)
    if (isNaN(d.getTime())) return ''
    return d.toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    })
  } catch {
    return ''
  }
}

export function timePrefix(): string {
  return new Date().toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
}