// Detailed views retain the capture identity in copied links and browser history.
export function resolveTaskContext(to, store) {
  if (to.name === 'task') store.setCurrent(Number(to.params.id))
  if (['sip', 'media', 'diagnostics', 'packets'].includes(to.name)) {
    if (!to.query.task && store.currentTaskId) {
      return { path: to.path, query: { ...to.query, task: store.currentTaskId }, hash: to.hash }
    }
    const id = Number(to.query.task)
    if (Number.isSafeInteger(id) && id > 0) store.setCurrent(id)
    else return { name: 'tasks' }
  }
}
