// Minimal Markdown -> DOCX converter for docs/*.md (headings, paragraphs,
// bold/italic/code, lists, tables, code blocks, blockquotes, rules).
// Usage: cd scripts/docs && npm install && npm run build
const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, Table, TableRow, TableCell, WidthType,
  ShadingType, BorderStyle, AlignmentType, LevelFormat, Footer, PageNumber, TableOfContents,
} = require("docx");

const [, , inPath, outPath] = process.argv;
const lines = fs.readFileSync(inPath, "utf8").replace(/\r/g, "").split("\n");

const LATIN = "Calibri", CJK = "PingFang SC", MONO = "Menlo";
const font = { ascii: LATIN, hAnsi: LATIN, eastAsia: CJK, cs: LATIN };
const mono = { ascii: MONO, hAnsi: MONO, eastAsia: CJK, cs: MONO };
const PAGE_W = 12240, MARGIN = 1200, CONTENT_W = PAGE_W - 2 * MARGIN;

function inline(text, base = {}) {
  const runs = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*\s][^*]*\*)/g;
  let last = 0, m;
  while ((m = re.exec(text))) {
    if (m.index > last) runs.push(new TextRun({ text: text.slice(last, m.index), font, ...base }));
    const t = m[0];
    if (t.startsWith("**")) runs.push(...inline(t.slice(2, -2), { ...base, bold: true }));
    else if (t.startsWith("`")) runs.push(new TextRun({ ...base, text: t.slice(1, -1), font: mono, size: 18,
      shading: { type: ShadingType.CLEAR, fill: "EEF1F5", color: "auto" } }));
    else runs.push(new TextRun({ text: t.slice(1, -1), font, italics: true, ...base }));
    last = m.index + t.length;
  }
  if (last < text.length) runs.push(new TextRun({ text: text.slice(last), font, ...base }));
  return runs;
}

let listCounter = 0;
const numberingConfigs = [{
  reference: "bullets",
  levels: [0, 1].map((lvl) => ({ level: lvl, format: LevelFormat.BULLET, text: lvl ? "–" : "•", alignment: AlignmentType.LEFT,
    style: { paragraph: { indent: { left: 540 + lvl * 360, hanging: 270 } } } })),
}];
function newNumbered() {
  const ref = `num-${listCounter++}`;
  numberingConfigs.push({ reference: ref, levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT,
    style: { paragraph: { indent: { left: 540, hanging: 300 } } } }] });
  return ref;
}

function cellWidths(rows) {
  const n = Math.max(...rows.map((r) => r.length));
  const lens = Array.from({ length: n }, (_, c) => Math.max(...rows.map((r) => {
    const s = (r[c] || "").replace(/\*\*|`/g, "");
    let w = 0; for (const ch of s) w += /[⺀-￿]/.test(ch) ? 2 : 1;
    return Math.min(w, 70);
  })));
  const weights = lens.map((l) => Math.max(14, l));
  const tot = weights.reduce((a, b) => a + b, 0);
  const ws = weights.map((w) => Math.floor(CONTENT_W * w / tot));
  ws[ws.length - 1] += CONTENT_W - ws.reduce((a, b) => a + b, 0);
  return ws;
}
const border = { style: BorderStyle.SINGLE, size: 4, color: "C9CED6" };
function table(rows) {
  const ws = cellWidths(rows);
  return new Table({
    width: { size: CONTENT_W, type: WidthType.DXA }, columnWidths: ws,
    rows: rows.map((r, i) => new TableRow({
      tableHeader: i === 0,
      children: ws.map((w, j) => new TableCell({
        width: { size: w, type: WidthType.DXA },
        borders: { top: border, bottom: border, left: border, right: border },
        shading: i === 0 ? { type: ShadingType.CLEAR, fill: "E8EEFC", color: "auto" } : undefined,
        margins: { top: 60, bottom: 60, left: 100, right: 100 },
        children: [new Paragraph({ spacing: { before: 0, after: 0, line: 276 },
          children: inline((r[j] || "").trim(), { size: 19, ...(i === 0 ? { bold: true } : {}) }) })],
      })),
    })),
  });
}
const splitRow = (l) => l.trim().replace(/^\|/, "").replace(/\|$/, "").split("|");
const ruleParagraph = () => new Paragraph({ border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: "C9CED6", space: 1 } }, spacing: { after: 120 } });

const children = [];
let i = 0, firstH1 = true, tocInserted = false;
while (i < lines.length) {
  const l = lines[i];
  if (!l.trim()) { i++; continue; }
  if (l.startsWith("```")) {
    const buf = []; i++;
    while (i < lines.length && !lines[i].startsWith("```")) buf.push(lines[i++]);
    i++;
    buf.forEach((b, k) => children.push(new Paragraph({
      spacing: { before: k ? 0 : 80, after: k === buf.length - 1 ? 140 : 0, line: 240 },
      shading: { type: ShadingType.CLEAR, fill: "F3F5F8", color: "auto" }, indent: { left: 120, right: 120 },
      children: [new TextRun({ text: b || " ", font: mono, size: 17 })],
    })));
    continue;
  }
  if (/^---+$/.test(l.trim())) {
    children.push(ruleParagraph());
    if (!tocInserted) {  // table of contents after the title block
      children.push(new Paragraph({ heading: HeadingLevel.HEADING_1, children: inline("目录") }),
        new TableOfContents("目录", { hyperlink: true, headingStyleRange: "1-2" }),
        new Paragraph({ spacing: { after: 120 }, children: [new TextRun({ text: "（如果目录为空或页码不对：在 Word 中右键目录 → 更新域。）", font, size: 18, color: "667085" })] }),
        ruleParagraph());
      tocInserted = true;
    }
    i++; continue;
  }
  const h = l.match(/^(#{1,4})\s+(.*)$/);
  if (h) {
    const lvl = h[1].length;
    if (lvl === 1 && firstH1) {
      children.push(new Paragraph({ spacing: { after: 160 }, children: inline(h[2], { size: 38, bold: true, color: "1D2B4F" }) }));
      firstH1 = false;
    } else {
      const H = [null, HeadingLevel.HEADING_1, HeadingLevel.HEADING_1, HeadingLevel.HEADING_2, HeadingLevel.HEADING_3][lvl];
      children.push(new Paragraph({ heading: H, children: inline(h[2]) }));
    }
    i++; continue;
  }
  if (l.startsWith(">")) {
    const buf = [];
    while (i < lines.length && lines[i].startsWith(">")) buf.push(lines[i++].replace(/^>\s?/, ""));
    buf.filter((b) => b.trim()).forEach((b) => {
      const bullet = b.match(/^-\s+(.*)/);
      children.push(new Paragraph({
        indent: { left: 240, right: 120 }, spacing: { after: 40 },
        border: { left: { style: BorderStyle.SINGLE, size: 18, color: "2553C7", space: 8 } },
        shading: { type: ShadingType.CLEAR, fill: "F1F5FE", color: "auto" },
        children: inline(bullet ? "· " + bullet[1] : b),
      }));
    });
    children.push(new Paragraph({ spacing: { after: 60 }, children: [] }));
    continue;
  }
  if (l.trim().startsWith("|")) {
    const rows = [];
    while (i < lines.length && lines[i].trim().startsWith("|")) {
      if (!/^\s*\|?\s*:?-{2,}/.test(lines[i])) rows.push(splitRow(lines[i]));
      i++;
    }
    children.push(table(rows), new Paragraph({ spacing: { after: 100 }, children: [] }));
    continue;
  }
  if (/^\s*-\s+/.test(l)) {
    while (i < lines.length && /^\s*-\s+/.test(lines[i])) {
      const m = lines[i].match(/^(\s*)-\s+(.*)$/);
      children.push(new Paragraph({ numbering: { reference: "bullets", level: m[1].length >= 2 ? 1 : 0 }, spacing: { after: 40 }, children: inline(m[2]) }));
      i++;
    }
    children.push(new Paragraph({ spacing: { after: 60 }, children: [] }));
    continue;
  }
  if (/^\d+\.\s+/.test(l)) {
    const ref = newNumbered();
    while (i < lines.length && (/^\d+\.\s+/.test(lines[i]) || /^\s{2,}-\s+/.test(lines[i]))) {
      const sub = lines[i].match(/^\s{2,}-\s+(.*)$/);
      if (sub) children.push(new Paragraph({ numbering: { reference: "bullets", level: 1 }, spacing: { after: 40 }, children: inline(sub[1]) }));
      else children.push(new Paragraph({ numbering: { reference: ref, level: 0 }, spacing: { after: 40 }, children: inline(lines[i].replace(/^\d+\.\s+/, "")) }));
      i++;
    }
    children.push(new Paragraph({ spacing: { after: 60 }, children: [] }));
    continue;
  }
  const buf = [];
  while (i < lines.length && lines[i].trim() && !/^(#|```|>|\||\s*-\s|\d+\.\s|---)/.test(lines[i])) buf.push(lines[i++].trim());
  children.push(new Paragraph({ spacing: { after: 120 }, children: inline(buf.join(" ")) }));
}

const doc = new Document({
  creator: "Naming Game Simulator", title: "LLM 命名博弈实验：研究假设、软件功能、操作步骤与原理",
  features: { updateFields: true },
  styles: {
    default: { document: { run: { font, size: 21 }, paragraph: { spacing: { line: 300 } } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { font, size: 30, bold: true, color: "1D2B4F" }, paragraph: { spacing: { before: 360, after: 140 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { font, size: 25, bold: true, color: "2553C7" }, paragraph: { spacing: { before: 260, after: 100 }, outlineLevel: 1 } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { font, size: 22, bold: true }, paragraph: { spacing: { before: 200, after: 80 }, outlineLevel: 2 } },
    ],
  },
  numbering: { config: numberingConfigs },
  sections: [{
    properties: { page: { size: { width: PAGE_W, height: 15840 }, margin: { top: 1200, bottom: 1200, left: MARGIN, right: MARGIN } } },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER,
      children: [new TextRun({ font, size: 17, color: "667085", children: ["LLM 命名博弈实验 · 审阅稿 v0.1 · 第 ", PageNumber.CURRENT, " 页"] })] })] }) },
    children,
  }],
});
Packer.toBuffer(doc).then((b) => { fs.writeFileSync(outPath, b); console.log("wrote", outPath, b.length, "bytes"); });
