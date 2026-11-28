import { expect, it, vi } from 'vitest'
import { resolveTaskContext } from '../src/router/taskNavigation'

const store = (currentTaskId = null) => ({ currentTaskId, setCurrent: vi.fn() })
it('首页独立于上次打开的任务', () => {
  const tasks = store(17)
  expect(resolveTaskContext({name:'workbench'}, tasks)).toBeUndefined()
  expect(tasks.setCurrent).not.toHaveBeenCalled()
})
it.each(['sip', 'media', 'diagnostics', 'packets', 'insight'])('%s 保留来源任务和已有定位参数', name => {
  const route = {name, path:'/'+name, query:{number:'24'}, hash:'#detail'}
  expect(resolveTaskContext(route, store(17))).toEqual({
    path:route.path, query:{number:'24',task:17}, hash:route.hash
  })
})
it('显式任务覆盖之前打开的抓包', () => {
  const tasks = store(12)
  resolveTaskContext({name:'packets', query:{task:'17'}}, tasks)
  expect(tasks.setCurrent).toHaveBeenCalledWith(17)
})
it('缺少或无效的抓包上下文回到任务列表', () => {
  for (const task of [undefined, 'abc', '-2']) {
    expect(resolveTaskContext({name:'sip', query:{task}}, store())).toEqual({name:'tasks'})
  }
})
