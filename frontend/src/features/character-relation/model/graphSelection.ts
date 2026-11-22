export interface GraphSelectionModel {
  selectedKey: string;
  hoveredKey: string;
}
export function createGraphSelection(): GraphSelectionModel {
  return { selectedKey: "", hoveredKey: "" };
}
export function selectGraphNode(model: GraphSelectionModel, key: string): void {
  model.selectedKey = key;
}
export function hoverGraphNode(model: GraphSelectionModel, key: string): void {
  model.hoveredKey = key;
}
export function clearGraphSelection(model: GraphSelectionModel): void {
  Object.assign(model, createGraphSelection());
}
export function activeGraphNode(model: GraphSelectionModel): string {
  return model.hoveredKey || model.selectedKey;
}
