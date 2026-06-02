---
name: deploy-workflow
description: "Deploy a data-processing workflow paradigm: generates DAG config, orchestration script, pipeline stubs, and infrastructure utilities"
argument-hint: "<name> [task1,task2,task3]"
disable-model-invocation: true
effort: high
---

# Deploy Workflow

Generate a complete data-processing workflow following the DAG orchestration paradigm:
YAML-configured task ordering, TaskExecutor lifecycle, `should_process_task()` idempotency,
and PipelineMonitor status tracking.

**Tasks are pure processors that receive orders.** Each task is a box with
named input and output connectors — it reads from the paths it is given,
processes the data, and writes to the paths it is given. The workflow owns
all file discovery, path construction, looping, and idempotency. A shared
`context` dict stores resolved output paths; downstream stages pull values
by key via a `pipeline_stages` list.

---

## Step 1: Parse Arguments

- `$0` = workflow name (snake_case, e.g. `spatial_analysis`)
- `$1` = optional comma-separated task names (e.g. `extract,transform,export`)

If `$0` is missing or empty, ask the user for a workflow name.
If `$1` is missing, use two default tasks: `task_one` and `task_two`.

Derive these variables:
- `WORKFLOW_NAME` = `$0`
- `TASK_NAMES` = split `$1` by comma, or `[task_one, task_two]`
- `SCRIPT_FILE` = `{WORKFLOW_NAME}_workflow.py`
- `DAG_FILE` = `{WORKFLOW_NAME}_workflow_dag.yaml`

---

## Step 2: Discover Project Structure

Scan the repository to find or propose directories. Use `Glob` and `ls` to detect:

1. **Configs dir** — look for `configs/`, `config/`, or project root
2. **Scripts dir** — look for `scripts/`, `code/scripts/`, `src/scripts/`, or project root
3. **Source dir** — look for `src/`, `code/src/`, `lib/`, or project root
4. **Utils dir** — look for `utils/`, `src/utils/`, `code/src/utils/`, or `{source_dir}/utils/`
5. **Knowledge-base dir** — look for `docs/development/knowledge-base/`, `docs/knowledge-base/`, `docs/development/`, `docs/`, or project root

If multiple candidates exist or none are found, ask the user with `AskUserQuestion`.

Set these path variables:
- `CONFIGS_DIR` = resolved configs directory
- `SCRIPTS_DIR` = resolved scripts directory
- `SRC_DIR` = resolved source directory
- `UTILS_DIR` = resolved utils directory
- `MODULE_DIR` = `{SCRIPTS_DIR}/{WORKFLOW_NAME}/` (task scripts sit next to the workflow script)
- `SRC_PKG_DIR` = `{SRC_DIR}/{WORKFLOW_NAME}/` (shared package for types, classes, and utilities)
- `KB_DIR` = resolved knowledge-base directory

Also compute:
- `UTILS_IMPORT` — the Python import path to the utils directory
  (e.g. `utils` or `src.utils` depending on project structure)
- `SRC_PKG_IMPORT` — the Python import path to the shared package
  (e.g. `src.analysis` or `code.src.analysis` depending on project structure)

---

## Step 3: Pre-flight Checks

Before generating anything:

1. Verify `{SCRIPTS_DIR}/{SCRIPT_FILE}` does NOT already exist
2. Verify `{CONFIGS_DIR}/{DAG_FILE}` does NOT already exist
3. Verify `{MODULE_DIR}/` does NOT already exist
4. Verify `{SRC_PKG_DIR}/` does NOT already exist
5. Check whether `{KB_DIR}/how-to-add-workflow-task.md` already exists (if so, skip how-to generation later)

If items 1–4 exist, warn the user and ask whether to overwrite or abort.

---

## Step 4: Search for Existing Infrastructure

Search the codebase for existing implementations:
- `Grep` for `class DagConfigHandler`
- `Grep` for `class TaskExecutor`
- `Grep` for `def should_process_task`
- `Grep` for `class PipelineMonitor`

Record which components already exist. If infrastructure already exists, compute
`UTILS_IMPORT` from the existing file locations instead.

---

## Step 5: Launch Background Agents for File Generation

Launch **up to 4 background agents in a single message** to generate files in parallel.
Pass each agent the full set of resolved variables (`WORKFLOW_NAME`, `TASK_NAMES`,
`CONFIGS_DIR`, `SCRIPTS_DIR`, `SRC_DIR`, `UTILS_DIR`, `MODULE_DIR`, `SRC_PKG_DIR`,
`UTILS_IMPORT`, `SRC_PKG_IMPORT`, `KB_DIR`, `DAG_FILE`, `SCRIPT_FILE`) and instruct
it to write the files described below.

### Agent A: Infrastructure Utilities (conditional)

**Only launch if Step 4 found missing components.**

For each missing component, read the corresponding template and write the file:
- `DagConfigHandler` — use template from [templates/dag_config_handler.md](templates/dag_config_handler.md)
- `TaskExecutor` — use template from [templates/task_executor.md](templates/task_executor.md)
- `should_process_task` — use template from [templates/should_process_task.md](templates/should_process_task.md)
- `PipelineMonitor` — use template from [templates/pipeline_monitor.md](templates/pipeline_monitor.md)

Use the exact code from the templates. Substitute `{UTILS_DIR}` in file paths.

### Agent B: DAG Config + Workflow Script

This agent generates two files:

**File 1: DAG Config YAML** — write to `{CONFIGS_DIR}/{DAG_FILE}`.

Generate a `parameters:` section with a comment placeholder, then a `tasks:` section
with one entry per task. Build a **linear dependency chain**: the first task has
`depends_on: []`, each subsequent task depends on the previous one.

Each task entry has:
```yaml
  {task_name}:
    enabled: true
    options:
      force_processing: false
    depends_on: [{previous_task or empty}]
```

**File 2: Workflow Script** — write to `{SCRIPTS_DIR}/{SCRIPT_FILE}`.

The script must:
1. Import `logging`, `Path` from pathlib
2. Import `DagConfigHandler`, `TaskExecutor`, `PipelineMonitor` from the utils location
3. Import `should_process_task`, `clean_task_outputs` from the utils location
4. Import each task's `run_{task_name}` function from the module package
5. Define `run_single_session_pipeline(dag_handler, monitor, block_name) -> dict`:
   - Initialize a `context = {}` dict with a TODO comment to seed initial values
   - Build a `pipeline_stages` list of dicts, one per task. Each entry separates
     **inputs** (paths to read) from **outputs** (paths to write):
     ```python
     {"name": "{task_name}",
      "func": run_{task_name},
      "inputs": lambda: {
          # TODO: map context keys to input parameter names
          "input_csv": context["..."],
      },
      "outputs": lambda: {
          # TODO: construct fully resolved output paths
          "output_csv": output_dir / session_name / "{task_name}_result.csv",
      },
      "store": ["output_csv"]},
     ```
   - Executor loop over `enumerate(pipeline_stages)`:
     ```python
     for stage_idx, stage in enumerate(pipeline_stages):
         task_name = stage["name"]
         executor = TaskExecutor(task_name, block_name, dag_handler, monitor, session_name=block_name)
         with executor:
             if not executor.can_run:
                 continue

             inputs = stage["inputs"]()
             outputs = stage["outputs"]()
             input_paths = list(inputs.values())
             output_paths = list(outputs.values())

             options = dag_handler.get_task_options(task_name)
             force = options.get("force_processing", False)

             if not should_process_task(
                 input_paths=input_paths,
                 output_paths=output_paths,
                 force=force,
             ):
                 # Store output paths in context even when skipped
                 for key in stage.get("store", []):
                     context[key] = outputs[key]
                 continue

             clean_task_outputs(output_paths)
             stage["func"](**inputs, **outputs)

         # Store output paths in context for downstream stages
         for key in stage.get("store", []):
             outputs = stage["outputs"]()
             context[key] = outputs[key]

         # On error, skip remaining tasks
         if task_name in dag_handler.tasks and executor.error_msg:
             all_tasks = list(dag_handler.tasks.keys())
             current_task_index = all_tasks.index(task_name)
             for skipped_task in all_tasks[current_task_index + 1:]:
                 if monitor is not None:
                     monitor.update(block_name, skipped_task, "SKIPPED", "Skipped due to prior failure.")
             return {"status": "failed", "stage": stage_idx, "error": executor.error_msg}
     ```
   - Return `{"status": "success", "completed_tasks": list(dag_handler.completed_tasks)}`
5. Define `main()`:
   - Configuration section at the top of the function: hardcode `dag_config_path = Path("{CONFIGS_DIR}/{DAG_FILE}")`
     and any other workflow-specific constants as variables (no argparse, no CLI arguments)
   - Guard: if `dag_config_path` does not exist, log an error and `exit(1)`
   - Create `DagConfigHandler` from `dag_config_path`
   - `block_name = "TODO"` with a comment to resolve the actual block/session name
   - Create `PipelineMonitor` with task names
   - Call `run_single_session_pipeline(dag_handler, monitor, block_name)` and log completion
6. `if __name__ == "__main__": main()`

### Agent C: Pipeline Module Stubs + Shared Source Package

**Task modules** — Create `{MODULE_DIR}/` directory and `__init__.py`.

For each task name, read the template from [templates/pipeline_stub.md](templates/pipeline_stub.md)
and write `{MODULE_DIR}/{task_name}.py`. Substitute `{task_name}`, `{UTILS_IMPORT}`,
`{SRC_PKG_IMPORT}`.

The `__init__.py` should import each task's `run_` function:
```python
from .{task_name} import run_{task_name}
```

**Shared source package** — Create `{SRC_PKG_DIR}/` directory and `__init__.py`.

This package holds shared types, classes, and utilities that task modules import.
The `__init__.py` should contain a docstring explaining its purpose:
```python
"""
Shared package for the {WORKFLOW_NAME} workflow.

Place domain types, data classes, constants, and reusable processing
utilities here. Task modules in {MODULE_DIR}/ import from this package
via: ``from {SRC_PKG_IMPORT} import ...``
"""
```

### Agent D: How-To Guide + CLAUDE.md Link (conditional)

**Only launch if `{KB_DIR}/how-to-add-workflow-task.md` does NOT already exist.**

Read the template from [templates/how_to_guide.md](templates/how_to_guide.md) and write
the file to `{KB_DIR}/how-to-add-workflow-task.md`. Substitute `{MODULE_DIR}` and
`{UTILS_IMPORT}` with their resolved values so the guide is concrete for this project.

Then read the project's `CLAUDE.md`. If no `Workflow Architecture` heading already exists,
append:

```markdown

# Workflow Architecture

For a guide on the DAG workflow paradigm (task contracts, idempotency,
adding new tasks), see:
[{KB_DIR}/how-to-add-workflow-task.md]({KB_DIR}/how-to-add-workflow-task.md)
```

If the heading already exists, skip this addition.

---

## Step 6: Post-generation Summary

Wait for all background agents to complete, then print a summary:

1. **Files created** — list every file with its full path, including:
   - `{KB_DIR}/how-to-add-workflow-task.md` (if generated)
   - Note if `CLAUDE.md` was updated with the workflow architecture link
2. **Infrastructure** — note whether utils were generated or pre-existing
3. **Next steps**:
   - Populate `parameters:` in the DAG YAML with workflow-specific settings
   - Seed the `context` dict and resolve `block_name` in `main()` (the TODO placeholders)
   - To change the DAG config path, edit the `dag_config_path` constant at the top of `main()`
   - Add shared types, classes, and utilities to `{SRC_PKG_DIR}/`
   - Implement task logic in each pipeline module stub (replace `NotImplementedError`)
   - Run with: `python {SCRIPTS_DIR}/{SCRIPT_FILE}`

---

## Important Rules

- **Do NOT use Prefect** — no `@flow` decorators, no prefect imports
- **Tasks are pure processors** — they read inputs, process, write outputs. No idempotency checks, no force flag, no path construction, no file discovery
- **Tasks receive fully resolved paths** — every input and output is an exact file path provided by the workflow. No directory scanning, no glob, no `name_baseline`
- **Tasks return `None`** — the workflow already knows the output paths (it provided them)
- **Separate inputs from outputs** in `pipeline_stages` — use `inputs` and `outputs` lambdas, not a single `params` dict
- **Idempotency lives in the workflow** — `should_process_task()` + `clean_task_outputs()` are called by the executor loop, not by tasks
- **Wire through context** — output paths are stored in the `context` dict via the `store` list; downstream stages pull values in their `inputs` lambda
- **Linear dependency chain** in DAG YAML unless user specifies otherwise
- **Never overwrite existing files** without user confirmation
- **Use the exact infrastructure code** from the templates (do not simplify or omit methods)
