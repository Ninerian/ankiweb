/**
 * Custom element <anki-mathjax> and MathJax edit modal / popover.
 */
import { renderMathjaxSvg, toStoredMathjax } from "./mathjax";
import { saveSelection, restoreSelection } from "../editor/selection";
import { setCaretToEnd } from "../editor/dom";

let activeModal: HTMLDialogElement | null = null;

function ensureMathjaxModal(): HTMLDialogElement {
    if (!activeModal) {
        activeModal = document.createElement("dialog") as HTMLDialogElement;
        activeModal.className = "ankiweb-mathjax-modal modal";
        activeModal.innerHTML = `
            <div class="modal-box max-w-lg">
                <div class="flex justify-between items-center pb-2">
                    <h3 class="font-bold text-base m-0">Edit MathJax Equation</h3>
                    <button type="button" class="btn btn-sm btn-circle btn-ghost mj-close-btn" aria-label="Close">✕</button>
                </div>
                <div class="py-2">
                    <div class="mb-2">
                        <label class="label text-sm font-bold">Formula (TeX / LaTeX):</label>
                        <textarea class="textarea w-full font-mono mj-input" rows="3" placeholder="e.g. \\frac{a}{b} or \\sqrt{x}"></textarea>
                    </div>
                    <div class="flex items-center gap-2 mb-2">
                        <input class="toggle toggle-primary mj-block-switch" type="checkbox" id="mj-block-toggle">
                        <label class="text-sm cursor-pointer" for="mj-block-toggle">Display as Block equation (\\[ ... \\])</label>
                    </div>
                    <div class="border border-base-300 rounded-box p-2 bg-base-200 mj-preview-box" style="min-height: 48px; display: flex; align-items: center; justify-content: center;">
                        <div class="mj-preview-content"></div>
                    </div>
                </div>
                <div class="modal-action flex justify-between items-center pt-2">
                    <button type="button" class="btn btn-sm btn-outline btn-error mj-delete-btn">Delete</button>
                    <div class="flex gap-2">
                        <button type="button" class="btn btn-sm btn-ghost mj-close-btn">Cancel</button>
                        <button type="button" class="btn btn-sm btn-primary mj-save-btn">Save (Enter)</button>
                    </div>
                </div>
            </div>
            <form method="dialog" class="modal-backdrop">
                <button>close</button>
            </form>
        `;
        document.body.appendChild(activeModal);
    }
    return activeModal;
}

export class AnkiMathjaxElement extends HTMLElement {
    private isRendered = false;

    static get observedAttributes() {
        return ["block", "data-mathjax"];
    }

    connectedCallback() {
        if (!this.isRendered) {
            this.render();
            this.isRendered = true;
        }
        this.addEventListener("click", this.onClick);
    }

    disconnectedCallback() {
        this.removeEventListener("click", this.onClick);
    }

    attributeChangedCallback() {
        if (this.isRendered) {
            this.render();
        }
    }

    private onClick = (e: MouseEvent) => {
        e.stopPropagation();
        openMathjaxEditor(this);
    };

    public getMathContent(): string {
        return this.getAttribute("data-mathjax") || this.textContent || "";
    }

    public setMathContent(content: string) {
        this.setAttribute("data-mathjax", content);
        this.render();
    }

    public isBlock(): boolean {
        const b = this.getAttribute("block");
        return b === "true" || b === "";
    }

    public setBlock(block: boolean) {
        this.setAttribute("block", block ? "true" : "false");
        this.render();
    }

    public render() {
        const tex = this.getMathContent().trim();
        const block = this.isBlock();
        const res = renderMathjaxSvg(tex, block);

        this.style.display = block ? "block" : "inline-block";
        this.style.cursor = "pointer";
        this.style.userSelect = "none";
        this.title = "Click to edit MathJax equation";
        this.classList.toggle("anki-mathjax-block", block);

        this.innerHTML = res.svgHtml;
    }
}

if (typeof customElements !== "undefined" && !customElements.get("anki-mathjax")) {
    customElements.define("anki-mathjax", AnkiMathjaxElement);
}

export function openMathjaxEditor(
    targetEl?: AnkiMathjaxElement,
    insertionContext?: { hostEl: HTMLElement; defaultBlock?: boolean }
) {
    const modal = ensureMathjaxModal();
    const input = modal.querySelector<HTMLTextAreaElement>(".mj-input")!;
    const blockSwitch = modal.querySelector<HTMLInputElement>(".mj-block-switch")!;
    const preview = modal.querySelector<HTMLElement>(".mj-preview-content")!;
    const deleteBtn = modal.querySelector<HTMLElement>(".mj-delete-btn")!;

    const isEdit = !!targetEl;
    deleteBtn.style.display = isEdit ? "" : "none";

    // Focusing the modal moves the selection out of the field; remember where to insert.
    const hostSelection = insertionContext && insertionContext.hostEl.contains(window.getSelection()?.anchorNode ?? null)
        ? saveSelection(insertionContext.hostEl)
        : null;

    let initialTex = "";
    let isBlock = false;

    if (targetEl) {
        initialTex = targetEl.getMathContent();
        isBlock = targetEl.isBlock();
    } else if (insertionContext) {
        isBlock = !!insertionContext.defaultBlock;
    }

    input.value = initialTex;
    blockSwitch.checked = isBlock;

    const updatePreview = () => {
        const tex = input.value.trim();
        const blk = blockSwitch.checked;
        const res = renderMathjaxSvg(tex, blk);
        preview.innerHTML = res.svgHtml;
    };

    updatePreview();

    modal.showModal();
    input.focus();
    input.setSelectionRange(input.value.length, input.value.length);

    input.oninput = updatePreview;
    blockSwitch.onchange = updatePreview;

    modal.onclose = () => {
        input.oninput = null;
        blockSwitch.onchange = null;
    };

    const closeModal = () => {
        modal.close();
    };

    const saveAndClose = () => {
        const tex = input.value.trim();
        const blk = blockSwitch.checked;
        if (targetEl) {
            targetEl.setMathContent(tex);
            targetEl.setBlock(blk);
            targetEl.dispatchEvent(new Event("input", { bubbles: true }));
        } else if (insertionContext) {
            const host = insertionContext.hostEl;
            const el = document.createElement("anki-mathjax") as AnkiMathjaxElement;
            el.setAttribute("data-mathjax", tex);
            el.setAttribute("block", blk ? "true" : "false");
            host.focus();
            if (hostSelection) restoreSelection(host, hostSelection);
            else setCaretToEnd(host);
            document.execCommand("insertHTML", false, el.outerHTML);
            host.dispatchEvent(new Event("input", { bubbles: true }));
        }
        closeModal();
    };

    const closeBtns = modal.querySelectorAll(".mj-close-btn");
    closeBtns.forEach(btn => {
        (btn as HTMLElement).onclick = closeModal;
    });

    const saveBtn = modal.querySelector<HTMLElement>(".mj-save-btn")!;
    saveBtn.onclick = saveAndClose;

    deleteBtn.onclick = () => {
        if (targetEl) {
            const parent = targetEl.parentNode;
            targetEl.remove();
            if (parent) {
                parent.dispatchEvent(new Event("input", { bubbles: true }));
            }
        }
        closeModal();
    };

    input.onkeydown = (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            saveAndClose();
        } else if (e.key === "Escape") {
            e.preventDefault();
            closeModal();
        }
    };
}
