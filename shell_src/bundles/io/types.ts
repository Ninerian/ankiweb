export interface Point {
    x: number;
    y: number;
}

export interface Size {
    width: number;
    height: number;
}

export type ShapeType = "rect" | "ellipse" | "polygon" | "text";

export interface ShapeBase {
    id: string;
    type: ShapeType;
    left: number;       // normalized (0-1)
    top: number;        // normalized (0-1)
    angle: number;      // degrees (0-360)
    fill: string;       // hex or color string
    ordinal?: number;   // cloze ordinal (1, 2, 3...)
    groupId?: string;   // if grouped with other shapes
}

export interface RectShape extends ShapeBase {
    type: "rect";
    width: number;      // normalized (0-1)
    height: number;     // normalized (0-1)
}

export interface EllipseShape extends ShapeBase {
    type: "ellipse";
    rx: number;         // normalized radius x (0-1)
    ry: number;         // normalized radius y (0-1)
}

export interface PolygonShape extends ShapeBase {
    type: "polygon";
    points: Point[];    // normalized points (0-1)
}

export interface TextShape extends ShapeBase {
    type: "text";
    text: string;
    scale: number;      // scale factor
    fontSize?: number;  // normalized or pt
}

export type Shape = RectShape | EllipseShape | PolygonShape | TextShape;

export type ToolType = "cursor" | "rect" | "ellipse" | "polygon" | "text" | "fill";
