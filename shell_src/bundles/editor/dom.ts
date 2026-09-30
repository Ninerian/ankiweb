/**
 * DOM node inspection & traversal utilities ported from Anki ts/lib/domlib
 */

export function isElement(node: Node): node is Element {
    return node.nodeType === Node.ELEMENT_NODE;
}

export function isHTMLElement(node: Node): node is HTMLElement {
    return node instanceof HTMLElement || node instanceof SVGElement;
}

export function isTextNode(node: Node): node is Text {
    return node.nodeType === Node.TEXT_NODE;
}

export function isCommentNode(node: Node): node is Comment {
    return node.nodeType === Node.COMMENT_NODE;
}

export const BLOCK_TAGS = [
    "ADDRESS", "ARTICLE", "ASIDE", "BLOCKQUOTE", "DETAILS", "DIALOG", "DD", "DIV", "DL", "DT",
    "FIELDSET", "FIGCAPTION", "FIGURE", "FOOTER", "FORM", "H1", "H2", "H3", "H4", "H5", "H6",
    "HEADER", "HGROUP", "HR", "LI", "MAIN", "NAV", "OL", "P", "PRE", "SECTION", "TABLE", "UL"
];

export function hasBlockAttribute(elem: Element): boolean {
    return elem.hasAttribute("block") && elem.getAttribute("block") !== "false";
}

export function isBlockElement(elem: Element): boolean {
    return BLOCK_TAGS.includes(elem.tagName) || hasBlockAttribute(elem);
}

export const VOID_TAGS = [
    "AREA", "BASE", "BR", "COL", "EMBED", "HR", "IMG", "INPUT", "LINK", "META", "PARAM", "SOURCE", "TRACK", "WBR"
];

export function isVoidElement(elem: Element): boolean {
    return VOID_TAGS.includes(elem.tagName);
}

export function isEmptyTextNode(node: Node): boolean {
    return isTextNode(node) && (node.length === 0 || /^\s*$/.test(node.data));
}

export function isEmptyBlock(elem: Element): boolean {
    if (!isBlockElement(elem)) return false;
    if (elem.childNodes.length === 0) return true;
    if (elem.childNodes.length === 1 && elem.firstChild && elem.firstChild.nodeName === "BR") return true;
    return false;
}

export function findAncestor(node: Node, base: Node, predicate: (el: Element) => boolean): Element | null {
    if (isElement(node) && predicate(node)) return node;
    let parent = node === base ? null : node.parentElement;
    while (parent && parent !== base) {
        if (predicate(parent)) return parent;
        parent = parent.parentElement;
    }
    return null;
}

export function findDeepestAncestor(node: Node, base: Node, predicate: (el: Element) => boolean): Element | null {
    let result: Element | null = null;
    let curr: Node | null = node;
    while (curr && curr !== base) {
        const found = findAncestor(curr, base, predicate);
        if (found) {
            result = found;
            curr = found.parentElement;
        } else {
            break;
        }
    }
    return result;
}

export function removeNode(node: Node): void {
    if (node.parentNode) {
        node.parentNode.removeChild(node);
    }
}

export function removeAllChildren(node: Node): void {
    while (node.firstChild) {
        node.removeChild(node.firstChild);
    }
}

export function setCaretToEnd(el: Node): void {
    const range = new Range();
    range.selectNodeContents(el);
    range.collapse(false);
    const sel = (el.getRootNode() as Document | ShadowRoot).getSelection?.() || document.getSelection();
    if (sel) {
        sel.removeAllRanges();
        sel.addRange(range);
    }
}
