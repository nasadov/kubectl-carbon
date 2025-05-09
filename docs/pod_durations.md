# Pod Duration Handling in the KWOK Simulation

Copyright 2025 Technische Universitaet Berlin.

This document explains how pod durations are handled in the KWOK simulation environment, and how the timing is affected by the shrink factor.

## Understanding Timing in the KWOK Simulation

The benchmark system operates with two time domains:

1. **Real Time**: Actual wall clock time that passes during the benchmark.
2. **Simulation Time**: Accelerated time within the simulation (real time × shrink factor).

By default, the system uses a shrink factor of 60, which means 60 simulation seconds pass for every 1 real second. This allows for faster experiments.

## How Pod Durations Work

Pod durations are defined by "Stage" objects in the KWOK configuration file (`k8s/kwok-config.yaml`). These stages look for pods with specific duration labels and delete them after the specified time:

- `duration-1h`: Pods intended to run for 1 simulation hour
- `duration-2h`: Pods intended to run for 2 simulation hours
- And so on...

For example, with the default shrink factor of 60:
- A `duration-1h` pod runs for 60,000ms = 1 real minute (representing 1 simulation hour)
- A `duration-2h` pod runs for 120,000ms = 2 real minutes (representing 2 simulation hours)

## KWOK Timing Configuration

Several timing values in the KWOK configuration need to be adjusted when the shrink factor changes:

1. **Pod durations** (12 different stages from 1h to 12h)
2. **Node heartbeat intervals** (controls how often nodes report their status)
3. **Pod deletion delays** (controls how quickly pods are deleted when terminated)
4. **Node lease durations** (controls how long node leases are valid)

## Important Consideration

**Changes to KWOK timing settings only take effect when the KWOK cluster is recreated.** Simply updating the configuration file is not enough.

## Adjusting Timing with Different Shrink Factors

When changing the shrink factor, you must update all timing-related values to maintain consistent simulation behavior. Two scripts are provided for this:

### 1. Update KWOK Durations Script (`update_kwok_durations.sh`)

This script updates the KWOK configuration file with appropriate timing values based on the shrink factor:

```bash
./scripts/update_kwok_durations.sh --shrink-factor 120
```

Options:
- `-s, --shrink-factor VALUE`: Shrink factor to use (default: 60)
- `-f, --file PATH`: Path to KWOK config file
- `-b, --backup`: Create a backup of the original file

### 2. Apply KWOK Settings Script (`apply_kwok_settings.sh`)

This script combines updating the configuration and restarting the KWOK cluster:

```bash
./scripts/apply_kwok_settings.sh --shrink-factor 120
```

Options:
- `-s, --shrink-factor VALUE`: Shrink factor to use (default: 60)
- `-n, --no-restart`: Update configuration only, don't restart KWOK

### 3. Automatic Integration with `run_benchmark.sh`

The `run_benchmark.sh` script now automatically detects when a non-default shrink factor is used and prompts to update the KWOK timing settings accordingly.

## Formula for Duration Calculation

The formula to calculate the correct duration values in milliseconds is:

```
duration_ms = (time_in_simulation_units × 1000) / shrink_factor
```

For example:
- 1 simulation hour with shrink factor 60 = 3600 × 1000 / 60 = 60,000ms
- 1 simulation hour with shrink factor 120 = 3600 × 1000 / 120 = 30,000ms

## Common Issues and Troubleshooting

1. **Pod durations seem incorrect**: Make sure you've recreated the KWOK cluster after changing the configuration.
2. **No changes after updating config**: KWOK requires a full restart to apply configuration changes.
3. **Pods running too long/short**: Verify that the correct shrink factor was used in both the KWOK configuration and the benchmark command.
