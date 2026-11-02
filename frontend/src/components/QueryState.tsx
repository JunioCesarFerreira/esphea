import { Alert, Center, Loader } from "@mantine/core";
import { IconAlertTriangle } from "@tabler/icons-react";
import type { ReactNode } from "react";

interface QueryStateProps {
  isPending: boolean;
  error: Error | null;
  children: ReactNode;
}

/** Uniform loading and error states around query-backed content. */
export function QueryState({ isPending, error, children }: QueryStateProps) {
  if (error) {
    return (
      <Alert color="red" icon={<IconAlertTriangle size={16} />} title="Could not load data">
        {error.message}
      </Alert>
    );
  }
  if (isPending) {
    return (
      <Center py="xl">
        <Loader />
      </Center>
    );
  }
  return <>{children}</>;
}
