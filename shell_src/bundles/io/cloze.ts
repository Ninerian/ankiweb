import { Point, Shape, RectShape, EllipseShape, PolygonShape, TextShape } from "./types";

export const SHAPE_MASK_COLOR = "#ffeba2";
export const BORDER_COLOR = "#212121";
export const TEXT_BACKGROUND_COLOR = "#ffffff";
export const TEXT_FONT_FAMILY = "Arial";
export const TEXT_PADDING = 5;
export const TEXT_FONT_SIZE = 40;
export const TEXT_COLOR = "#000000";

const ANGLE_STEPS = 10000;

export function floatToDisplay(num: number): string {
    if (Number.isNaN(num) || num === 0) {
        return ".0000";
    }
    return num.toFixed(4).replace(/^0+|0+$/g, "");
}

export function angleToStored(angle: number | undefined): number | null {
    if (angle === undefined || Number.isNaN(angle)) return null;
    const angleDeg = (Number(angle) % 360 + 360) % 360;
    const stored = Math.round((angleDeg / 360) * ANGLE_STEPS);
    return stored === 0 ? null : stored;
}

export function storedToAngle(x: any): number {
    const angleSteps = Number(x) % ANGLE_STEPS;
    return Number.isNaN(angleSteps) ? 0 : (angleSteps / ANGLE_STEPS) * 360;
}

export function shapesToCloze(shapes: Shape[], occludeInactive: boolean = true): string {
    if (!shapes || shapes.length === 0) {
        return "";
    }

    // Determine ordinals
    const ordinalList: number[] = [];
    for (const shape of shapes) {
        if (typeof shape.ordinal === "number" && shape.ordinal > 0) {
            ordinalList.push(shape.ordinal);
        }
    }

    const maxOrdinal = ordinalList.length > 0 ? Math.max(...ordinalList) : 0;
    const missingOrdinals: number[] = [];
    for (let i = 1; i <= maxOrdinal; i++) {
        if (!ordinalList.includes(i)) {
            missingOrdinals.push(i);
        }
    }

    let nextOrdinal = maxOrdinal + 1;

    // Group shapes by groupId or treat individually
    // Map of group / individual item -> ordinal
    const groupOrdinalMap = new Map<string, number>();

    const assignedShapes: { shape: Shape; ordinal: number }[] = [];

    for (const shape of shapes) {
        let ord = shape.ordinal;
        if (shape.type === "text") {
            ord = 0;
        } else if (shape.groupId && groupOrdinalMap.has(shape.groupId)) {
            ord = groupOrdinalMap.get(shape.groupId)!;
        } else if (ord === undefined || ord === 0) {
            if (missingOrdinals.length > 0) {
                ord = missingOrdinals.shift()!;
            } else {
                ord = nextOrdinal++;
            }
            if (shape.groupId) {
                groupOrdinalMap.set(shape.groupId, ord);
            }
        } else if (shape.groupId) {
            groupOrdinalMap.set(shape.groupId, ord);
        }
        shape.ordinal = ord;
        assignedShapes.push({ shape, ordinal: ord });
    }

    let clozes = "";

    function addKeyValue(key: string, value: string): string {
        const escaped = value.replace(/\\/g, "\\\\").replace(/:/g, "\\:");
        return `:${key}=${escaped}`;
    }

    for (const { shape, ordinal } of assignedShapes) {
        let props = "";
        props += addKeyValue("left", floatToDisplay(shape.left));
        props += addKeyValue("top", floatToDisplay(shape.top));

        const storedAngle = angleToStored(shape.angle);
        if (storedAngle !== null && storedAngle !== 0) {
            props += addKeyValue("angle", storedAngle.toString());
        }

        if (shape.type === "rect") {
            const r = shape as RectShape;
            props += addKeyValue("width", floatToDisplay(r.width));
            props += addKeyValue("height", floatToDisplay(r.height));
            if (r.fill && r.fill !== SHAPE_MASK_COLOR) {
                props += addKeyValue("fill", r.fill);
            }
        } else if (shape.type === "ellipse") {
            const el = shape as EllipseShape;
            props += addKeyValue("rx", floatToDisplay(el.rx));
            props += addKeyValue("ry", floatToDisplay(el.ry));
            if (el.fill && el.fill !== SHAPE_MASK_COLOR) {
                props += addKeyValue("fill", el.fill);
            }
        } else if (shape.type === "polygon") {
            const p = shape as PolygonShape;
            // Compute bounding box left/top if needed
            const xs = p.points.map(pt => pt.x);
            const ys = p.points.map(pt => pt.y);
            const minX = xs.length > 0 ? Math.min(...xs) : p.left;
            const minY = ys.length > 0 ? Math.min(...ys) : p.top;
            // upstream Polygon overrides left/top to bounding box min
            props = addKeyValue("left", floatToDisplay(minX)) + addKeyValue("top", floatToDisplay(minY));
            if (storedAngle !== null && storedAngle !== 0) {
                props += addKeyValue("angle", storedAngle.toString());
            }
            const pointsStr = p.points.map(pt => `${floatToDisplay(pt.x)},${floatToDisplay(pt.y)}`).join(" ");
            props += addKeyValue("points", pointsStr);
            if (p.fill && p.fill !== SHAPE_MASK_COLOR) {
                props += addKeyValue("fill", p.fill);
            }
        } else if (shape.type === "text") {
            const t = shape as TextShape;
            props += addKeyValue("text", t.text);
            const scaleVal = t.scale || 1;
            props += addKeyValue("scale", floatToDisplay(scaleVal));
            const fsVal = t.fontSize !== undefined ? t.fontSize : 40 / 600; // normalized default
            props += addKeyValue("fs", floatToDisplay(fsVal));
            if (t.fill && t.fill !== TEXT_COLOR) {
                props += addKeyValue("fill", t.fill);
            }
        }

        if (occludeInactive) {
            props += addKeyValue("oi", "1");
        }

        clozes += `{{c${ordinal}::image-occlusion:${shape.type}${props}}}<br>`;
    }

    return clozes;
}

export function clozeToShapes(clozeText: string): Shape[] {
    if (!clozeText) return [];

    const shapes: Shape[] = [];
    const clozeRegex = /\{\{c(\d+)::image-occlusion:([a-z]+)(.*?)\}\}/g;
    let match: RegExpExecArray | null;

    let idCounter = 1;
    // Map ordinal to groupId for grouped shapes
    const ordinalCount = new Map<number, number>();

    // Pass 1: count occurrences of each ordinal
    const rawMatches: { ordinal: number; type: string; propsStr: string }[] = [];
    while ((match = clozeRegex.exec(clozeText)) !== null) {
        const ordinal = parseInt(match[1], 10);
        const type = match[2];
        const propsStr = match[3];
        rawMatches.push({ ordinal, type, propsStr });
        if (ordinal > 0) {
            ordinalCount.set(ordinal, (ordinalCount.get(ordinal) || 0) + 1);
        }
    }

    for (const m of rawMatches) {
        const { ordinal, type, propsStr } = m;
        // Parse key-value properties
        // propsStr is like ":left=.1:top=.2:width=.3"
        // key=value, handling escaped colons "\:"
        const props: Record<string, string> = {};
        const parts = propsStr.split(/(?<!\\):/);
        for (const part of parts) {
            if (!part) continue;
            const eqIdx = part.indexOf("=");
            if (eqIdx !== -1) {
                const k = part.substring(0, eqIdx);
                const v = part.substring(eqIdx + 1).replace(/\\:/g, ":").replace(/\\\\/g, "\\");
                props[k] = v;
            }
        }

        const left = parseFloat(props["left"] || "0");
        const top = parseFloat(props["top"] || "0");
        const angle = storedToAngle(props["angle"]);
        const fill = props["fill"] || (type === "text" ? TEXT_COLOR : SHAPE_MASK_COLOR);
        const isGrouped = ordinal > 0 && (ordinalCount.get(ordinal) || 0) > 1;
        const groupId = isGrouped ? `group-${ordinal}` : undefined;
        const id = `${type}-${Date.now()}-${idCounter++}`;

        if (type === "rect") {
            shapes.push({
                id,
                type: "rect",
                left,
                top,
                angle,
                fill,
                ordinal,
                groupId,
                width: parseFloat(props["width"] || "0"),
                height: parseFloat(props["height"] || "0"),
            });
        } else if (type === "ellipse") {
            shapes.push({
                id,
                type: "ellipse",
                left,
                top,
                angle,
                fill,
                ordinal,
                groupId,
                rx: parseFloat(props["rx"] || "0"),
                ry: parseFloat(props["ry"] || "0"),
            });
        } else if (type === "polygon") {
            const rawPoints = props["points"] || "";
            const points: Point[] = [];
            if (rawPoints) {
                for (const pt of rawPoints.split(" ")) {
                    const [px, py] = pt.split(",");
                    if (px !== undefined && py !== undefined) {
                        points.push({ x: parseFloat(px), y: parseFloat(py) });
                    }
                }
            }
            shapes.push({
                id,
                type: "polygon",
                left,
                top,
                angle,
                fill,
                ordinal,
                groupId,
                points: points.length > 0 ? points : [{ x: 0, y: 0 }],
            });
        } else if (type === "text") {
            shapes.push({
                id,
                type: "text",
                left,
                top,
                angle,
                fill,
                ordinal: 0,
                text: props["text"] || "",
                scale: parseFloat(props["scale"] || "1"),
                fontSize: props["fs"] ? parseFloat(props["fs"]) : undefined,
            });
        }
    }

    return shapes;
}
