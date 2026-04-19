## 适配说明

- 支持 patcheval，vul4j，vjbench，secbench数据集
- 两种工作流模式
    - patchagent的默认模式：带feedback。默认使用该模式。
    - 新增模式：不带feedback，验证完一次立刻结束。使用 --single_shot_validate 指定
- 两种输入设置
    - patchagent的默认输入：带sanitizer report；且有sanitzier优化机制。使用--input_mode sanitizer指定
    - 新增输出设置：输入vuln_func作为漏洞定位信息，不再使用sanitizer优化。使用--input_mode vuln_func指定
    - secbench支持两种输入设置，其余数据集仅支持vuln_func设置

## 使用说明

1. 环境准备
```
uv venv --python /opt/venv/conda/envs/py313/bin/python
source .venv/bin/activate

python -m ensurepip --upgrade
python -m pip install --upgrade pip setuptools wheel

python -m pip install python-dotenv GitPython pika meson pandas openpyxl clang==16.0.1 unidiff litellm prettytable matplotlib venn langchain==0.2.5 langchain-community==0.2.5 langchain-core==0.2.9 langchain-experimental==0.0.61 langchain-openai==0.1.8 openai==1.35.1 httpx==0.27.2 docker

# .env 补充OPENAI_BASE_URL和OPENAI_API_KEY字段
cp .env.tmp .env

```

2. 修复
```
# 示例
 ./nwtool \
    --dataset vul4j \
    --model doubao1_8 \
    --input_mode vuln_func \
    --tmux \
    --single_shot_validate \
    --tag VUL4J-1 
```
- dataset:可选 patcheval，vul4j，vjbench，secbench
- model:可选 deepseekv3, doubao1_8, doubao2_0
    - **如需更换/新增模型**，更换.env中的OPENAI_API_KEY和OPENAI_BASE_URL字段，并在 `nvwa/model_aliases.py` 的 `MODEL_ALIASES` 中添加 `可读model名-实际model_id` 映射。例如`"deepseekv3":"ep-20251205193935-fsfw9"`
- input_mode:可选 sanitizer，vuln_func
- tmux:启动并发修复。可通过 --max_sessions 指定并发数，默认为5
- single_shot_validate: 使用不带feedback的模式。不添加该参数则默认使用带feedback的模式
- tag: 可指定修复单个case。不加该参数则默认修全部

3. 查看结果

输出目录：results/{model_name}/{dataset}/{input_mode}

示例：
```
results
├── doubao1_8
    ├──secbench
        ├──sanitizer
           ├──id1.json
            ├──id2.json
        ├──vuln_func
            ├──id1.json
            ├──id2.json
    ├──vul4j
        ├──vuln_func
            ├──id1.json
            ├──id2.json
├── deepseekv3
└── doubao2_0

```
统计结果
```bash
# result_dir 如results/doubao1_8/vul4j/vuln_func
python results/analyse_result.py -d {result_dir} -m {input_mode}
```
统计结果final_result.json默认保存在result_dir