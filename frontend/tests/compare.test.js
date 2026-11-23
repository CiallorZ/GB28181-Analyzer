import { describe, expect, it } from 'vitest'
import { allowedLink, fieldName, formatValue, groups, judgments } from '../src/utils/compare'

describe('两侧观测值', () => {
  it.each([
    [null, '未知'], [undefined, '未知'], ['', '未知'], ['unknown', '未知'],
    [0, '0'], [false, '否'], [true, '是'], [10.1, '10.1'], ['H264', 'H264']
  ])('格式化 %s 为 %s', (input, expected) => expect(formatValue(input)).toBe(expected))

  it.each([
    ['same', '一致'], ['different', '不同'], ['only_a', '仅 A 侧观察到'],
    ['only_b', '仅 B 侧观察到'], ['unknown', '无法比较'], ['ambiguous', '存在歧义']
  ])('%s 有独立文字判定', (code, expected) => expect(judgments[code]).toBe(expected))

  it('标出毫秒与秒的单位', () => {
    expect(fieldName('jitter_avg')).toContain('ms')
    expect(fieldName('media_duration')).toContain('秒')
  })
  it.each([['sessions','negotiated_port','SDP 协商'], ['sessions','signal_status','信令与会话'],
    ['streams','codec','编码与重建'], ['streams','max_gap','媒体传输']])(
    '%s.%s 只属于 %s', (layer, field, name) => {
      expect(groups.filter(([,key,accept]) => key === layer && accept(field)).map(([n]) => n)).toEqual([name])
    })
})

describe('证据跳转', () => {
  const links = {a:{sessions:[17], packets:true}, b:{sessions:[22], packets:false}}
  it('按本侧会话和报文可用性控制', () => {
    expect(allowedLink({links},'a',17)).toBe(true)
    expect(allowedLink({links},'b',17)).toBe(false)
    expect(allowedLink({links},'b',null)).toBe(false)
    expect(allowedLink({links},'a',null)).toBe(true)
  })
  it('过期后关闭两类跳转', () => {
    for (const target of [17,null]) expect(allowedLink({links,stale:true},'a',target)).toBe(false)
  })
})
