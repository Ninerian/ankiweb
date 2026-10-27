import { build } from "esbuild";
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join, relative, sep } from "node:path";

const staticDir = "ankiweb/shell/static";
const devStaticDir = "ankiweb/shell/dev-static";
const cssOnly = process.argv.includes("--css-only");
const dev = process.argv.includes("--dev");
if (!dev) rmSync(devStaticDir, { recursive: true, force: true });
mkdirSync(staticDir, { recursive: true });

if (!cssOnly) {
  await build({
    entryPoints: ["shell_src/bootstrap.ts"],
    bundle: true,
    format: "iife",
    target: "es2020",
    outfile: `${staticDir}/bootstrap.js`,
  });
  console.log(`built ${staticDir}/bootstrap.js`);

  copyFileSync("shell_src/dialogs.js", `${staticDir}/dialogs.js`);
  console.log(`copied dialogs.js -> ${staticDir}/dialogs.js`);
}

// Compile each public stylesheet separately. @reference shares the app's Tailwind
// and daisyUI definitions without emitting a second copy of the framework.
const cliPackage = fileURLToPath(import.meta.resolve("@tailwindcss/cli/package.json"));
const tailwindCli = join(dirname(cliPackage), JSON.parse(readFileSync(cliPackage, "utf8")).bin.tailwindcss);
const compileCss = (input, output) =>
  execFileSync(process.execPath, [tailwindCli, "-i", input, "-o", output, "--minify"], { stdio: "inherit" });

compileCss("shell_src/app.css", `${staticDir}/app.css`);
// theme.css imports the unlayered Anki compatibility shim before owned styles.
compileCss("shell_src/theme.css", `${staticDir}/theme.css`);

if (dev) {
  mkdirSync(devStaticDir, { recursive: true });
  compileCss("shell_src/dev/gallery.css", `${devStaticDir}/gallery.css`);
}

// Keep sorted auto-discovery while giving Tailwind real CSS imports to compile.
// Manual imports may be added to shell_src/components.css; component files
// themselves are wrapped in the existing components layer.
const entryDir = mkdtempSync(join(staticDir, ".components-entry-"));
try {
  const cssImport = (file) => {
    let path = relative(entryDir, file).split(sep).join("/");
    if (!path.startsWith(".")) path = `./${path}`;
    return JSON.stringify(path);
  };
  const files = existsSync("shell_src/components")
    ? readdirSync("shell_src/components").filter(f => f.endsWith(".css")).sort()
    : [];
  const imports = [
    `@import ${cssImport("shell_src/components.css")};`,
    ...files.map(f => `@import ${cssImport(join("shell_src/components", f))} layer(components);`),
  ];
  const entry = join(entryDir, "components.css");
  writeFileSync(entry, `${imports.join("\n")}\n`);
  compileCss(entry, `${staticDir}/components.css`);
  console.log(`built ${staticDir}/components.css from ${files.length} css files`);
} finally {
  rmSync(entryDir, { recursive: true, force: true });
}

// Page bundles: every top-level shell_src/bundles/*.ts|js is an esbuild entry point and
// becomes ankiweb/shell/static/bundles/<name>.js (IIFE). Helper modules live in subfolders
// and are only imported, never entries. No build-script edit is needed to add a bundle.
if (!cssOnly && existsSync("shell_src/bundles")) {
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
