import { describe, expect, it } from 'vitest'
import { esc, renderMd } from '../src/utils/markdown.js'

describe('esc', () => {
  it('转义 HTML 特殊字符', () => {
    expect(esc('<script>"x"&\'y\'</script>'))
      .toBe('&lt;script&gt;&quot;x&quot;&amp;&#39;y&#39;&lt;/script&gt;')
  })
})

describe('renderMd', () => {
  it('渲染标题与段落', () => {
    expect(renderMd('# 标题\n正文')).toBe('<h2>标题</h2><p>正文</p>')
  })

  it('渲染无序列表', () => {
    expect(renderMd('- a\n- b')).toBe('<ul><li>a</li><li>b</li></ul>')
  })

  it('渲染表格并跳过对齐行', () => {
    const html = renderMd('| 项 | 值 |\n|---|---|\n| A | 1 |')
    expect(html).toContain('<th>项</th>')
    expect(html).toContain('<td>1</td>')
    expect(html.match(/<tr>/g)).toHaveLength(2)
  })

  it('渲染代码块且转义内容', () => {
    expect(renderMd('```\n<script>\n```'))
      .toBe('<pre><code>&lt;script&gt;</code></pre>')
  })

  it('不把用户文本当 HTML 执行', () => {
    const html = renderMd('<img src=x onerror=alert(1)>')
    expect(html).not.toContain('<img')
    expect(html).toContain('&lt;img')
  })

  it('行内代码优先于粗体', () => {
    expect(renderMd('`**x**`')).toBe('<p><code>**x**</code></p>')
  })
})
