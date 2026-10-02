/**
 * Format commands and toolbar actions
 */
import { Surrounder, removeAllFormatting, MatchContext, cleanEmptyAttributes } from "./surround";
import { insertCloze } from "./cloze";
import { getEditingHost, rememberFocusedHost } from "./host";

export const surrounder = new Surrounder();

// Register standard inline formats
surrounder.registerFormat("bold", {
    tagName: "b",
    matcher: (el, ctx) => {
        if (el.tagName === "B" || el.tagName === "STRONG") {
            ctx.remove();
            return;
        }
        const weight = (el as HTMLElement).style?.fontWeight;
        if (weight === "bold" || Number(weight) >= 700) {
            ctx.clear(() => {
                (el as HTMLElement).style.removeProperty("font-weight");
                if (!(el as HTMLElement).style.cssText && !el.className) {
                    ctx.remove();
                }
            });
        }
    },
});

surrounder.registerFormat("italic", {
    tagName: "i",
    matcher: (el, ctx) => {
        if (el.tagName === "I" || el.tagName === "EM") {
            ctx.remove();
            return;
        }
        const style = (el as HTMLElement).style?.fontStyle;
        if (style === "italic") {
            ctx.clear(() => {
                (el as HTMLElement).style.removeProperty("font-style");
                if (!(el as HTMLElement).style.cssText && !el.className) {
                    ctx.remove();
                }
            });
        }
    },
});

surrounder.registerFormat("underline", {
    tagName: "u",
    matcher: (el, ctx) => {
        if (el.tagName === "U") {
            ctx.remove();
            return;
        }
        const textDec = (el as HTMLElement).style?.textDecoration;
        if (textDec?.includes("underline")) {
            ctx.clear(() => {
                (el as HTMLElement).style.removeProperty("text-decoration");
                if (!(el as HTMLElement).style.cssText && !el.className) {
                    ctx.remove();
                }
            });
        }
    },
});
surrounder.registerFormat("strikethrough", {
    tagName: "s",
    matcher: (el, ctx) => {
        if (el.tagName === "S" || el.tagName === "STRIKE" || el.tagName === "DEL") {
            ctx.remove();
            return;
        }
        const textDec = (el as HTMLElement).style?.textDecoration;
        if (textDec?.includes("line-through")) {
            ctx.clear(() => {
                (el as HTMLElement).style.removeProperty("text-decoration");
                if (!(el as HTMLElement).style.cssText && !el.className) {
                    ctx.remove();
                }
            });
        }
    },
});
surrounder.registerFormat("subscript", {
    tagName: "sub",
    exclusiveNames: ["superscript"],
    matcher: (el, ctx) => {
        if (el.tagName === "SUB") {
            ctx.remove();
            return;
        }
        const va = (el as HTMLElement).style?.verticalAlign;
        if (va === "sub") {
            ctx.clear(() => {
                (el as HTMLElement).style.removeProperty("vertical-align");
                if (!(el as HTMLElement).style.cssText && !el.className) {
                    ctx.remove();
                }
            });
        }
    },
});

surrounder.registerFormat("superscript", {
    tagName: "sup",
    exclusiveNames: ["subscript"],
    matcher: (el, ctx) => {
        if (el.tagName === "SUP") {
            ctx.remove();
            return;
        }
        const va = (el as HTMLElement).style?.verticalAlign;
        if (va === "super") {
            ctx.clear(() => {
                (el as HTMLElement).style.removeProperty("vertical-align");
                if (!(el as HTMLElement).style.cssText && !el.className) {
                    ctx.remove();
                }
            });
        }
    },
});

export function executeCommand(cmd: string, arg?: string): void {
    const richHost = getEditingHost();
    if (!richHost) return;
    // Toolbar buttons keep field focus on press; other triggers (colour picker, menus, the
    // toolbar while no field is focused) need the caret put back into the target field.
    if (!richHost.contains(document.activeElement)) richHost.focus();
    switch (cmd) {
        case "bold":
            document.execCommand("bold", false, undefined);
            break;
        case "italic":
            document.execCommand("italic", false, undefined);
            break;
        case "underline":
            document.execCommand("underline", false, undefined);
            break;
        case "strikethrough":
        case "strikeThrough":
            document.execCommand("strikeThrough", false, undefined);
            break;
        case "subscript":
            document.execCommand("subscript", false, undefined);
            break;
        case "superscript":
            document.execCommand("superscript", false, undefined);
            break;
        case "removeFormat":
            if (arg) {
                if (surrounder.hasFormat(arg)) {
                    surrounder.removeFormat(arg, richHost);
                } else {
                    document.execCommand("removeFormat", false, undefined);
                }
            } else {
                removeAllFormatting(richHost);
            }
            break;
        case "insertUnorderedList":
            document.execCommand("insertUnorderedList", false, undefined);
            break;
        case "insertOrderedList":
            document.execCommand("insertOrderedList", false, undefined);
            break;
        case "justifyLeft":
            document.execCommand("justifyLeft", false, undefined);
            break;
        case "justifyCenter":
            document.execCommand("justifyCenter", false, undefined);
            break;
        case "justifyRight":
            document.execCommand("justifyRight", false, undefined);
            break;
        case "justifyFull":
            document.execCommand("justifyFull", false, undefined);
            break;
        case "foreColor":
        case "textColor":
            if (arg) {
                document.execCommand("foreColor", false, arg);
            }
            break;
        case "hiliteColor":
        case "highlightColor":
            if (arg) {
                document.execCommand("hiliteColor", false, arg);
            }
            break;
        case "fontName":
            if (arg) {
                document.execCommand("fontName", false, arg);
            }
            break;
        case "fontSize":
            if (arg) {
                document.execCommand("fontSize", false, arg);
            }
            break;
        case "cloze":
            insertCloze(true, richHost);
            break;
        case "cloze-same-number":
            insertCloze(false, richHost);
            break;
        default:
            try {
                document.execCommand(cmd, false, arg);
            } catch (err) {
                console.warn("Unknown command:", cmd, err);
            }
            break;
    }

    cleanEmptyAttributes(richHost);

    // Trigger input event to update state and listeners
    richHost.dispatchEvent(new Event("input", { bubbles: true }));
    updateToolbarState();
}

export function updateToolbarState(): void {
    rememberFocusedHost();
    const active = document.activeElement;
    const richHost = active?.closest<HTMLElement>("[data-ankiweb-rich]");

    const buttons = document.querySelectorAll<HTMLElement>("[data-editor-command]");
    buttons.forEach((btn) => {
        const cmd = btn.getAttribute("data-editor-command");
        if (!cmd) return;

        if (!richHost) {
            btn.classList.remove("btn-active");
            return;
        }

        try {
            let isActive = false;
            if (["bold", "italic", "underline", "strikethrough", "strikeThrough", "subscript", "superscript", "insertUnorderedList", "insertOrderedList", "justifyLeft", "justifyCenter", "justifyRight", "justifyFull"].includes(cmd)) {
                isActive = document.queryCommandState(cmd === "strikethrough" ? "strikeThrough" : cmd);
            }
            btn.classList.toggle("btn-active", isActive);
        } catch {
            btn.classList.remove("btn-active");
        }
    });
}
