import { build } from "esbuild";
import { mkdirSync, copyFileSync } from "node:fs";
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
