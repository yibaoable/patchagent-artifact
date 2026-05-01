# PatchAgent-artifact


## Adaptation Notes

We reproduced this project based on the original code and the [documentation](README.bak.md).

- Supports the `patcheval`, `vul4j`, `vjbench`, and `secbench` datasets
- Provides two workflow modes
    - PatchAgent default mode: with feedback. This mode is used by default and is intended for RQ4.
    - Added mode: without feedback. Execution stops immediately after one validation round. Specify it with `--single_shot_validate`. This is intended for RQ4.

## Usage

1. Environment setup
```
conda create -p /opt/venv/conda/envs/py313 python=3.13
uv venv --python /opt/venv/conda/envs/py313/bin/python
source .venv/bin/activate

python -m ensurepip --upgrade
python -m pip install --upgrade pip setuptools wheel

python -m pip install python-dotenv GitPython pika meson pandas openpyxl clang==16.0.1 unidiff litellm prettytable matplotlib venn langchain==0.2.5 langchain-community==0.2.5 langchain-core==0.2.9 langchain-experimental==0.0.61 langchain-openai==0.1.8 openai==1.35.1 httpx==0.27.2 docker

# Add the OPENAI_BASE_URL and OPENAI_API_KEY fields to .env
cp .env.tmp .env

```

2. Evaluation
RQ 1
```
# Example
 ./nwtool \
    --dataset patcheval \
    --model gpt_5_4 \
    --input_mode vuln_func \
    --tmux \
    --single_shot_validate \
    --tag CVE-2023-24623
```
- `dataset`: one of `patcheval`, `vul4j`, `vjbench`, or `secbench`
- `model`: currently supports `gpt_5_4`
    - **To change or add a model**, update `OPENAI_API_KEY` and `OPENAI_BASE_URL` in `.env`, then add a `readable_model_name -> actual_model_id` mapping to `MODEL_ALIASES` in `nvwa/model_aliases.py`. For example: `"gpt_5_4_mini":"gpt-5-4-mini"`
- `input_mode`: one of `sanitizer` or `vuln_func`
- `tmux`: enables concurrent repair. You can set the concurrency with `--max_sessions`; the default is `5`
- `single_shot_validate`: uses the no-feedback mode. If this argument is omitted, the feedback-enabled mode is used by default
- `tag`: can be used to repair a single case. If omitted, all cases are repaired by default

RQ 4
```
# Example
 ./nwtool \
    --dataset patcheval \
    --model gpt_5_4 \
    --input_mode vuln_func \
    --tmux \
    --tag CVE-2023-24623
```

3. View results

Output directory: `results/{model_name}/{dataset}/{input_mode}`

Example:
```
results
results/gpt_5_4
├── patcheval
│   └── vuln_func
        └── CVE-2023-24623
```
Summarize results:
```bash
# result_dir, for example: results/gpt_5_4/vul4j/vuln_func
python results/analyse_result.py -d {result_dir} -m {input_mode}
```
The summary file `final_result.json` is saved to `result_dir` by default.
