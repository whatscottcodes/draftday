import { positionColor } from "@/lib/positions";

export function PositionBadge({
  position,
  size = "sm",
}: {
  position: string;
  size?: "sm" | "xs";
}) {
  return (
    <span
      className={`inline-flex items-center justify-center rounded font-bold leading-none align-middle ${
        size === "xs"
          ? "text-[9px] px-1 py-[2px]"
          : "text-[11px] px-1.5 py-0.5"
      }`}
      style={{ backgroundColor: positionColor(position), color: "#0f172a" }}
    >
      {position}
    </span>
  );
}
