#!/usr/bin/env node
/**
 * create_deck.js - Create a .pptx presentation from scratch using PptxGenJS.
 *
 * Usage:
 *   node create_deck.js <config.json> [output.pptx]
 *
 * Config JSON format:
 * {
 *   "theme": {
 *     "primary_color": "2F5496",
 *     "secondary_color": "4472C4",
 *     "accent_color": "ED7D31",
 *     "background_color": "FFFFFF",
 *     "text_color": "333333",
 *     "light_text_color": "666666",
 *     "font_heading": "Microsoft YaHei",
 *     "font_body": "Microsoft YaHei"
 *   },
 *   "metadata": {
 *     "title": "Presentation Title",
 *     "author": "Author Name",
 *     "subject": "Subject"
 *   },
 *   "output": "output.pptx",
 *   "slides": [
 *     {"type": "cover", "title": "Main Title", "subtitle": "Subtitle", "date": "2024-01-01"},
 *     {"type": "section", "title": "Section Title", "subtitle": "Section description"},
 *     {"type": "content", "title": "Slide Title", "bullets": ["Point 1", "Point 2"]},
 *     {"type": "content", "title": "Table Slide", "table": {"headers": [...], "rows": [...]}},
 *     {"type": "content", "title": "Two Column", "columns": [{"bullets": [...]}, {"bullets": [...]}]},
 *     {"type": "summary", "title": "Summary", "bullets": ["Key takeaway 1", "Key takeaway 2"]}
 *   ]
 * }
 */

const PptxGenJS = require("pptxgenjs");
const fs = require("fs");
const path = require("path");

// Default theme
const DEFAULT_THEME = {
  primary_color: "2F5496",
  secondary_color: "4472C4",
  accent_color: "ED7D31",
  background_color: "FFFFFF",
  text_color: "333333",
  light_text_color: "666666",
  font_heading: "Microsoft YaHei",
  font_body: "Microsoft YaHei",
};

function createPresentation(config) {
  const theme = { ...DEFAULT_THEME, ...(config.theme || {}) };
  const metadata = config.metadata || {};
  const slides = config.slides || [];

  const pptx = new PptxGenJS();

  // Set metadata
  if (metadata.title) pptx.title = metadata.title;
  if (metadata.author) pptx.author = metadata.author;
  if (metadata.subject) pptx.subject = metadata.subject;

  // Set default slide size (widescreen 16:9)
  pptx.layout = "LAYOUT_WIDE";

  // Process each slide
  for (const slideSpec of slides) {
    switch (slideSpec.type) {
      case "cover":
        addCoverSlide(pptx, slideSpec, theme);
        break;
      case "section":
        addSectionSlide(pptx, slideSpec, theme);
        break;
      case "content":
        addContentSlide(pptx, slideSpec, theme);
        break;
      case "summary":
        addSummarySlide(pptx, slideSpec, theme);
        break;
      default:
        console.error(`Unknown slide type: ${slideSpec.type}`);
        addContentSlide(pptx, slideSpec, theme);
    }
  }

  return pptx;
}

function addCoverSlide(pptx, spec, theme) {
  const slide = pptx.addSlide();

  // Full-bleed background with primary color
  slide.background = { color: theme.primary_color };

  // Title
  slide.addText(spec.title || "Untitled", {
    x: 0.8,
    y: 2.0,
    w: "85%",
    h: 1.5,
    fontSize: 40,
    fontFace: theme.font_heading,
    color: "FFFFFF",
    bold: true,
    align: "left",
    valign: "bottom",
  });

  // Subtitle
  if (spec.subtitle) {
    slide.addText(spec.subtitle, {
      x: 0.8,
      y: 3.6,
      w: "85%",
      h: 0.8,
      fontSize: 20,
      fontFace: theme.font_body,
      color: "CCDDEE",
      align: "left",
      valign: "top",
    });
  }

  // Date or additional info
  if (spec.date) {
    slide.addText(spec.date, {
      x: 0.8,
      y: 6.5,
      w: "50%",
      h: 0.5,
      fontSize: 12,
      fontFace: theme.font_body,
      color: "AABBCC",
      align: "left",
    });
  }

  // Decorative accent line
  slide.addShape(pptx.ShapeType.rect, {
    x: 0.8,
    y: 3.4,
    w: 2.0,
    h: 0.06,
    fill: { color: theme.accent_color },
    line: { type: "none" },
  });
}

function addSectionSlide(pptx, spec, theme) {
  const slide = pptx.addSlide();

  // Light background with accent
  slide.background = { color: theme.background_color };

  // Left accent bar
  slide.addShape(pptx.ShapeType.rect, {
    x: 0,
    y: 0,
    w: 0.15,
    h: "100%",
    fill: { color: theme.primary_color },
    line: { type: "none" },
  });

  // Section title
  slide.addText(spec.title || "Section", {
    x: 1.0,
    y: 2.5,
    w: "80%",
    h: 1.2,
    fontSize: 36,
    fontFace: theme.font_heading,
    color: theme.primary_color,
    bold: true,
    align: "left",
    valign: "middle",
  });

  // Section subtitle/description
  if (spec.subtitle) {
    slide.addText(spec.subtitle, {
      x: 1.0,
      y: 3.8,
      w: "75%",
      h: 0.8,
      fontSize: 16,
      fontFace: theme.font_body,
      color: theme.light_text_color,
      align: "left",
      valign: "top",
    });
  }
}

function addContentSlide(pptx, spec, theme) {
  const slide = pptx.addSlide();
  slide.background = { color: theme.background_color };

  // Top accent bar
  slide.addShape(pptx.ShapeType.rect, {
    x: 0,
    y: 0,
    w: "100%",
    h: 0.06,
    fill: { color: theme.primary_color },
    line: { type: "none" },
  });

  // Slide title
  const title = spec.title || "";
  if (title) {
    slide.addText(title, {
      x: 0.6,
      y: 0.3,
      w: "90%",
      h: 0.8,
      fontSize: 24,
      fontFace: theme.font_heading,
      color: theme.primary_color,
      bold: true,
      align: "left",
      valign: "middle",
    });
  }

  const contentY = title ? 1.3 : 0.5;
  const contentH = title ? 5.7 : 6.8;

  // Determine content type and render
  if (spec.bullets) {
    addBullets(slide, spec.bullets, 0.6, contentY, "90%", contentH, theme);
  } else if (spec.table) {
    addTable(slide, spec.table, 0.6, contentY, theme);
  } else if (spec.columns) {
    addColumns(slide, spec.columns, contentY, contentH, theme);
  } else if (spec.text) {
    slide.addText(spec.text, {
      x: 0.6,
      y: contentY,
      w: "90%",
      h: contentH,
      fontSize: 16,
      fontFace: theme.font_body,
      color: theme.text_color,
      align: "left",
      valign: "top",
      lineSpacing: 28,
    });
  }
}

function addSummarySlide(pptx, spec, theme) {
  const slide = pptx.addSlide();

  // Slightly tinted background
  slide.background = { color: "F5F7FA" };

  // Title with icon-like decoration
  slide.addShape(pptx.ShapeType.rect, {
    x: 0.6,
    y: 0.5,
    w: 0.08,
    h: 0.7,
    fill: { color: theme.accent_color },
    line: { type: "none" },
  });

  slide.addText(spec.title || "Summary", {
    x: 0.9,
    y: 0.4,
    w: "85%",
    h: 0.9,
    fontSize: 26,
    fontFace: theme.font_heading,
    color: theme.primary_color,
    bold: true,
    align: "left",
    valign: "middle",
  });

  // Summary bullets with checkmark style
  if (spec.bullets) {
    const bulletRows = spec.bullets.map((bullet) => ({
      text: `✓  ${bullet}`,
      options: {
        fontSize: 16,
        fontFace: theme.font_body,
        color: theme.text_color,
        bullet: false,
        lineSpacing: 36,
        paraSpaceBefore: 6,
      },
    }));

    slide.addText(bulletRows, {
      x: 0.8,
      y: 1.5,
      w: "85%",
      h: 5.0,
      valign: "top",
    });
  }

  // "Thank you" or closing text
  if (spec.closing) {
    slide.addText(spec.closing, {
      x: 0.6,
      y: 6.5,
      w: "90%",
      h: 0.5,
      fontSize: 12,
      fontFace: theme.font_body,
      color: theme.light_text_color,
      align: "right",
    });
  }
}

function addBullets(slide, bullets, x, y, w, h, theme) {
  const textRows = bullets.map((bullet) => {
    if (typeof bullet === "string") {
      return {
        text: bullet,
        options: {
          fontSize: 16,
          fontFace: theme.font_body,
          color: theme.text_color,
          bullet: { code: "2022" }, // bullet character •
          indentLevel: 0,
          lineSpacing: 32,
          paraSpaceBefore: 4,
          paraSpaceAfter: 4,
        },
      };
    }
    // Support nested bullets: {text: "...", level: 1}
    return {
      text: bullet.text,
      options: {
        fontSize: bullet.level > 0 ? 14 : 16,
        fontFace: theme.font_body,
        color: bullet.level > 0 ? theme.light_text_color : theme.text_color,
        bullet: { code: bullet.level > 0 ? "2013" : "2022" },
        indentLevel: bullet.level || 0,
        lineSpacing: 30,
        paraSpaceBefore: 2,
        paraSpaceAfter: 2,
      },
    };
  });

  slide.addText(textRows, { x, y, w, h, valign: "top" });
}

function addTable(slide, tableSpec, x, y, theme) {
  const headers = tableSpec.headers || [];
  const rows = tableSpec.rows || [];

  if (headers.length === 0) return;

  // Build table rows
  const tableRows = [];

  // Header row
  tableRows.push(
    headers.map((h) => ({
      text: String(h),
      options: {
        bold: true,
        fontSize: 13,
        fontFace: theme.font_body,
        color: "FFFFFF",
        fill: theme.primary_color,
        align: "center",
        valign: "middle",
      },
    }))
  );

  // Data rows with alternating colors
  rows.forEach((row, idx) => {
    tableRows.push(
      row.map((cell) => ({
        text: String(cell),
        options: {
          fontSize: 12,
          fontFace: theme.font_body,
          color: theme.text_color,
          fill: idx % 2 === 0 ? "F8F9FA" : "FFFFFF",
          align: "center",
          valign: "middle",
        },
      }))
    );
  });

  // Calculate column widths
  const availableWidth = 11.0; // for widescreen
  const colWidth = Math.min(3.0, (availableWidth - x * 2) / headers.length);

  slide.addTable(tableRows, {
    x,
    y,
    w: colWidth * headers.length,
    colW: colWidth,
    rowH: 0.5,
    border: { type: "solid", pt: 0.5, color: "DEE2E6" },
    autoPage: false,
  });
}

function addColumns(slide, columns, contentY, contentH, theme) {
  const colCount = columns.length;
  const totalWidth = 11.5; // usable width
  const gap = 0.4;
  const startX = 0.6;
  const colWidth = (totalWidth - startX * 2 - gap * (colCount - 1)) / colCount;

  columns.forEach((col, idx) => {
    const colX = startX + idx * (colWidth + gap);

    // Column header if present
    let bulletY = contentY;
    if (col.title) {
      slide.addText(col.title, {
        x: colX,
        y: contentY,
        w: colWidth,
        h: 0.6,
        fontSize: 16,
        fontFace: theme.font_heading,
        color: theme.secondary_color,
        bold: true,
        align: "left",
        valign: "bottom",
      });
      bulletY += 0.7;
    }

    // Column content
    if (col.bullets) {
      addBullets(
        slide,
        col.bullets,
        colX,
        bulletY,
        colWidth,
        contentH - (bulletY - contentY),
        theme
      );
    } else if (col.text) {
      slide.addText(col.text, {
        x: colX,
        y: bulletY,
        w: colWidth,
        h: contentH - (bulletY - contentY),
        fontSize: 14,
        fontFace: theme.font_body,
        color: theme.text_color,
        align: "left",
        valign: "top",
        lineSpacing: 26,
      });
    }
  });
}

// --- Main ---
async function main() {
  const args = process.argv.slice(2);

  if (args.length === 0) {
    console.error("Usage: node create_deck.js <config.json> [output.pptx]");
    process.exit(1);
  }

  const configPath = args[0];
  const outputOverride = args[1];

  // Load config
  let config;
  try {
    const raw = fs.readFileSync(configPath, "utf-8");
    config = JSON.parse(raw);
  } catch (err) {
    console.error(`Error reading config: ${err.message}`);
    process.exit(1);
  }

  // Determine output path
  const outputPath = outputOverride || config.output || "output.pptx";

  // Create presentation
  const pptx = createPresentation(config);

  // Save
  try {
    const outputDir = path.dirname(outputPath);
    if (outputDir && !fs.existsSync(outputDir)) {
      fs.mkdirSync(outputDir, { recursive: true });
    }
    await pptx.writeFile({ fileName: outputPath });
    console.error(`Output saved to: ${outputPath}`);
  } catch (err) {
    console.error(`Error saving file: ${err.message}`);
    process.exit(1);
  }
}

main();
