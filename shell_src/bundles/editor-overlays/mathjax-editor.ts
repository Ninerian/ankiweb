/**
 * Custom element <anki-mathjax> and MathJax edit modal / popover.
 */
import { renderMathjaxSvg, toStoredMathjax } from "./mathjax";
import { saveSelection, restoreSelection } from "../editor/selection";
import { setCaretToEnd } from "../editor/dom";

let activeModal: HTMLElement | null = null;

function ensureMathjaxModal(): HTMLElement {
    if (!activeModal) {
        activeModal = document.createElement("div");
        activeModal.className = "ankiweb-mathjax-modal modal";
        activeModal.tabIndex = -1;
        activeModal.style.zIndex = "1055";
        activeModal.innerHTML = `
            <div class="modal-dialog modal-dialog-centered">
                <div class="modal-content">
                    <div class="modal-header py-2">
                        <h6 class="modal-title m-0">Edit MathJax Equation</h6>
                        <button type="button" class="btn-close btn-sm mj-close-btn" aria-label="Close"></button>
                    </div>
                    <div class="modal-body py-2">
                        <div class="mb-2">
                            <label class="form-label small fw-bold">Formula (TeX / LaTeX):</label>
                            <textarea class="form-control font-monospace mj-input" rows="3" placeholder="e.g. \\frac{a}{b} or \\sqrt{x}"></textarea>
                        </div>
                        <div class="form-check form-switch mb-2">
                            <input class="form-check-input mj-block-switch" type="checkbox" id="mj-block-toggle">
                            <label class="form-check-label small" for="mj-block-toggle">Display as Block equation (\\[ ... \\])</label>
                        </div>
                        <div class="border rounded p-2 bg-light mj-preview-box" style="min-height: 48px; display: flex; align-items: center; justify-content: center;">
                            <div class="mj-preview-content"></div>
                        </div>
                    </div>
                    <div class="modal-footer py-2">
                        <button type="button" class="btn btn-sm btn-outline-danger me-auto mj-delete-btn">Delete</button>
                        <button type="button" class="btn btn-sm btn-secondary mj-close-btn">Cancel</button>
                        <button type="button" class="btn btn-sm btn-primary mj-save-btn">Save (Enter)</button>
                    </div>
                </div>
            </div>
            <div class="modal-backdrop fade show" style="position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; background: rgba(0,0,0,0.5); z-index: -1;"></div>
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

    modal.style.display = "block";
    input.focus();
    input.setSelectionRange(input.value.length, input.value.length);

    input.oninput = updatePreview;
    blockSwitch.onchange = updatePreview;

    const closeModal = () => {
        modal.style.display = "none";
        input.oninput = null;
        blockSwitch.onchange = null;
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
