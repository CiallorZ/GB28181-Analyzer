/**
 * 会诊流程的阶段判定
 *
 * 面板里"当前该显示哪一屏"和"进度条走到第几步"是同一份状态的两个视图，
 * 抽出来单独测，避免以后调整顺序时两边不一致。
 */

export const AI_STEPS = ['选择专家', '确认发送', '研判报告']

export function resolvePhase({ view, report, previewOpen }) {
  if (view === 'config') return 'config'
  if (report) return 'result'
  if (previewOpen) return 'preview'
  return 'choose'
}

export function stepIndexFor(phase) {
  return { choose: 0, preview: 1, result: 2 }[phase] ?? 0
}

