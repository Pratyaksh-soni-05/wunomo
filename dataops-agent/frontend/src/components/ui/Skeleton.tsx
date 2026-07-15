import { CSSProperties } from "react";

interface SkeletonProps {
  width?: string | number;
  height?: string | number;
  className?: string;
  style?: CSSProperties;
}

export function Skeleton({ width = "100%", height = "16px", className = "", style }: SkeletonProps) {
  return <div className={["skeleton", className].filter(Boolean).join(" ")} style={{ width, height, ...style }} />;
}
