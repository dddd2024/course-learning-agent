import { marked } from 'marked'
import DOMPurify from 'dompurify'

// Configure marked for GFM with line breaks
marked.setOptions({
  breaks: true,
  gfm: true,
})

/**
 * 将 Markdown 文本渲染为经过净化的安全 HTML。
 *
 * 使用 marked 解析 GFM（含换行），再用 DOMPurify 过滤危险标签与属性，
 * 仅保留展示所需的白名单，避免 XSS。
 */
export function renderMarkdown(text: string): string {
  if (!text) return ''
  // async:false 将返回类型收窄为 string（而非 string | Promise<string>），
  // 保证同步调用并满足 DOMPurify.sanitize 的入参类型。
  const html = marked.parse(text, { async: false })
  return DOMPurify.sanitize(html, {
    ALLOWED_TAGS: ['p', 'br', 'strong', 'em', 'code', 'pre', 'ul', 'ol', 'li',
                   'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote', 'a', 'table',
                   'thead', 'tbody', 'tr', 'th', 'td', 'hr', 'del', 'sub', 'sup', 'span'],
    ALLOWED_ATTR: ['href', 'target', 'rel', 'class'],
  })
}
