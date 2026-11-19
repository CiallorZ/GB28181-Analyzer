/**
 * 极简 Markdown 渲染
 *
 * 只支持模型输出会用到的语法：标题、列表、加粗、行内代码、表格、代码块。
 * 所有文本先 esc() 转义，避免 XSS。
 */

export function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]))
}

function inline(s) {
  let t = esc(s)
  // 行内代码优先（避免其中的 * 被当粗体）
  const codes = []
  t = t.replace(/`([^`]+)`/g, (_, c) => {
    codes.push(c)
    return `\uE000C${codes.length - 1}\uE001`
  })
  t = t.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
  t = t.replace(/(?<!\*)\*([^*\n]+)\*(?!\*)/g, '<em>$1</em>')
  t = t.replace(/\uE000C(\d+)\uE001/g, (_, i) => `<code>${codes[+i]}</code>`)
  return t
}

export function renderMd(text) {
  const lines = String(text || '').split('\n')
  const out = []
  let list = null        // 'ul' | 'ol'
  let inCode = false
  let codeBuf = []
  let tableBuf = []

  const closeList = () => {
    if (list) { out.push(`</${list}>`); list = null }
  }
  const flushTable = () => {
    if (!tableBuf.length) return
    const rows = tableBuf.filter(r => !/^\s*\|?[\s:|-]+\|?\s*$/.test(r))
    if (rows.length) {
      const cells = r => r.replace(/^\s*\|/, '').replace(/\|\s*$/, '')
                          .split('|').map(c => c.trim())
      out.push('<table><thead><tr>' +
        cells(rows[0]).map(c => `<th>${inline(c)}</th>`).join('') +
        '</tr></thead><tbody>')
      rows.slice(1).forEach(r => {
        out.push('<tr>' + cells(r).map(c => `<td>${inline(c)}</td>`).join('') + '</tr>')
      })
      out.push('</tbody></table>')
    }
    tableBuf = []
  }

  for (const raw of lines) {
    const line = raw.replace(/\r$/, '')

    // 代码块
    if (line.trim().startsWith('```')) {
      if (inCode) {
        out.push(`<pre><code>${esc(codeBuf.join('\n'))}</code></pre>`)
        codeBuf = []
        inCode = false
      } else {
        closeList(); flushTable()
        inCode = true
      }
      continue
    }
    if (inCode) { codeBuf.push(line); continue }

    // 表格
    if (/^\s*\|.*\|\s*$/.test(line)) {
      closeList()
      tableBuf.push(line)
      continue
    } else if (tableBuf.length) {
      flushTable()
    }

    if (!line.trim()) { closeList(); continue }

    // 标题
    const h = line.match(/^(#{1,6})\s+(.*)$/)
    if (h) {
      closeList()
      const lvl = Math.min(h[1].length + 1, 6)   // # 映射到 h2，避免过大
      out.push(`<h${lvl}>${inline(h[2])}</h${lvl}>`)
      continue
    }

    // 引用
    const q = line.match(/^>\s?(.*)$/)
    if (q) {
      closeList()
      out.push(`<blockquote>${inline(q[1])}</blockquote>`)
      continue
    }

    // 分隔线
    if (/^\s*([-*_])\1{2,}\s*$/.test(line)) {
      closeList()
      out.push('<hr/>')
      continue
    }

    // 无序列表
    const ul = line.match(/^\s*[-*+]\s+(.*)$/)
    if (ul) {
      if (list !== 'ul') { closeList(); out.push('<ul>'); list = 'ul' }
      out.push(`<li>${inline(ul[1])}</li>`)
      continue
    }

    // 有序列表
    const ol = line.match(/^\s*\d+\.\s+(.*)$/)
    if (ol) {
      if (list !== 'ol') { closeList(); out.push('<ol>'); list = 'ol' }
      out.push(`<li>${inline(ol[1])}</li>`)
      continue
    }

    closeList()
    out.push(`<p>${inline(line)}</p>`)
  }

  if (inCode && codeBuf.length) {
    out.push(`<pre><code>${esc(codeBuf.join('\n'))}</code></pre>`)
  }
  closeList()
  flushTable()

  return out.join('')
}
