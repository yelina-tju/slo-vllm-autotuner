# Markdown formula renderer

The rendered project documents use local SVG equations so they display in
Markdown viewers without built-in LaTeX support. Edit the corresponding
`*_LATEX.md` source, then run these commands from the repository root (replace
the two document paths when rendering another file):

```powershell
pnpm install --dir tools/formula-renderer
node tools/formula-renderer/render.mjs `
  docs/PROJECT_GUIDE_ZH_LATEX.md `
  docs/PROJECT_GUIDE_ZH.md `
  docs/assets/formulas
```

The renderer writes deterministic, content-addressed SVG filenames and a
formula manifest. `node_modules` is intentionally ignored by Git.
