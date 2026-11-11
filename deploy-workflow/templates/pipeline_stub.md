# Pipeline Module Stub Template

For each task name, create `{MODULE_DIR}/{task_name}.py` with:

```python
import logging
from pathlib import Path

# Shared package — import domain types, classes, and utilities from here:
# from {SRC_PKG_IMPORT} import MyClass, my_utility

log = logging.getLogger(__name__)


def run_{task_name}(
    input_path: Path,
    output_path: Path,
) -> None:
    """
    Process the {task_name} task.

    This task is a pure processor: it reads from ``input_path``, processes
    the data, and writes to ``output_path``.  It has no knowledge of file
    discovery, idempotency, or workflow orchestration — those concerns
    belong to the workflow.

    Parameters
    ----------
    input_path : Path
        Primary input file path.
        NOTE: Rename to a domain-specific name (e.g. ``video_path``,
        ``tracking_csv``). Add more input parameters as needed — each
        task declares exactly the inputs it requires.
    output_path : Path
        Output file path (fully resolved by the workflow).
        NOTE: Rename to a domain-specific name (e.g. ``summary_csv``,
        ``cleaned_output``). Add more output parameters as needed —
        each output is a separate named argument.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # TODO: implement processing logic here
    # Example:
    #   df = pd.read_csv(input_path)
    #   result_df = process(df)
    #   result_df.to_csv(output_path, index=False)
    log.info("[{task_name}] Processing %s -> %s", input_path.name, output_path.name)
    raise NotImplementedError("{task_name} logic not yet implemented")
```

**Adapting the stub to the task's needs:**

- **Multiple inputs**: rename `input_path` and add more parameters with
  domain-specific names. Each input is resolved by the workflow and passed
  via the `inputs` lambda in the pipeline stage.
  ```python
  def run_{task_name}(
      video_path: Path,
      tracking_csv: Path,
      metadata_path: Path,
      output_csv: Path,
  ) -> None:
  ```

- **Multiple outputs** (2 typical, 3 exceptional): add more output parameters
  with domain-specific names. Each output path is resolved by the workflow
  and passed via the `outputs` lambda in the pipeline stage.
  ```python
  def run_{task_name}(
      log_path: Path,
      voltages_output: Path,
      metadata_output: Path,
  ) -> None:
  ```

**What does NOT belong in a task:**
- `should_process_task()` or `clean_task_outputs()` — idempotency is the
  workflow's concern
- `force_processing` parameter — the workflow decides whether to call the task
- Output filename construction or `name_baseline` patterns — the workflow
  resolves all paths
- Directory scanning or file discovery — the workflow provides exact paths
- Returning `Path` — the workflow already knows the output paths (it provided
  them)

The `__init__.py` should import each task's `run_` function:
```python
from .{task_name} import run_{task_name}
```
