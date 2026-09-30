/**
 * Tag utilities matching upstream Anki ts/lib/tag-editor/tags.ts
 */

export const UNICODE_SEPARATOR = "∷"; // \u2237

export function replaceWithUnicodeSeparator(tag: string): string {
    return tag.replace(/::/g, UNICODE_SEPARATOR);
}

export function replaceWithColons(tag: string): string {
    return tag.replace(/\u2237/gu, "::");
}

export function normalizeTag(tag: string): string {
    let t = tag.trim();
    while (t.startsWith(":") || t.startsWith(UNICODE_SEPARATOR)) {
        t = t.slice(1).trimStart();
    }
    while (t.endsWith(":") || t.endsWith(UNICODE_SEPARATOR)) {
        t = t.slice(0, -1).trimEnd();
    }
    return t;
}

export function shortenTag(tag: string): string {
    const parts = tag.split(UNICODE_SEPARATOR);
    return parts.length === 1 ? tag : `…${UNICODE_SEPARATOR}${parts[parts.length - 1]}`;
}

export function isHierarchical(tag: string): boolean {
    return tag.includes(UNICODE_SEPARATOR);
}

export interface TagItem {
    id: string;
    name: string; // Displayed with UNICODE_SEPARATOR
    selected: boolean;
    flash?: () => void;
}

export function createTagItem(name: string): TagItem {
    return {
        id: Math.random().toString(36).substring(2, 9),
        name: replaceWithUnicodeSeparator(name),
        selected: false,
    };
}
