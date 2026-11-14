import type { Point } from "./graphLayout";
export interface GraphDragModel {
  key: string;
  pointerId: number;
  start: Point;
  pixel: number[];
  moved: boolean;
}
export function beginGraphDrag(key: string, pointerId: number, start: Point, pixel: number[]): GraphDragModel {
  return { key, pointerId, start: { ...start }, pixel: [...pixel], moved: false };
}
export function advanceGraphDrag(
  model: GraphDragModel,
  pointerId: number,
  pixel: number[],
): { starting: boolean } | undefined {
  if (model.pointerId !== pointerId) return;
  if (!model.moved && Math.hypot(pixel[0] - model.pixel[0], pixel[1] - model.pixel[1]) < 4) return;
  const starting = !model.moved;
  model.moved = true;
  return { starting };
}
