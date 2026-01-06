# skyset

**IMPORTANT**: All test cases can be compiled and triggered using `skyset_tools/asan{++/cc}` in the Docker container specified in `.devcontainer/Dockerfile`. However, we cannot guarantee success if you change the compiler or Docker configuration.

## Dataset Structure

```
{PROJECT NAME}
    - build.sh 
    - {VULNERABILITY-TAG}
      - @POC@
      - exp.sh
      - config.yml
      - report.txt
      - patch.diff
```

The `build.sh` script should be executed within the project directory. It can accept `CC` and `CXX` as environment variables. The `exp.sh` script takes `@POC@` as input to execute the program. The `report.txt` file displays the address sanitizer report. The `patch.diff` serves as the ground truth patch.

A example of `config.yml`:
```yaml
fix_commit: b8ff98c810f1bf8e8000f44be2f4af30a7ba43fa
fix_date: '2024-02-05'
project: wasm-micro-runtime
sanitizer: AddressSanitizer
tag: 06df58f-null_pointer_deref
```

## Usage

```
usage: run.py [-h] --project PROJECT --tag TAG [--patch_path PATCH_PATH] [--action {checkout,compile,test_poc,test_func,all}] [--save]

Skyset

options:
  -h, --help            show this help message and exit
  --project PROJECT     Project name
  --tag TAG             Tag name
  --patch_path PATCH_PATH
                        Patch path
  --action {checkout,compile,test_poc,test_func,all}
                        Action name
  --save                choose to save the report or not
```