// Renders the nicro app icons (white "n" monogram on a violet-cyan gradient) to PNG without dependencies.
// Usage: node scripts/make-icons.mjs  -> public/icon-192.png, icon-512.png, icon-maskable-512.png
import { writeFileSync, mkdirSync } from 'node:fs'
import { deflateSync } from 'node:zlib'


// nicro monogram "n" in a 24x24 box: two stems + an arch
function inN(x, y) {
  if (x >= 6.5 && x <= 9.5 && y >= 8 && y <= 18) return true           // left stem
  if (x >= 14.5 && x <= 17.5 && y >= 12 && y <= 18) return true        // right stem
  const dx = x - 12, dy = y - 12, r = Math.hypot(dx, dy)
  return y <= 12 && r >= 2.5 && r <= 5.5                                // arch
}

function render(size, { maskable }) {
  const A = [124, 108, 255], B = [34, 211, 238]
  const pad = maskable ? size * 0.2 : size * 0.12
  const scale = (size - 2 * pad) / 24
  const radius = maskable ? 0 : size * 0.23
  const px = Buffer.alloc(size * (size * 4 + 1))
  const S = 4
  for (let y = 0; y < size; y++) {
    px[y * (size * 4 + 1)] = 0
    for (let x = 0; x < size; x++) {
      let bg = 0, fg = 0
      for (let sy = 0; sy < S; sy++) for (let sx = 0; sx < S; sx++) {
        const X = x + (sx + 0.5) / S, Y = y + (sy + 0.5) / S
        const dx = Math.max(radius - X, 0, X - (size - radius)), dy = Math.max(radius - Y, 0, Y - (size - radius))
        if (radius === 0 || dx * dx + dy * dy <= radius * radius) { bg++; if (inN((X - pad) / scale, (Y - pad) / scale)) fg++ }
      }
      const t = (x + y) / (2 * size)  // diagonal violet -> cyan gradient
      const base = A.map((c, i) => c + (B[i] - c) * t)
      const f = bg ? fg / bg : 0
      const o = y * (size * 4 + 1) + 1 + x * 4
      for (let c = 0; c < 3; c++) px[o + c] = Math.round(base[c] * (1 - f) + 255 * f)
      px[o + 3] = Math.round((bg / (S * S)) * 255)
    }
  }
  return png(size, px)
}

function png(size, raw) {
  const crcTable = Array.from({ length: 256 }, (_, n) => { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; return c >>> 0 })
  const crc = (b) => { let c = 0xffffffff; for (const x of b) c = crcTable[(c ^ x) & 0xff] ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0 }
  const chunk = (type, data) => {
    const len = Buffer.alloc(4); len.writeUInt32BE(data.length)
    const td = Buffer.concat([Buffer.from(type), data]); const c = Buffer.alloc(4); c.writeUInt32BE(crc(td))
    return Buffer.concat([len, td, c])
  }
  const ihdr = Buffer.alloc(13); ihdr.writeUInt32BE(size, 0); ihdr.writeUInt32BE(size, 4); ihdr[8] = 8; ihdr[9] = 6
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', ihdr), chunk('IDAT', deflateSync(raw)), chunk('IEND', Buffer.alloc(0))])
}

mkdirSync('public', { recursive: true })
writeFileSync('public/icon-192.png', render(192, { maskable: false }))
writeFileSync('public/icon-512.png', render(512, { maskable: false }))
writeFileSync('public/icon-maskable-512.png', render(512, { maskable: true }))
console.log('icons written')
