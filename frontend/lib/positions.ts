export const POSITION_COLORS: Record<string, string> = {
  QB: "#FF6B6B", // Vibrant Retro Red / Coral
  RB: "#48C774", // Vibrant Retro Grass Green
  WR: "#FFD700", // Vibrant Retro Gold / Yellow
  TE: "#4D96FF", // Vibrant Retro Dodger Blue
  K: "#D980FA",  // Vibrant Retro Lavender / Magenta
  DST: "#FF9F43", // Vibrant Retro Orange / Amber
  DEF: "#FF9F43", // Vibrant Retro Orange / Amber
};

export const DEFAULT_POSITION_COLOR = "#A0AEC0";

export function positionColor(position: string): string {
  return (
    POSITION_COLORS[(position ?? "").trim().toUpperCase()] ??
    DEFAULT_POSITION_COLOR
  );
}
