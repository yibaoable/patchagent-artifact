#!/usr/bin/env python3
# 批量执行操作
import subprocess
import sys
import time
from datetime import datetime
import json


def run_command(project, tag, action="checkout", timeout=3600):
    """执行单个命令"""
    cmd = [
        "python", "skyset/run.py",
        "--project", project,
        "--tag", tag,
        "--action", action
    ]
    
    print(f"\n{'='*60}")
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 开始执行: {project}/{tag}")
    print(f"命令: {' '.join(cmd)}")
    print(f"{'='*60}")
    
    start_time = time.time()
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        
        elapsed = time.time() - start_time
        
        # 输出结果
        print(f"[耗时: {elapsed:.2f}秒]")
        print(f"返回码: {result.returncode}")
        
        if result.stdout:
            print(f"标准输出 (前500字符):")
            print(result.stdout[:500] + ("..." if len(result.stdout) > 500 else ""))
        
        if result.stderr:
            print(f"错误输出 (前500字符):")
            print(result.stderr[:500] + ("..." if len(result.stderr) > 500 else ""))
        
        if result.returncode == 0:
            print(f"✅ {project}/{tag} {action} 成功")
            return True, elapsed
        else:
            print(f"❌ {project}/{tag} {action} 失败")
            return False, elapsed
            
    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        print(f"⏰ {project}/{tag} {action} 超时 ({timeout}秒)")
        return False, elapsed
    
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"⚠️ {project}/{tag} {action} 异常: {str(e)}")
        return False, elapsed

def batch_run(projects_data, action="checkout", max_workers=1):
    """批量执行"""
    total = len(projects_data)
    completed = 0
    successful = 0
    failed = 0
    
    print(f"开始批量执行，共 {total} 个任务")
    print(f"操作: {action}")
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    results = []

    for tag, data in projects_data.items():
        project = data.get("project")
        
        completed += 1
        print(f"\n[进度: {completed}/{total}]")
        success, elapsed = run_command(project, tag, action)
        if success:
            successful += 1
        else:
            failed += 1
        
        results.append({
            "project": project,
            "tag": tag,
            "success": success,
            "elapsed": elapsed,
            "action": action
        })
        
        if completed < total:
            time.sleep(2)
    
    # 生成统计报告
    print(f"\n{'='*60}")
    print(f"批量执行完成")
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"总计任务: {total}")
    print(f"成功: {successful}")
    print(f"失败: {failed}")
    print(f"成功率: {successful/total*100:.1f}%")
    
    # 输出详细结果
    print(f"\n详细结果:")
    for r in results:
        status = "✅ 成功" if r["success"] else "❌ 失败"
        print(f"  {r['project']}/{r['tag']}: {status} ({r['elapsed']:.1f}s)")
    
    return results

if __name__ == "__main__":
    # 默认执行 checkout 操作，可以通过命令行参数指定
    action = sys.argv[1] if len(sys.argv) > 1 else "checkout"
    
    dataset = "skyset/patchagent_dataset.json"
    with open(dataset) as f:
        project_data = json.load(f)
    results = batch_run(project_data, action=action)
    
    # 可选：将结果保存到文件
    with open(f"batch_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n结果已保存到 JSON 文件")