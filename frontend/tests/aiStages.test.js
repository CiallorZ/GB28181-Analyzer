import { describe, expect, it } from 'vitest'
import { AI_STEPS, resolvePhase, stepIndexFor } from '../src/utils/aiStages.js'

describe('resolvePhase', () => {
  it('配置页优先，即便已有报告', () => {
    expect(resolvePhase({ view: 'config', report: 'x', previewOpen: false })).toBe('config')
  })

  it('已有报告时进入结果阶段', () => {
    expect(resolvePhase({ view: 'flow', report: '# 结论', previewOpen: false })).toBe('result')
  })

  it('确认发送优先于选择专家', () => {
    expect(resolvePhase({ view: 'flow', report: '', previewOpen: true })).toBe('preview')
  })

  it('重新分析时允许旧报告先返回发送确认', () => {
    expect(resolvePhase({ view: 'flow', report: '# 旧报告', previewOpen: true })).toBe('preview')
  })

  it('首个流式片段之前已经进入报告阶段', () => {
    expect(resolvePhase({ view: 'flow', report: '', previewOpen: false, running: true })).toBe('result')
  })

  it('默认停留在选择专家', () => {
    expect(resolvePhase({ view: 'flow', report: '', previewOpen: false })).toBe('choose')
  })
})

describe('stepIndexFor', () => {
  it('三个业务阶段对应 0/1/2', () => {
    expect(stepIndexFor('choose')).toBe(0)
    expect(stepIndexFor('preview')).toBe(1)
    expect(stepIndexFor('result')).toBe(2)
  })

  it('配置阶段不显示进度条，索引回落到 0', () => {
    expect(stepIndexFor('config')).toBe(0)
  })

  it('步骤标签与进度条数量一致', () => {
    expect(AI_STEPS).toHaveLength(3)
  })
})

