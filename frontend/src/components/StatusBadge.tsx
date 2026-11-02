import { Badge } from "@mantine/core";
import {
  IconAlertTriangle,
  IconCircleCheck,
  IconClock,
  IconLoader2,
  IconPlayerStop,
} from "@tabler/icons-react";
import type { ComponentType } from "react";

import type { RunStatus } from "../api/types";

const STYLE: Record<
  RunStatus,
  { color: string; label: string; Icon: ComponentType<{ size?: number }> }
> = {
  queued: { color: "gray", label: "Queued", Icon: IconClock },
  running: { color: "blue", label: "Running", Icon: IconLoader2 },
  completed: { color: "green", label: "Completed", Icon: IconCircleCheck },
  failed: { color: "red", label: "Failed", Icon: IconAlertTriangle },
  cancelled: { color: "yellow", label: "Cancelled", Icon: IconPlayerStop },
};

/** Status is always conveyed by icon + label, never by colour alone. */
export function StatusBadge({ status }: { status: RunStatus }) {
  const { color, label, Icon } = STYLE[status];
  return (
    <Badge color={color} variant="light" leftSection={<Icon size={12} />}>
      {label}
    </Badge>
  );
}
