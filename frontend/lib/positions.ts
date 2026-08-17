export const POSITION_COLORS: Record<string, string> = {
  QB: "#D57A66",
  RB: "#B5D6B2",
  WR: "#F8E16C",
  TE: "#759FBC",
  K: "#D57A66",
  DST: "#F0A868",
  DEF: "#F0A868",
};

export const DEFAULT_POSITION_COLOR = "#94a3b8";

export function positionColor(position: string): string {
  return (
    POSITION_COLORS[(position ?? "").trim().toUpperCase()] ??
    DEFAULT_POSITION_COLOR
  );
}
