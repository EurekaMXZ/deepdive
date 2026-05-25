export type AnalysisThreadScrollMetrics = {
  clientHeight: number
  scrollHeight: number
  scrollTop: number
}

export const ANALYSIS_THREAD_BOTTOM_THRESHOLD = 24

export function isAnalysisThreadAtBottom(
  metrics: AnalysisThreadScrollMetrics,
  threshold = ANALYSIS_THREAD_BOTTOM_THRESHOLD,
): boolean {
  return metrics.scrollHeight - metrics.scrollTop - metrics.clientHeight <= threshold
}
