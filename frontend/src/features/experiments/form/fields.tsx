/** Field wrappers that wire Mantine inputs to config values and server-side issues. */
import { NumberInput, type NumberInputProps } from "@mantine/core";

import { useIssue } from "./issues";

interface NumberFieldProps extends Omit<NumberInputProps, "value" | "onChange" | "error"> {
  path: string;
  value: number;
  onChange: (value: number) => void;
}

/** Numeric input that only reports finite numbers and shows the issue for ``path``. */
export function NumberField({ path, value, onChange, ...props }: NumberFieldProps) {
  const error = useIssue(path);
  return (
    <NumberInput
      {...props}
      value={value}
      error={error}
      onChange={(next) => {
        const parsed = typeof next === "number" ? next : Number.parseFloat(next);
        if (Number.isFinite(parsed)) onChange(parsed);
      }}
    />
  );
}
