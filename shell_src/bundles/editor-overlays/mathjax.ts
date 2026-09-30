/**
 * Delimiters and transformations for MathJax in Anki.
 * Storage forms:
 *   Inline: \(...\)
 *   Block:  \[...\]
 * Presentation in editor:
 *   <anki-mathjax block="true" data-mathjax="..."> or <anki-mathjax data-mathjax="...">
 */

const MATHJAX_BLOCK_RE = /\\\[([\s\S]*?)\\\]/g;
const MATHJAX_INLINE_RE = /\\\(([\s\S]*?)\\\)/g;
const ANKI_MATHJAX_TAG_RE = /<anki-mathjax(?:\s+[^>]*?block="(.*?)")?[^>]*?>([\s\S]*?)<\/anki-mathjax>/gi;

function escapeHtml(text: string): string {
    return text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

/**
 * Converts stored \(...\) and \[...\] delimiters into <anki-mathjax> tags for editing.
 */
export function toUndecoratedMathjax(html: string): string {
    if (!html) return "";
    let res = html.replace(MATHJAX_BLOCK_RE, (_match, content) => {
        const clean = content.replace(/<br\s*\/?>/gi, "\n");
        return `<anki-mathjax block="true" data-mathjax="${escapeHtml(clean)}">${clean}</anki-mathjax>`;
    });
    res = res.replace(MATHJAX_INLINE_RE, (_match, content) => {
        const clean = content.replace(/<br\s*\/?>/gi, "\n");
        return `<anki-mathjax data-mathjax="${escapeHtml(clean)}">${clean}</anki-mathjax>`;
    });
    return res;
}

/**
 * Converts <anki-mathjax> tags back to stored \(...\) and \[...\] delimiters.
 */
export function toStoredMathjax(html: string): string {
    if (!html) return "";
    // Parse with DOM to properly read data-mathjax or content without inner preview HTML
    const temp = document.createElement("template");
    temp.innerHTML = html;
    const nodes = temp.content.querySelectorAll("anki-mathjax");
    nodes.forEach(node => {
        const isBlock = node.getAttribute("block") === "true";
        const raw = node.getAttribute("data-mathjax") || node.textContent || "";
        const clean = raw.replace(/<br\s*\/?>/gi, "\n").trim();
        const delim = isBlock ? `\\[${clean}\\]` : `\\(${clean}\\)`;
        node.replaceWith(document.createTextNode(delim));
    });
    return temp.innerHTML;
}
interface MathJaxGlobal {
    tex2svg?: (tex: string, options?: { display: boolean }) => HTMLElement;
}

/**
 * Render an SVG preview or placeholder for LaTeX / MathJax string.
 */
export function renderMathjaxSvg(tex: string, isBlock: boolean): { svgHtml: string; error?: string } {
    const win = window as unknown as Record<string, unknown>;
    if ("MathJax" in win && win.MathJax && typeof win.MathJax === "object" && "tex2svg" in win.MathJax) {
        const mj = win.MathJax as MathJaxGlobal;
        if (typeof mj.tex2svg === "function") {
            try {
                const node = mj.tex2svg(tex, { display: isBlock });
                return { svgHtml: node.outerHTML };
            } catch (e: unknown) {
                return { svgHtml: "", error: String(e) };
            }
        }
    }
    return {
        svgHtml: `<span class="badge ${isBlock ? "bg-primary" : "bg-info"} font-monospace py-1 px-2">${escapeHtml(tex || "(empty)")}</span>`
    };
}
