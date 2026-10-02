/**
 * Port of ts/lib/html-filter/
 * Basic, Extended, and Internal filtering modes matching Anki desktop/web behavior.
 */

export enum FilterMode {
    Basic = 0,
    Extended = 1,
    Internal = 2,
}

const VOID_ELEMENTS = new Set([
    "AREA", "BASE", "BR", "COL", "EMBED", "HR", "IMG", "INPUT",
    "LINK", "META", "PARAM", "SOURCE", "TRACK", "WBR"
]);

function removeNode(node: Node) {
    if (node.parentNode) {
        node.parentNode.removeChild(node);
    }
}

function unwrapNode(node: Node) {
    if (!node.parentNode) return;
    while (node.firstChild) {
        node.parentNode.insertBefore(node.firstChild, node);
    }
    node.parentNode.removeChild(node);
}

function forEachChild(node: Node, fn: (child: Node) => void) {
    const children = Array.from(node.childNodes);
    for (const child of children) {
        fn(child);
    }
}

// Tree walker
function walkTree(node: Node, filterFn: (el: HTMLElement) => void) {
    switch (node.nodeType) {
        case Node.COMMENT_NODE:
            removeNode(node);
            break;
        case Node.DOCUMENT_FRAGMENT_NODE:
            forEachChild(node, child => walkTree(child, filterFn));
            break;
        case Node.ELEMENT_NODE:
            forEachChild(node, child => walkTree(child, filterFn));
            if (node instanceof HTMLElement) {
                filterFn(node);
            }
            break;
        default:
            break;
    }
}

// Style filtering
type StylePredicate = (el: HTMLElement, prop: string, val: string) => boolean;

const allowAll: StylePredicate = () => true;
const denyAll: StylePredicate = () => false;
const notImg: StylePredicate = (el) => el.nodeName !== "IMG";

function createStyleFilter(defaultPred: StylePredicate, overrides: Record<string, StylePredicate>) {
    return (el: HTMLElement) => {
        if (!el.style || !el.style.length) return;
        const toRemove: string[] = [];
        for (let i = 0; i < el.style.length; i++) {
            const prop = el.style.item(i);
            const val = el.style.getPropertyValue(prop);
            const pred = overrides[prop] ?? defaultPred;
            if (!pred(el, prop, val)) {
                toRemove.push(prop);
            }
        }
        for (const prop of toRemove) {
            el.style.removeProperty(prop);
        }
        if (el.style.length === 0) {
            el.removeAttribute("style");
        }
    };
}

const standardTextStyles: Record<string, StylePredicate> = {
    "font-weight": allowAll,
    "font-style": allowAll,
    "text-decoration-line": allowAll,
    "text-decoration": allowAll,
};

const filterStylesNight = createStyleFilter(denyAll, { ...standardTextStyles });
const filterStylesDay = createStyleFilter(denyAll, {
    color: allowAll,
    "background-color": (_el, _prop, val) => val !== "transparent",
    ...standardTextStyles,
});

const filterStylesInternal = createStyleFilter(allowAll, {
    "font-size": denyAll,
    "font-family": denyAll,
    width: denyAll,
    height: denyAll,
    "max-width": denyAll,
    "max-height": denyAll,
    "vertical-align": notImg,
});

function isNightMode(): boolean {
    return document.body.classList.contains("nightMode") || document.documentElement.getAttribute("data-theme") === "dark";
}

function filterAttributes(predicate: (attrName: string) => boolean, el: HTMLElement) {
    const attrs = Array.from(el.attributes);
    for (const attr of attrs) {
        if (!predicate(attr.name.toUpperCase())) {
            el.removeAttribute(attr.name);
        }
    }
}

const stripAllAttributes = (el: HTMLElement) => filterAttributes(() => false, el);
const allowAttrs = (allowed: string[]) => (el: HTMLElement) => filterAttributes(name => allowed.includes(name), el);

function convertPToDiv(el: HTMLElement) {
    const div = document.createElement("div");
    div.innerHTML = el.innerHTML;
    el.replaceWith(div);
}

function filterSpan(el: HTMLElement) {
    allowAttrs(["STYLE"])(el);
    if (isNightMode()) {
        filterStylesNight(el);
    } else {
        filterStylesDay(el);
    }
    // If span has no style and no attributes, unwrap it
    if (el.attributes.length === 0) {
        unwrapNode(el);
    }
}

// Basic rules (plain text / paste strips formatting)
const BasicElementRules: Record<string, (el: HTMLElement) => void> = {
    BR: stripAllAttributes,
    IMG: allowAttrs(["SRC", "ALT", "WIDTH", "HEIGHT"]),
    DIV: stripAllAttributes,
    P: convertPToDiv,
    SUB: stripAllAttributes,
    SUP: stripAllAttributes,
    TITLE: removeNode,
    SCRIPT: removeNode,
    IFRAME: removeNode,
    OBJECT: removeNode,
    STYLE: removeNode,
    NOSCRIPT: removeNode,
    TEMPLATE: removeNode,
};

// Extended rules (paste preserving formatting)
const ExtendedElementRules: Record<string, (el: HTMLElement) => void> = {
    ...BasicElementRules,
    A: allowAttrs(["HREF"]),
    B: stripAllAttributes,
    BLOCKQUOTE: stripAllAttributes,
    CODE: stripAllAttributes,
    DD: stripAllAttributes,
    DL: stripAllAttributes,
    DT: stripAllAttributes,
    EM: stripAllAttributes,
    FONT: allowAttrs(["COLOR"]),
    H1: stripAllAttributes,
    H2: stripAllAttributes,
    H3: stripAllAttributes,
    I: stripAllAttributes,
    LI: stripAllAttributes,
    OL: stripAllAttributes,
    PRE: stripAllAttributes,
    RP: stripAllAttributes,
    RT: stripAllAttributes,
    RUBY: stripAllAttributes,
    SPAN: filterSpan,
    STRONG: stripAllAttributes,
    TABLE: stripAllAttributes,
    TD: allowAttrs(["COLSPAN", "ROWSPAN"]),
    TH: allowAttrs(["COLSPAN", "ROWSPAN"]),
    TR: allowAttrs(["ROWSPAN"]),
    U: stripAllAttributes,
    UL: stripAllAttributes,
};

function createElementFilter(rules: Record<string, (el: HTMLElement) => void>) {
    return (el: HTMLElement) => {
        const tag = el.tagName.toUpperCase();
        if (Object.prototype.hasOwnProperty.call(rules, tag)) {
            rules[tag](el);
        } else if (el.innerHTML) {
            unwrapNode(el);
        } else {
            removeNode(el);
        }
    };
}

const basicFilter = createElementFilter(BasicElementRules);
const extendedFilter = createElementFilter(ExtendedElementRules);
function internalFilter(el: HTMLElement) {
    filterStylesInternal(el);
}

const FilterMap: Record<FilterMode, (el: HTMLElement) => void> = {
    [FilterMode.Basic]: basicFilter,
    [FilterMode.Extended]: extendedFilter,
    [FilterMode.Internal]: internalFilter,
};

export function filterHTML(html: string, mode: FilterMode = FilterMode.Basic): string {
    if (!html) return "";
    const template = document.createElement("template");
    template.innerHTML = html;
    const filter = FilterMap[mode];
    walkTree(template.content, filter);

    let res = template.innerHTML;
    if (mode === FilterMode.Basic) {
        res = res.replace(/[\n\t ]+/g, " ").trim();
    } else {
        res = res.trim();
    }
    return res;
}
