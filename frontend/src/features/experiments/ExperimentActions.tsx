import { ActionIcon, Button, Group, Menu, Modal, Text } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { notifications } from "@mantine/notifications";
import { IconCopy, IconDots, IconPlayerStop, IconTrash } from "@tabler/icons-react";
import { useNavigate } from "react-router";

import { useCancelExperiment, useDeleteExperiment } from "../../api/queries";
import { isActive, type RunStatus } from "../../api/types";

interface ExperimentActionsProps {
  id: string;
  name: string;
  status: RunStatus;
  /** Where to go after deleting (stay on the list by default). */
  afterDelete?: string;
}

/** Duplicate / cancel / delete menu shared by the list and the detail page. */
export function ExperimentActions({ id, name, status, afterDelete }: ExperimentActionsProps) {
  const navigate = useNavigate();
  const cancel = useCancelExperiment();
  const remove = useDeleteExperiment();
  const [confirming, { open, close }] = useDisclosure(false);
  const active = isActive(status);

  const onError = (title: string) => (error: Error) =>
    notifications.show({ color: "red", title, message: error.message });

  const confirmDelete = () =>
    remove.mutate(id, {
      onSuccess: () => {
        close();
        notifications.show({ message: `Deleted “${name}”` });
        if (afterDelete) void navigate(afterDelete);
      },
      onError: onError("Could not delete the experiment"),
    });

  return (
    <>
      <Menu position="bottom-end" withinPortal>
        <Menu.Target>
          <ActionIcon variant="subtle" color="gray" aria-label={`Actions for ${name}`}>
            <IconDots size={18} />
          </ActionIcon>
        </Menu.Target>
        <Menu.Dropdown>
          <Menu.Item
            leftSection={<IconCopy size={14} />}
            onClick={() => void navigate(`/experiments/new?from=${id}`)}
          >
            Duplicate and edit
          </Menu.Item>
          <Menu.Item
            leftSection={<IconPlayerStop size={14} />}
            disabled={!active}
            onClick={() =>
              cancel.mutate(id, { onError: onError("Could not cancel the experiment") })
            }
          >
            Cancel runs
          </Menu.Item>
          <Menu.Divider />
          <Menu.Item
            color="red"
            leftSection={<IconTrash size={14} />}
            disabled={active}
            onClick={open}
          >
            Delete
          </Menu.Item>
        </Menu.Dropdown>
      </Menu>
      <Modal opened={confirming} onClose={close} title="Delete experiment" centered>
        <Text size="sm">
          “{name}” and all of its stored generations and metrics will be permanently deleted.
        </Text>
        <Group justify="flex-end" mt="lg">
          <Button variant="default" onClick={close}>
            Keep it
          </Button>
          <Button color="red" loading={remove.isPending} onClick={confirmDelete}>
            Delete
          </Button>
        </Group>
      </Modal>
    </>
  );
}
