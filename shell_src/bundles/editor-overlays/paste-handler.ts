/**
 * Paste and drop handler for editor inputs.
 * Ports ts/routes/editor/paste-handler and image upload.
 */
import { filterHTML, FilterMode } from "./html-filter";

export interface PasteOptions {
    uploadUrl?: string;
    stripFormatting?: boolean;
}

export async function uploadMediaFile(file: File, uploadUrl = "/upload_media"): Promise<string> {
    const fd = new FormData();
    fd.append("file", file, file.name || "pasted_image.png");
    const resp = await fetch(uploadUrl, {
        method: "POST",
        body: fd,
    });
    if (!resp.ok) {
        throw new Error(`Upload failed with status ${resp.status}`);
    }
    const data = await resp.json() as { filename: string };
    return data.filename;
}

export function setupPasteAndDrop(root: HTMLElement, options: PasteOptions = {}) {
    const uploadUrl = options.uploadUrl || "/upload_media";

    // Handle paste
    root.addEventListener("paste", async (e: ClipboardEvent) => {
        const cd = e.clipboardData;
        if (!cd) return;

        // Check for file items (images/audio)
        let imageFile: File | null = null;
        if (cd.files && cd.files.length > 0) {
            for (let i = 0; i < cd.files.length; i++) {
                const f = cd.files[i];
                if (f.type.startsWith("image/")) {
                    imageFile = f;
                    break;
                }
            }
        } else if (cd.items && cd.items.length > 0) {
            for (let i = 0; i < cd.items.length; i++) {
                const item = cd.items[i];
                if (item.kind === "file" && item.type.startsWith("image/")) {
                    imageFile = item.getAsFile();
                    break;
                }
            }
        }

        if (imageFile) {
            e.preventDefault();
            e.stopImmediatePropagation();
            try {
                const filename = await uploadMediaFile(imageFile, uploadUrl);
                const imgTag = `<img src="${filename}" alt="">`;
                document.execCommand("insertHTML", false, imgTag);
            } catch (err) {
                console.error("Failed to upload pasted image:", err);
            }
            return;
        }

        // Check HTML content
        const rawHtml = cd.getData("text/html");
        const plainText = cd.getData("text/plain");

        if (rawHtml) {
            e.preventDefault();
            e.stopImmediatePropagation();
            // Determine filter mode: if Shift is held or option is set, basic; else extended
            const mode = options.stripFormatting ? FilterMode.Basic : FilterMode.Extended;
            const cleaned = filterHTML(rawHtml, mode);
            if (cleaned) {
                document.execCommand("insertHTML", false, cleaned);
            }
            return;
        }

        if (plainText) {
            e.preventDefault();
            e.stopImmediatePropagation();
            // Escape plain text and convert newlines to <br>
            const escaped = plainText
                .replace(/&/g, "&amp;")
                .replace(/</g, "&lt;")
                .replace(/>/g, "&gt;")
                .replace(/\n/g, "<br>");
            document.execCommand("insertHTML", false, escaped);
        }
    }, true);

    // Handle drag and drop files
    root.addEventListener("dragover", (e: DragEvent) => {
        if (e.dataTransfer && e.dataTransfer.types.includes("Files")) {
            e.preventDefault();
            e.dataTransfer.dropEffect = "copy";
        }
    });

    root.addEventListener("drop", async (e: DragEvent) => {
        const dt = e.dataTransfer;
        if (!dt || !dt.files || dt.files.length === 0) return;

        let hasImage = false;
        for (let i = 0; i < dt.files.length; i++) {
            if (dt.files[i].type.startsWith("image/")) {
                hasImage = true;
                break;
            }
        }

        if (hasImage) {
            e.preventDefault();
            e.stopImmediatePropagation();
            for (let i = 0; i < dt.files.length; i++) {
                const file = dt.files[i];
                if (file.type.startsWith("image/")) {
                    try {
                        const fname = await uploadMediaFile(file, uploadUrl);
                        const imgTag = `<img src="${fname}" alt="">`;
                        document.execCommand("insertHTML", false, imgTag);
                    } catch (err) {
                        console.error("Failed to upload dropped file:", err);
                    }
                }
            }
        }
    }, true);
}
