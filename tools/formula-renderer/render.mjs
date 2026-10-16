import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";

import { liteAdaptor } from "mathjax-full/js/adaptors/liteAdaptor.js";
import { RegisterHTMLHandler } from "mathjax-full/js/handlers/html.js";
import { AllPackages } from "mathjax-full/js/input/tex/AllPackages.js";
import { TeX } from "mathjax-full/js/input/tex.js";
import { mathjax } from "mathjax-full/js/mathjax.js";
import { SVG } from "mathjax-full/js/output/svg.js";

const [inputArg, outputArg, assetDirArg] = process.argv.slice(2);
if (!inputArg || !outputArg || !assetDirArg) {
  throw new Error(
    "usage: node render.mjs INPUT.md OUTPUT.md ASSET_DIRECTORY",
  );
}

const inputPath = path.resolve(inputArg);
const outputPath = path.resolve(outputArg);
const assetDir = path.resolve(assetDirArg);
const markdownAssetPrefix = path
  .relative(path.dirname(outputPath), assetDir)
  .split(path.sep)
  .join("/");

const adaptor = liteAdaptor();
RegisterHTMLHandler(adaptor);
const tex = new TeX({ packages: AllPackages });
const svgOutput = new SVG({ fontCache: "local" });
const document = mathjax.document("", { InputJax: tex, OutputJax: svgOutput });

await mkdir(assetDir, { recursive: true });
let markdown = await readFile(inputPath, "utf8");
const manifestPath = path.join(assetDir, "manifest.json");
let manifest = {};
try {
  manifest = JSON.parse(await readFile(manifestPath, "utf8"));
} catch (error) {
  if (error?.code !== "ENOENT") throw error;
}

async function renderFormula(source, display) {
  const normalized = source.trim();
  const digest = createHash("sha256")
    .update(`${display ? "display" : "inline"}\0${normalized}`)
    .digest("hex")
    .slice(0, 16);
  const filename = `${display ? "display" : "inline"}-${digest}.svg`;
  const outputFile = path.join(assetDir, filename);
  const container = document.convert(normalized, { display });
  const svgNode = adaptor.firstChild(container);
  let svg = adaptor.outerHTML(svgNode);
  const adaptiveColor = [
    "<style>",
    ":root{color:#1f2328}",
    "@media(prefers-color-scheme:dark){:root{color:#f0f6fc}}",
    "</style>",
  ].join("");
  svg = svg.replace(">", `>${adaptiveColor}`);
  await writeFile(outputFile, `${svg}\n`, "utf8");
  manifest[filename] = { display, latex: normalized };
  return {
    filename,
  };
}

const displayPattern = /^\$\$\s*\r?\n([\s\S]*?)\r?\n\$\$/gm;
const displayMatches = [...markdown.matchAll(displayPattern)];
for (const match of displayMatches) {
  const rendered = await renderFormula(match[1], true);
  const replacement = `![公式](${markdownAssetPrefix}/${rendered.filename})`;
  markdown = markdown.replace(match[0], replacement);
}

const inlinePattern = /\\\((.+?)\\\)/g;
const inlineMatches = [...markdown.matchAll(inlinePattern)];
for (const match of inlineMatches) {
  const rendered = await renderFormula(match[1], false);
  const replacement = `![公式](${markdownAssetPrefix}/${rendered.filename})`;
  markdown = markdown.replace(match[0], replacement);
}

const renderingNote = [
  "",
  `> 本文件中的公式已预渲染为本地 SVG，因此不依赖 Markdown 预览器的 LaTeX 支持。请在 [LaTeX 源文档](${path.basename(inputPath)}) 中编辑内容，重新生成方法见 [公式渲染说明](../tools/formula-renderer/README.md)。`,
  "",
].join("\n");
const firstLineEnd = markdown.indexOf("\n");
markdown = `${markdown.slice(0, firstLineEnd + 1)}${renderingNote}${markdown.slice(firstLineEnd + 1)}`;

await writeFile(outputPath, markdown, "utf8");
await writeFile(
  manifestPath,
  `${JSON.stringify(manifest, null, 2)}\n`,
  "utf8",
);

console.log(
  `rendered ${displayMatches.length} display and ${inlineMatches.length} inline formulas`,
);
