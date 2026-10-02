// Codemod: wraps every Russian UI string in tr(...) so the panel can be translated.
//   node scripts/i18n-wrap.mjs          -> rewrites src/**/*.ts(x), writes src/locales/keys.json
//   node scripts/i18n-wrap.mjs --keys   -> only collects the keys (after new strings were wrapped by hand)
// JSX text -> {tr("…")}, "…" -> tr("…"), `a ${x} b` -> tr("a {0} b", x). Idempotent: strings already
// inside tr(...) are left alone. Runs in passes until nothing changes (nested templates).
import fs from 'node:fs'
import path from 'node:path'
import ts from 'typescript'

const SRC = path.resolve('src')
const CYR = /[А-Яа-яЁё]/
const onlyKeys = process.argv.includes('--keys')
const keys = new Set()

const files = []
;(function walk(d) {
  for (const f of fs.readdirSync(d)) {
    const p = path.join(d, f)
    if (fs.statSync(p).isDirectory()) walk(p)
    else if (/\.(tsx?|mts)$/.test(f) && !/i18n\.ts$|\.d\.ts$/.test(f)) files.push(p)
  }
})(SRC)

const ENT = { '&amp;': '&', '&lt;': '<', '&gt;': '>', '&quot;': '"', '&#39;': "'", '&nbsp;': ' ' }
const jsxText = (raw) => raw.replace(/&(amp|lt|gt|quot|#39|nbsp);/g, (m) => ENT[m])
  .split('\n').map((l, i, a) => (i === 0 ? l.trimEnd() : i === a.length - 1 ? l.trimStart() : l.trim()))
  .filter((l, i, a) => l || i === 0 || i === a.length - 1).join(' ').trim()

const isTrCall = (n) => n && ts.isCallExpression(n) && ts.isIdentifier(n.expression) && n.expression.text === 'tr'

function transform(file) {
  let text = fs.readFileSync(file, 'utf8')
  let changed = false
  for (let pass = 0; pass < 6; pass++) {
    const sf = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, file.endsWith('x') ? ts.ScriptKind.TSX : ts.ScriptKind.TS)
    const edits = []
    const hasInner = (node) => {
      let found = false
      node.forEachChild(function visit(c) {
        if (found) return
        if (want(c)) found = true
        else c.forEachChild(visit)
      })
      return found
    }
    const want = (n) => {
      if (ts.isJsxText(n)) return CYR.test(n.text)
      if (ts.isStringLiteral(n) || ts.isNoSubstitutionTemplateLiteral(n)) {
        if (!CYR.test(n.text)) return false
        const p = n.parent
        if (ts.isImportDeclaration(p) || ts.isLiteralTypeNode(p) || (ts.isPropertyAssignment(p) && p.name === n)) return false
        if (isTrCall(p) && p.arguments[0] === n) { keys.add(n.text); return false }
        return true
      }
      if (ts.isTemplateExpression(n)) {
        return [n.head, ...n.templateSpans.map((s) => s.literal)].some((x) => CYR.test(x.text))
      }
      return false
    }
    sf.forEachChild(function visit(n) {
      if (want(n) && !hasInner(n)) {
        const q = (s) => JSON.stringify(s)
        if (ts.isJsxText(n)) {
          const raw = n.getFullText(sf)
          const lead = raw.match(/^\s*/)[0], trail = raw.match(/\s*$/)[0]
          const s = jsxText(raw)
          keys.add(s)
          // keep a space where JSX would have kept one between words on the same line
          const l = lead && !lead.includes('\n') ? lead : '', r = trail && !trail.includes('\n') ? trail : ''
          edits.push([n.getFullStart(), n.getEnd(), `${lead.includes('\n') ? lead : ''}${l ? "{' '}" : ''}{tr(${q(s)})}${r ? "{' '}" : ''}${trail.includes('\n') ? trail : ''}`])
        } else if (ts.isTemplateExpression(n)) {
          let pat = n.head.text
          const args = []
          n.templateSpans.forEach((sp, i) => { pat += `{${i}}` + sp.literal.text; args.push(sp.expression.getText(sf)) })
          keys.add(pat)
          edits.push([n.getStart(sf), n.getEnd(), `tr(${q(pat)}, ${args.join(', ')})`])
        } else {
          keys.add(n.text)
          const inAttr = ts.isJsxAttribute(n.parent)
          edits.push([n.getStart(sf), n.getEnd(), inAttr ? `{tr(${q(n.text)})}` : `tr(${q(n.text)})`])
        }
        return
      }
      n.forEachChild(visit)
    })
    if (!edits.length || onlyKeys) break
    edits.sort((a, b) => b[0] - a[0])
    for (const [s, e, r] of edits) text = text.slice(0, s) + r + text.slice(e)
    changed = true
  }
  if (changed && !onlyKeys) {
    if (!/import \{ tr \} from/.test(text)) {
      let rel = path.relative(path.dirname(file), path.join(SRC, 'i18n')).replace(/\\/g, '/')
      if (!rel.startsWith('.')) rel = './' + rel
      const lines = text.split('\n')
      let last = -1
      lines.forEach((l, i) => { if (/^import /.test(l) || (last === i - 1 && /^\s+[\w{},]/.test(l) && last >= 0 && !/;$|'$/.test(lines[last]))) last = i })
      // insert after the last complete import line
      let idx = 0
      for (let i = 0; i < lines.length; i++) { if (/^import .* from '.*'$/.test(lines[i]) || /^} from '.*'$/.test(lines[i])) idx = i + 1 }
      lines.splice(idx, 0, `import { tr } from '${rel}'`)
      text = lines.join('\n')
    }
    fs.writeFileSync(file, text)
    console.log('wrapped', path.relative(SRC, file))
  }
}

files.forEach(transform)
fs.mkdirSync(path.join(SRC, 'locales'), { recursive: true })
fs.writeFileSync(path.join(SRC, 'locales', 'keys.json'), JSON.stringify([...keys].sort(), null, 1))
console.log(keys.size, 'keys')
