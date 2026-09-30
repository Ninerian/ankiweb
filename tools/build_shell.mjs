import { build } from "esbuild";
import { mkdirSync, copyFileSync, readdirSync, readFileSync, writeFileSync, existsSync } from "node:fs";
mkdirSync("ankiweb/shell/static", { recursive: true });
await build({
  entryPoints: ["shell_src/bootstrap.ts"],
  bundle: true,
  format: "iife",
  target: "es2020",
  outfile: "ankiweb/shell/static/bootstrap.js",
});
console.log("built ankiweb/shell/static/bootstrap.js");

// Plain (non-bundled) shell assets: tracked in shell_src/, served from the gitignored
// static dir like bootstrap.js so the Docker frontend stage ships them too.
for (const f of ["theme.css", "dialogs.js"]) {
  copyFileSync(`shell_src/${f}`, `ankiweb/shell/static/${f}`);
  console.log(`copied ${f} -> ankiweb/shell/static/${f}`);
}

// Bundle any scoped component CSS files from shell_src/components/

if (existsSync("shell_src/components")) {
  const files = readdirSync("shell_src/components").filter(f => f.endsWith(".css")).sort();
  let combined = "/* Generated from shell_src/components/*.css */\n";
  for (const f of files) {
    combined += readFileSync(`shell_src/components/${f}`, "utf8") + "\n";
  }
  writeFileSync("ankiweb/shell/static/components.css", combined);
  console.log(`built ankiweb/shell/static/components.css from ${files.length} css files`);
}

// Page bundles: every top-level shell_src/bundles/*.ts|js is an esbuild entry point and
// becomes ankiweb/shell/static/bundles/<name>.js (IIFE). Helper modules live in subfolders
// and are only imported, never entries. No build-script edit is needed to add a bundle.
if (existsSync("shell_src/bundles")) {
  const entries = readdirSync("shell_src/bundles")
    .filter(f => /\.(ts|js)$/.test(f))
    .sort()
    .map(f => `shell_src/bundles/${f}`);
  if (entries.length) {
    mkdirSync("ankiweb/shell/static/bundles", { recursive: true });
    await build({
      entryPoints: entries,
      bundle: true,
      format: "iife",
      target: "es2020",
      outdir: "ankiweb/shell/static/bundles",
    });
    console.log(`built ${entries.length} bundle(s) -> ankiweb/shell/static/bundles/`);
  }
}
