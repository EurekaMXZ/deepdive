export function getTimeAwareGreeting(now = new Date()): string {
  const hour = now.getHours()

  if (hour >= 5 && hour < 12) {
    return '早上好，今天你想探索什么？'
  }

  if (hour >= 12 && hour < 18) {
    return '下午好，今天你想探索什么？'
  }

  return '晚上好，今天你想探索什么？'
}
