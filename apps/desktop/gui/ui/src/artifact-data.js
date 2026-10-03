// Artifact HTML'si hiçbir zaman DOM'a eklenmez veya çalıştırılmaz.
export const ARTIFACT_LIMIT = 8 * 1024 * 1024;

export function parseMindmapHTML(html) {
  if (typeof html !== "string" || html.length > ARTIFACT_LIMIT)
    throw new Error("Harita boyut sınırını aşıyor.");
  const matches = [...html.matchAll(/(?:^|\n)\s*const\s+veri\s*=\s*/g)];
  if (matches.length !== 1)
    throw new Error("Harita veri ağacı bulunamadı veya belirsiz.");
  const start = matches[0].index + matches[0][0].length;
  if (html[start] !== "{") throw new Error("Harita veri biçimi geçersiz.");
  let depth = 0,
    quoted = false,
    escaped = false;
  for (let end = start; end < html.length; end++) {
    const char = html[end];
    if (quoted) {
      if (escaped) escaped = false;
      else if (char === "\\") escaped = true;
      else if (char === '"') quoted = false;
    } else if (char === '"') quoted = true;
    else if (char === "{" || char === "[") depth++;
    else if (char === "}" || char === "]") {
      depth--;
      if (depth === 0)
        return validateMindmapTree(JSON.parse(html.slice(start, end + 1)));
    }
    if (depth > 64) throw new Error("Harita çok derin.");
  }
  throw new Error("Harita veri ağacı tamamlanmamış.");
}

export function validateMindmapTree(value) {
  let nodes = 0,
    total = 0;
  function visit(node, depth) {
    if (++nodes > 1000 || depth > 24)
      throw new Error("Harita düğüm sınırını aşıyor.");
    if (
      !node ||
      Array.isArray(node) ||
      typeof node !== "object" ||
      typeof node.content !== "string" ||
      !Array.isArray(node.children)
    )
      throw new Error("Harita düğümü geçersiz.");
    if (Object.keys(node).some((key) => !["content", "children"].includes(key)))
      throw new Error("Harita düğümünde desteklenmeyen alan var.");
    total += node.content.length;
    if (node.content.length > 4000 || total > 200000)
      throw new Error("Harita metin sınırını aşıyor.");
    return {
      content: decodeEntities(node.content),
      children: node.children.map((child) => visit(child, depth + 1)),
    };
  }
  return visit(value, 0);
}

function decodeEntities(text) {
  const named = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " " };
  return text.replace(
    /&(#x[0-9a-f]+|#[0-9]+|amp|lt|gt|quot|apos|nbsp);/gi,
    (whole, entity) => {
      if (entity[0] !== "#") return named[entity.toLowerCase()] || whole;
      const code =
        entity[1].toLowerCase() === "x"
          ? parseInt(entity.slice(2), 16)
          : Number(entity.slice(1));
      return code > 0 && code <= 0x10ffff && !(code >= 0xd800 && code <= 0xdfff)
        ? String.fromCodePoint(code)
        : whole;
    },
  );
}

export function validatePDFBytes(bytes) {
  if (
    !(bytes instanceof Uint8Array) ||
    bytes.length < 8 ||
    bytes.length > ARTIFACT_LIMIT ||
    !new TextDecoder()
      .decode(bytes.subarray(0, Math.min(1024, bytes.length)))
      .includes("%PDF-")
  )
    throw new Error("PDF dosyası geçersiz veya boyut sınırını aşıyor.");
  return bytes;
}

export function mapLayout(tree, collapsed = new Set()) {
  const rows = [];
  let cursor = 38,
    maxDepth = 0;
  function visit(node, depth, path, parent) {
    const row = {
      node,
      depth,
      path,
      parent,
      x: 24 + depth * 256,
      y: 0,
      lines: wrap(node.content),
    };
    rows.push(row);
    maxDepth = Math.max(maxDepth, depth);
    const children = collapsed.has(path)
      ? []
      : node.children.map((child, index) =>
          visit(child, depth + 1, `${path}.${index}`, row),
        );
    if (children.length) row.y = (children[0].y + children.at(-1).y) / 2;
    else {
      row.y = cursor;
      cursor += 86;
    }
    return row;
  }
  visit(tree, 0, "0", null);
  return {
    rows,
    width: (maxDepth + 1) * 256 + 32,
    height: Math.max(150, cursor + 24),
  };
}
function wrap(text) {
  const lines = [],
    words = text.split(/\s+/);
  let current = "";
  for (const word of words) {
    for (const chunk of word.match(/.{1,27}/gu) || [""]) {
      if ((current + " " + chunk).trim().length > 27) {
        lines.push(current);
        current = chunk;
      } else current = (current + " " + chunk).trim();
    }
  }
  if (current) lines.push(current);
  return lines.length > 4
    ? [...lines.slice(0, 3), lines[3].slice(0, 26) + "…"]
    : lines;
}
