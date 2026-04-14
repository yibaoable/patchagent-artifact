import json
import os
import argparse
from pathlib import Path

def analyze_validation_results(directory_path, mode='single_validate'):
    """
    统计指定目录下所有 JSON 文件的验证结果
    
    Args:
        directory_path: 包含 JSON 文件的目录路径
        mode: 模式选择，'single_validate' 或 'normal'
    
    Returns:
        dict: 包含统计结果的字典
    """
    # 存储结果
    passed_cases = []
    failed_cases = []
    
    # 获取目录下所有 JSON 文件
    json_files = list(Path(directory_path).glob("*.json"))
    
    if not json_files:
        print(f"在目录 {directory_path} 中未找到 JSON 文件")
        return None
    
    print(f"使用模式: {'Single Shot模式' if mode == 'single_validate' else '普通模式'}")
    print(f"找到 {len(json_files)-1} 个JSON文件\n")
    
    for json_file in json_files:
        if json_file.stem == "final_result":
            continue
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Handle both format: old format (list) and new format (dict with contexts)
            if isinstance(data, dict) and "contexts" in data:
                contexts = data.get("contexts", [])
            elif isinstance(data, list):
                contexts = data
            else:
                print(f"警告: {json_file.name} 数据格式不正确或为空")
                continue
            
            if len(contexts) == 0:
                print(f"警告: {json_file.name} contexts 为空")
                continue
            
            # 获取最后一个字典
            last_item = contexts[-1]
            
            if mode == 'single_validate':
                # Single Shot 模式：查看 patch_validation_results
                if 'patch_validation_results' not in last_item:
                    print(f"警告: {json_file.name} 中没有 patch_validation_results 字段")
                    continue
                
                validation_results = last_item['patch_validation_results']
                
                # 如果没有验证结果，跳过
                if not validation_results:
                    print(f"警告: {json_file.name} 中 patch_validation_results 为空")
                    continue
                
                # 获取最后一个验证结果
                last_validation = validation_results[-1]
                
                if 'validation_passed' not in last_validation:
                    print(f"警告: {json_file.name} 中没有 validation_passed 字段")
                    continue
                
                # 根据 validation_passed 分类
                if last_validation['validation_passed']:
                    passed_cases.append(json_file.stem)
                else:
                    failed_cases.append(json_file.stem)
                    
            else:  # normal mode
                # 普通模式：查看 patch 字段是否为 null
                if 'patch' not in last_item:
                    print(f"警告: {json_file.name} 中没有 patch 字段")
                    continue
                
                patch_value = last_item['patch']
                
                # 如果 patch 为 None 或空字符串，则认为是失败
                if patch_value is None or patch_value == "":
                    failed_cases.append(json_file.stem)
                else:
                    passed_cases.append(json_file.stem)
                
        except json.JSONDecodeError as e:
            print(f"错误: {json_file.name} JSON 解析失败: {e}")
        except Exception as e:
            print(f"错误: 处理 {json_file.name} 时发生异常: {e}")
    
    # 统计结果
    stats = {
        'mode': mode,
        'total_cases': len(passed_cases) + len(failed_cases),
        'passed_count': len(passed_cases),
        'failed_count': len(failed_cases),
        'passed_cases': passed_cases,
        'failed_cases': failed_cases
    }
    
    return stats

def print_statistics(stats):
    """打印统计结果"""
    if not stats:
        return
    
    print("=" * 60)
    print("验证结果统计报告")
    print("=" * 60)
    print(f"分析模式: {'Single Shot模式' if stats['mode'] == 'single_validate' else '普通模式'}")
    print(f"总案例数: {stats['total_cases']}")
    print(f"通过案例数: {stats['passed_count']} ({stats['passed_count']/stats['total_cases']*100:.1f}%)")
    print(f"失败案例数: {stats['failed_count']} ({stats['failed_count']/stats['total_cases']*100:.1f}%)")
    print("\n" + "=" * 60)
    
    if stats['passed_cases']:
        print("\n通过的案例列表:")
        for case in stats['passed_cases']:
            print(f"  ✓ {case}")
    
    if stats['failed_cases']:
        print("\n失败的案例列表:")
        for case in stats['failed_cases']:
            print(f"  ✗ {case}")
    
    print("\n" + "=" * 60)

def main():
    """主函数，解析命令行参数"""
    parser = argparse.ArgumentParser(
        description='统计JSON文件中验证结果',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    
    parser.add_argument(
        '-d', '--directory',
        help='包含JSON文件的目录路径'
    )
    
    parser.add_argument(
        '-m', '--mode',
        choices=['single_validate', 'normal'],
        default='single_validate',
        help='分析模式: single_validate=查看validation_passed, normal=查看patch是否为null (默认: single_validate)'
    )
    
    parser.add_argument(
        '--no-save',
        action='store_true',
        help='不保存结果到JSON文件'
    )
    
    args = parser.parse_args()
    
    # 检查目录是否存在
    if not os.path.exists(args.directory):
        print(f"错误: 目录 '{args.directory}' 不存在")
        return
    
    if not os.path.isdir(args.directory):
        print(f"错误: '{args.directory}' 不是一个目录")
        return
    
    # 分析结果
    results = analyze_validation_results(args.directory, args.mode)
    
    # 打印统计信息
    print_statistics(results)
    
    # 保存结果到文件
    if results and not args.no_save:
        output_path = f"{args.directory}/final_result.json"
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"\n详细结果已保存到 {output_path}")

if __name__ == "__main__":
    main()