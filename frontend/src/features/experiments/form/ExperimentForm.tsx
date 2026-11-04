import {
  Card,
  Checkbox,
  Group,
  SegmentedControl,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import type { ReactNode } from "react";

import type {
  AlgorithmName,
  Catalog,
  ExperimentConfig,
  NSGA3Config,
  PMConfig,
  ProblemConfig,
  ProblemName,
  SBXConfig,
} from "../../../api/types";
import {
  ALGORITHM_LABELS,
  PROBLEM_DESCRIPTIONS,
  PROBLEM_LABELS,
  switchAlgorithm,
  switchProblem,
} from "../../../lib/configModel";
import { NumberField } from "./fields";
import { useIssue } from "./issues";

interface FormProps {
  config: ExperimentConfig;
  catalog: Catalog;
  onChange: (config: ExperimentConfig) => void;
}

function Section({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: ReactNode;
}) {
  return (
    <Card withBorder padding="lg">
      <Title order={4}>{title}</Title>
      {description && (
        <Text size="sm" c="dimmed" mb="md">
          {description}
        </Text>
      )}
      <Stack gap="md" mt={description ? 0 : "md"}>
        {children}
      </Stack>
    </Card>
  );
}

function GeneralSection({ config, onChange }: Omit<FormProps, "catalog">) {
  const nameError = useIssue("name");
  return (
    <Section title="General">
      <TextInput
        label="Name"
        required
        value={config.name}
        error={nameError}
        maxLength={120}
        onChange={(event) => onChange({ ...config, name: event.currentTarget.value })}
      />
      <SimpleGrid cols={{ base: 1, sm: 3 }}>
        <NumberField
          path="n_gen"
          label="Generations"
          min={1}
          max={100_000}
          value={config.n_gen}
          onChange={(n_gen) => onChange({ ...config, n_gen })}
        />
        <NumberField
          path="n_runs"
          label="Independent runs"
          description="One seed per run"
          min={1}
          max={100}
          value={config.n_runs}
          onChange={(n_runs) => onChange({ ...config, n_runs })}
        />
        <NumberField
          path="seed"
          label="Base seed"
          min={0}
          max={4_294_967_295}
          allowDecimal={false}
          value={config.seed}
          onChange={(seed) => onChange({ ...config, seed })}
        />
      </SimpleGrid>
    </Section>
  );
}

function ProblemSection({ config, catalog, onChange }: FormProps) {
  const problem = config.problem;
  const update = (next: ProblemConfig) => onChange({ ...config, problem: next });
  return (
    <Section title="Problem" description="Box-constrained multi-objective minimisation benchmark.">
      <Select
        label="Benchmark"
        description={PROBLEM_DESCRIPTIONS[problem.name]}
        data={catalog.problems.map((p) => ({
          value: p.name,
          label: PROBLEM_LABELS[p.name] ?? p.name,
        }))}
        value={problem.name}
        allowDeselect={false}
        onChange={(name) => name && onChange(switchProblem(config, catalog, name as ProblemName))}
      />
      {problem.name === "dtlz2" ? (
        <SimpleGrid cols={{ base: 1, sm: 2 }}>
          <NumberField
            path="problem.n_obj"
            label="Objectives (M)"
            min={2}
            max={15}
            allowDecimal={false}
            value={problem.n_obj}
            onChange={(n_obj) => update({ ...problem, n_obj })}
          />
          <NumberField
            path="problem.k"
            label="Distance variables (k)"
            description={`n_var = M + k − 1 = ${problem.n_obj + problem.k - 1}`}
            min={1}
            max={100}
            allowDecimal={false}
            value={problem.k}
            onChange={(k) => update({ ...problem, k })}
          />
        </SimpleGrid>
      ) : (
        <SimpleGrid cols={{ base: 1, sm: 2 }}>
          <NumberField
            path="problem.n_var"
            label="Decision variables (n)"
            description="Objectives: M = 2"
            min={2}
            max={1000}
            allowDecimal={false}
            value={problem.n_var}
            onChange={(n_var) => update({ ...problem, n_var })}
          />
        </SimpleGrid>
      )}
    </Section>
  );
}

function AlgorithmSection({ config, catalog, onChange }: FormProps) {
  const algorithm = config.algorithm;
  return (
    <Section title="Algorithm">
      <SegmentedControl
        fullWidth
        value={algorithm.name}
        data={catalog.algorithms.map((a) => ({ value: a.name, label: ALGORITHM_LABELS[a.name] }))}
        onChange={(name) => onChange(switchAlgorithm(config, catalog, name as AlgorithmName))}
      />
      {algorithm.name === "nsga2" ? (
        <NumberField
          path="algorithm.pop_size"
          label="Population size"
          min={4}
          max={10_000}
          allowDecimal={false}
          value={algorithm.pop_size}
          onChange={(pop_size) => onChange({ ...config, algorithm: { ...algorithm, pop_size } })}
        />
      ) : (
        <NSGA3Fields
          algorithm={algorithm}
          onChange={(next) => onChange({ ...config, algorithm: next })}
        />
      )}
    </Section>
  );
}

function NSGA3Fields({
  algorithm,
  onChange,
}: {
  algorithm: NSGA3Config;
  onChange: (a: NSGA3Config) => void;
}) {
  const automatic = algorithm.pop_size === null || algorithm.pop_size === undefined;
  return (
    <SimpleGrid cols={{ base: 1, sm: 2 }}>
      <NumberField
        path="algorithm.n_partitions"
        label="Reference-point partitions (p)"
        description="Das–Dennis divisions of the unit simplex"
        min={1}
        max={200}
        allowDecimal={false}
        value={algorithm.n_partitions}
        onChange={(n_partitions) => onChange({ ...algorithm, n_partitions })}
      />
      <Stack gap={6}>
        <Switch
          label="Automatic population size"
          description="Smallest multiple of 4 ≥ number of directions"
          checked={automatic}
          onChange={(event) =>
            onChange({ ...algorithm, pop_size: event.currentTarget.checked ? null : 92 })
          }
        />
        {!automatic && (
          <NumberField
            path="algorithm.pop_size"
            aria-label="Population size"
            min={4}
            max={10_000}
            allowDecimal={false}
            value={algorithm.pop_size ?? 92}
            onChange={(pop_size) => onChange({ ...algorithm, pop_size })}
          />
        )}
      </Stack>
    </SimpleGrid>
  );
}

function VariationSection({ config, onChange }: Omit<FormProps, "catalog">) {
  const algorithm = config.algorithm;
  const sbx = (patch: Partial<SBXConfig>) =>
    onChange({
      ...config,
      algorithm: { ...algorithm, crossover: { ...algorithm.crossover, ...patch } },
    });
  const pm = (patch: Partial<PMConfig>) =>
    onChange({
      ...config,
      algorithm: { ...algorithm, mutation: { ...algorithm.mutation, ...patch } },
    });
  const defaultRate =
    algorithm.mutation.prob_var === null || algorithm.mutation.prob_var === undefined;
  return (
    <Section
      title="Variation operators"
      description="Simulated binary crossover and polynomial mutation."
    >
      <Text size="sm" fw={600}>
        SBX crossover
      </Text>
      <SimpleGrid cols={{ base: 1, sm: 3 }}>
        <NumberField
          path="algorithm.crossover.eta"
          label="Distribution index η"
          min={0.01}
          step={1}
          value={algorithm.crossover.eta}
          onChange={(eta) => sbx({ eta })}
        />
        <NumberField
          path="algorithm.crossover.prob"
          label="Probability per mating"
          min={0}
          max={1}
          step={0.05}
          decimalScale={4}
          value={algorithm.crossover.prob}
          onChange={(prob) => sbx({ prob })}
        />
        <NumberField
          path="algorithm.crossover.prob_var"
          label="Probability per variable"
          min={0}
          max={1}
          step={0.05}
          decimalScale={4}
          value={algorithm.crossover.prob_var}
          onChange={(prob_var) => sbx({ prob_var })}
        />
      </SimpleGrid>
      <Text size="sm" fw={600}>
        Polynomial mutation
      </Text>
      <SimpleGrid cols={{ base: 1, sm: 3 }}>
        <NumberField
          path="algorithm.mutation.eta"
          label="Distribution index η"
          min={0.01}
          step={1}
          value={algorithm.mutation.eta}
          onChange={(eta) => pm({ eta })}
        />
        <Switch
          mt={28}
          label="Rate 1 / n_var"
          checked={defaultRate}
          onChange={(event) => pm({ prob_var: event.currentTarget.checked ? null : 0.1 })}
        />
        {!defaultRate && (
          <NumberField
            path="algorithm.mutation.prob_var"
            label="Probability per variable"
            min={0}
            max={1}
            step={0.01}
            decimalScale={4}
            value={algorithm.mutation.prob_var ?? 0.1}
            onChange={(prob_var) => pm({ prob_var })}
          />
        )}
      </SimpleGrid>
    </Section>
  );
}

function ObservationSection({ config, onChange }: Omit<FormProps, "catalog">) {
  const metrics = config.metrics;
  const snapshots = config.snapshots;
  const setMetrics = (patch: Partial<typeof metrics>) =>
    onChange({ ...config, metrics: { ...metrics, ...patch } });
  const setSnapshots = (patch: Partial<typeof snapshots>) =>
    onChange({ ...config, snapshots: { ...snapshots, ...patch } });
  return (
    <Section
      title="Observation"
      description="What is measured and stored. Snapshots keep parents, offspring, lineage and survival of each stored generation."
    >
      <Group gap="lg">
        <Checkbox
          label="IGD"
          checked={metrics.igd}
          onChange={(e) => setMetrics({ igd: e.currentTarget.checked })}
        />
        <Checkbox
          label="IGD+"
          checked={metrics.igd_plus}
          onChange={(e) => setMetrics({ igd_plus: e.currentTarget.checked })}
        />
        <Checkbox
          label="GD"
          checked={metrics.gd}
          onChange={(e) => setMetrics({ gd: e.currentTarget.checked })}
        />
        <Checkbox
          label="Hypervolume"
          checked={metrics.hv}
          onChange={(e) => setMetrics({ hv: e.currentTarget.checked })}
        />
        <Checkbox
          label="Offspring hypervolume"
          checked={metrics.hv_offspring}
          onChange={(e) => setMetrics({ hv_offspring: e.currentTarget.checked })}
        />
      </Group>
      <SimpleGrid cols={{ base: 1, sm: 2 }}>
        <NumberField
          path="metrics.every"
          label="Indicators every N generations"
          min={1}
          allowDecimal={false}
          value={metrics.every}
          onChange={(every) => setMetrics({ every })}
        />
        <NumberField
          path="metrics.reference_front_size"
          label="Reference front points"
          min={10}
          max={100_000}
          allowDecimal={false}
          value={metrics.reference_front_size}
          onChange={(reference_front_size) => setMetrics({ reference_front_size })}
        />
      </SimpleGrid>
      <Switch
        label="Store generation snapshots"
        checked={snapshots.enabled}
        onChange={(e) => setSnapshots({ enabled: e.currentTarget.checked })}
      />
      {snapshots.enabled && (
        <SimpleGrid cols={{ base: 1, sm: 3 }}>
          <NumberField
            path="snapshots.every"
            label="Store every N generations"
            min={1}
            allowDecimal={false}
            value={snapshots.every}
            onChange={(every) => setSnapshots({ every })}
          />
          <Stack gap={4}>
            <Text size="sm" fw={500}>
              Precision
            </Text>
            <SegmentedControl
              value={snapshots.precision}
              data={["float64", "float32"]}
              onChange={(precision) =>
                setSnapshots({ precision: precision as typeof snapshots.precision })
              }
            />
          </Stack>
          <Switch
            mt={28}
            label="Decision variables (X)"
            checked={snapshots.decision_variables}
            onChange={(e) => setSnapshots({ decision_variables: e.currentTarget.checked })}
          />
        </SimpleGrid>
      )}
    </Section>
  );
}

export function ExperimentForm(props: FormProps) {
  return (
    <Stack gap="md">
      <GeneralSection config={props.config} onChange={props.onChange} />
      <ProblemSection {...props} />
      <AlgorithmSection {...props} />
      <VariationSection config={props.config} onChange={props.onChange} />
      <ObservationSection config={props.config} onChange={props.onChange} />
    </Stack>
  );
}
