# 加载所有config.yml并存为一个json
import os
import yaml
import json
from pathlib import Path

def get_commit(tag: str) -> str:
    return tag if "-" not in tag else tag.split("-")[0]

def load_all_configs(root_dir, output_json_path):
    """
    从指定根目录加载所有 config.yml 文件，汇总保存到单个 JSON 文件
    
    Args:
        root_dir: 项目根目录路径
        output_json_path: 输出的单个 JSON 文件完整路径（包含文件名）
    
    Returns:
        dict: 包含所有配置信息的字典，键为配置文件的相对路径，值为配置内容
    """
    # 存储所有配置数据，键为相对路径，便于识别来源
    all_configs = {}
    
    # 遍历根目录下所有文件
    counter = 1
    for root, dirs, files in os.walk(root_dir):
        # 查找 config.yml 文件
        if 'config.yml' in files:
            config_file = Path(root) / 'config.yml'
            
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    config_data = yaml.safe_load(f)
                
                relative_path = str(config_file.relative_to(root_dir))
                project_name = Path(root).parts[len(Path(root_dir).parts)] if len(Path(root).parts) > len(Path(root_dir).parts) else "unknown"
                target_key = f"{project_name}-{counter}"
                commit = get_commit(config_data["tag"])
                config_data["vul_commit"] = commit
                config_data["project"] = project_name
                config_data["vul_func"] = []


                all_configs[target_key] = config_data
                print(f"成功加载: {relative_path}")
                counter += 1
            
            except Exception as e:
                print(f"处理配置文件 {config_file} 时出错: {e}")
    
    # 将所有配置保存到单个 JSON 文件
    output_dir = Path(output_json_path).parent
    output_dir.mkdir(parents=True, exist_ok=True)
    
    with open(output_json_path, 'w', encoding='utf-8') as f:
        json.dump(all_configs, f, indent=4, ensure_ascii=False)
    
    print(f"\n所有配置已汇总保存到: {output_json_path}")
    print(f"共加载 {len(all_configs)} 个配置文件")
    
    return all_configs

if __name__ == "__main__":
    # 根目录
    SKYSET_ROOT = Path(__file__).resolve().parents[0]
    
    # 输出的单个 JSON 文件路径
    OUTPUT_JSON_FILE = SKYSET_ROOT / "patchagent_dataset.json"
    
    # 加载所有 config.yml 并保存到单个 JSON
    all_configs = load_all_configs(SKYSET_ROOT, OUTPUT_JSON_FILE)
    print("转换完成, 保存至: ",OUTPUT_JSON_FILE)