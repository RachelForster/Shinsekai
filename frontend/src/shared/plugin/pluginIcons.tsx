import {
  BookOpen,
  Bot,
  Brush,
  Database,
  File,
  Gamepad2,
  Globe,
  Image,
  Info,
  Layers,
  Play,
  Puzzle,
  Settings,
  Sliders,
  Smartphone,
  Sparkles,
  Terminal,
  Wand2,
  Wrench,
} from "lucide-react";
import type { ReactNode } from "react";

import type { PluginSlotContributionIcon } from "../platform/types";

export function renderPluginIcon(
  icon: PluginSlotContributionIcon | string | null | undefined,
  className = "button__icon",
): ReactNode {
  switch (icon) {
    case "book":
      return <BookOpen aria-hidden className={className} />;
    case "bot":
      return <Bot aria-hidden className={className} />;
    case "brush":
      return <Brush aria-hidden className={className} />;
    case "database":
      return <Database aria-hidden className={className} />;
    case "file":
      return <File aria-hidden className={className} />;
    case "gamepad":
      return <Gamepad2 aria-hidden className={className} />;
    case "globe":
      return <Globe aria-hidden className={className} />;
    case "image":
      return <Image aria-hidden className={className} />;
    case "info":
      return <Info aria-hidden className={className} />;
    case "layers":
      return <Layers aria-hidden className={className} />;
    case "play":
      return <Play aria-hidden className={className} />;
    case "settings":
      return <Settings aria-hidden className={className} />;
    case "sliders":
      return <Sliders aria-hidden className={className} />;
    case "smartphone":
      return <Smartphone aria-hidden className={className} />;
    case "sparkles":
      return <Sparkles aria-hidden className={className} />;
    case "terminal":
      return <Terminal aria-hidden className={className} />;
    case "wand":
      return <Wand2 aria-hidden className={className} />;
    case "wrench":
      return <Wrench aria-hidden className={className} />;
    case "puzzle":
    default:
      return <Puzzle aria-hidden className={className} />;
  }
}
