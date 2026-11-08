import { Card, Group, Text, Title } from "@mantine/core";
import type { ReactNode } from "react";

/** A titled card of the analysis results, with its controls on the right. */
export function Section({
  title,
  description,
  controls,
  children,
}: {
  title: string;
  description: string;
  controls?: ReactNode;
  children: ReactNode;
}) {
  return (
    <Card withBorder padding="md">
      <Group justify="space-between" align="flex-start" mb="xs" wrap="wrap">
        <div>
          <Title order={5}>{title}</Title>
          <Text size="xs" c="dimmed" maw={620}>
            {description}
          </Text>
        </div>
        <Group gap="xs">{controls}</Group>
      </Group>
      {children}
    </Card>
  );
}
