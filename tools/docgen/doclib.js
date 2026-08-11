// Общая библиотека для сборки docx-документации Dashboard.
// ВАЖНО: buildDoc делает children.flat(Infinity) — незаспредленный массив в
// children иначе даёт битый XML (<0/>), Word/рендеры такой файл не открывают.
const fs = require('fs');
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType, ImageRun,
  Table, TableRow, TableCell, WidthType, BorderStyle, ShadingType, LevelFormat,
  PageBreak, TableOfContents, convertMillimetersToTwip,
} = require('docx');

const SHOTS = __dirname + '/shots/';
const BRAND = 'e04e39';
const DARKTXT = '2c2a29';
const MUTED = '6b625c';

function pngSize(path) {
  const b = fs.readFileSync(path);
  return { w: b.readUInt32BE(16), h: b.readUInt32BE(20) };
}

// Картинка на ширину текста с подписью «Рис. N — …».
let figN = 0;
function img(name, caption) {
  const path = SHOTS + name + '.png';
  const { w, h } = pngSize(path);
  const maxW = 612; // pt — ширина области текста
  const width = maxW;
  const height = Math.round(h * (maxW / w));
  figN += 1;
  return [
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 160, after: 60 },
      children: [new ImageRun({ type: 'png', data: fs.readFileSync(path), transformation: { width, height } })],
      keepNext: true,
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { after: 200 },
      children: [new TextRun({ text: `Рис. ${figN}. ${caption}`, italics: true, size: 18, color: MUTED, font: 'PT Sans' })],
    }),
  ];
}

const runOpts = { size: 22, font: 'PT Sans', color: DARKTXT };
function tr(text, extra = {}) { return new TextRun({ text, ...runOpts, ...extra }); }
function B(text) { return tr(text, { bold: true }); }
function C(text) { return new TextRun({ text, size: 20, font: 'Courier New', color: '8a2f1f' }); }
function P(...parts) {
  const children = parts.map((p) => (typeof p === 'string' ? tr(p) : p));
  return new Paragraph({ children, spacing: { after: 120, line: 300 } });
}
function NOTE(...parts) {
  const children = parts.map((p) => (typeof p === 'string' ? tr(p, { size: 20 }) : p));
  return new Paragraph({
    children, spacing: { after: 140, line: 280 },
    shading: { type: ShadingType.CLEAR, fill: 'faf0e9' },
    border: { left: { style: BorderStyle.SINGLE, size: 18, color: BRAND } },
    indent: { left: 200 },
  });
}
function H1(text) { return new Paragraph({ heading: HeadingLevel.HEADING_1, spacing: { before: 360, after: 160 }, children: [new TextRun({ text, bold: true, size: 32, color: BRAND, font: 'PT Sans' })] }); }
function H2(text) { return new Paragraph({ heading: HeadingLevel.HEADING_2, spacing: { before: 280, after: 120 }, children: [new TextRun({ text, bold: true, size: 26, color: DARKTXT, font: 'PT Sans' })] }); }
function H3(text) { return new Paragraph({ heading: HeadingLevel.HEADING_3, spacing: { before: 200, after: 100 }, children: [new TextRun({ text, bold: true, size: 23, color: MUTED, font: 'PT Sans' })] }); }

function UL(...items) {
  return items.map((it) => new Paragraph({
    children: (Array.isArray(it) ? it : [it]).map((p) => (typeof p === 'string' ? tr(p) : p)),
    numbering: { reference: 'bullets', level: 0 }, spacing: { after: 60, line: 280 },
  }));
}
function OL(...items) {
  return items.map((it) => new Paragraph({
    children: (Array.isArray(it) ? it : [it]).map((p) => (typeof p === 'string' ? tr(p) : p)),
    numbering: { reference: 'nums', level: 0 }, spacing: { after: 60, line: 280 },
  }));
}
function CODE(text) {
  return text.split('\n').map((line) => new Paragraph({
    children: [new TextRun({ text: line, size: 20, font: 'Courier New', color: '3d2c24' })],
    shading: { type: ShadingType.CLEAR, fill: 'f3ece6' },
    spacing: { after: 0, line: 260 }, indent: { left: 200 },
  })).concat([new Paragraph({ children: [], spacing: { after: 120 } })]);
}

// Таблица: header — массив строк, rows — массив массивов, widths — DXA.
function TBL(header, rows, widths) {
  const total = widths.reduce((a, b) => a + b, 0);
  const mkCell = (text, i, isHead) => new TableCell({
    width: { size: widths[i], type: WidthType.DXA },
    shading: isHead ? { type: ShadingType.CLEAR, fill: 'f7e3dd' } : undefined,
    margins: { top: 60, bottom: 60, left: 100, right: 100 },
    children: (Array.isArray(text) ? text : [text]).map((t) =>
      new Paragraph({ children: [typeof t === 'string' ? tr(t, { size: 20, bold: !!isHead }) : t], spacing: { after: 0, line: 260 } })),
  });
  const mkRow = (cells, isHead) => new TableRow({
    children: cells.map((c, i) => mkCell(c, i, isHead)),
    tableHeader: !!isHead,
  });
  return new Table({
    width: { size: total, type: WidthType.DXA },
    columnWidths: widths,
    rows: [mkRow(header, true), ...rows.map((r) => mkRow(r, false))],
  });
}

function title(docTitle, subtitle, version) {
  return [
    new Paragraph({ spacing: { before: 3200 }, children: [] }),
    new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: 'Dashboard', bold: true, size: 72, color: BRAND, font: 'PT Sans' })] }),
    new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 200 }, children: [new TextRun({ text: 'Аналитический портал для управленческих решений', size: 26, color: MUTED, font: 'PT Sans' })] }),
    new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 1200 }, children: [new TextRun({ text: docTitle, bold: true, size: 44, color: DARKTXT, font: 'PT Sans' })] }),
    new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 300 }, children: [new TextRun({ text: subtitle, size: 24, color: MUTED, font: 'PT Sans' })] }),
    new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 2600 }, children: [new TextRun({ text: version, size: 22, color: MUTED, font: 'PT Sans' })] }),
    new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: 'ГБУ «МФЦ ДНР» · первое внедрение · август 2026', size: 22, color: MUTED, font: 'PT Sans' })] }),
    new Paragraph({ children: [new PageBreak()] }),
    new Paragraph({ children: [new TextRun({ text: 'Содержание', bold: true, size: 28, color: DARKTXT, font: 'PT Sans' })], spacing: { after: 200 } }),
    new TableOfContents('Содержание', { hyperlink: true, headingStyleRange: '1-2' }),
    new Paragraph({ children: [new PageBreak()] }),
  ];
}

function buildDoc(children) {
  return new Document({
    numbering: {
      config: [
        { reference: 'bullets', levels: [{ level: 0, format: LevelFormat.BULLET, text: '•', alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 460, hanging: 230 } } } }] },
        { reference: 'nums', levels: [{ level: 0, format: LevelFormat.DECIMAL, text: '%1.', alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 460, hanging: 230 } } } }] },
      ],
    },
    styles: { default: { document: { run: { font: 'PT Sans', size: 22, color: DARKTXT } } } },
    sections: [{
      properties: { page: { margin: { top: convertMillimetersToTwip(20), bottom: convertMillimetersToTwip(18), left: convertMillimetersToTwip(20), right: convertMillimetersToTwip(16) } } },
      children: children.flat(Infinity),
    }],
  });
}

async function save(doc, path) {
  const buf = await Packer.toBuffer(doc);
  fs.writeFileSync(path, buf);
  console.log('WROTE ' + path + ' (' + Math.round(buf.length / 1024) + ' КБ)');
}

module.exports = { img, P, B, C, NOTE, H1, H2, H3, UL, OL, CODE, TBL, title, buildDoc, save, tr, PageBreak, Paragraph };
