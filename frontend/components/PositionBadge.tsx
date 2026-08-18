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
      className={`inline-flex items-center justify-center rounded-none font-black leading-none align-middle select-none border-t border-l border-t-white/80 border-l-white/80 border-b border-r border-b-black border-r-black ${
        size === "xs"
          ? "text-[9px] px-1 py-[1.5px]"
          : "text-[11px] px-1.5 py-0.5"
      }`}
      style={{
        backgroundColor: positionColor(position),
        color: "#000000",
        textShadow: "0 0 1px rgba(255,255,255,0.4)",
      }}
    >
      {position}
    </span>
  );
}
