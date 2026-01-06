import os
import argparse
import skyset_tools
import json


parser = argparse.ArgumentParser(description="Skyset")
parser.add_argument("--project", type=str, help="Project name", required=True)
parser.add_argument("--tag", type=str, help="Tag name", required=True)
parser.add_argument("--patch_path", type=str, help="Patch path")
parser.add_argument("--action", type=str, help="Action name", choices=["checkout", "compile", "test_poc", "test_func", "all"], default="all")
parser.add_argument("--save", action="store_true", help="Save test report")

if __name__ == "__main__":
    args = parser.parse_args()
    sanitizer = skyset_tools.get_config(args.project, args.tag)["sanitizer"]

    if args.action in ["checkout", "all"]:
        print(f"Building {args.project}:{args.tag}")
        ret, stdout = skyset_tools.checkout(args.project, args.tag, sanitizer, patch_path=args.patch_path)
        if not ret:
            print("Build failed, check the logs below:")
            print(stdout)
            exit(0)
    
    if args.action in ["compile", "all"]:
        print(f"Compiling {args.project}:{args.tag}")
        ret, stdout = skyset_tools.compile(args.project, args.tag, sanitizer, patch_path=args.patch_path)
        if not ret:
            print("Compile failed, check the logs below:")
            print(stdout)
            exit(0)   

    if args.action in ["test_poc", "all"]:
        print(f"Testing {args.project}:{args.tag}")
        ret, report = skyset_tools.test(args.project, args.tag, sanitizer, patch=args.patch_path is not None)
        print(f"Test {'succeeded' if ret else 'failed'}")
        print("Test report:")
        print(report)

        report_path = os.path.join(os.path.dirname(__file__), args.project, args.tag, "report.txt")
        if args.save:
            with open(report_path, "w") as f:
                f.write(report)

    if args.action in ["test_func", "all"]:
        print(f"Testing {args.project}:{args.tag}")
        result = skyset_tools.test_functional(args.project, args.tag, sanitizer, patch_path=args.patch_path)
        ret = True if result["result"]=="passed" else False
        print(f"Test {'succeeded' if ret else 'failed'}")
        print("Test report:")
        # print(result)

        report_path = os.path.join(os.path.dirname(__file__), args.project, args.tag, "report.txt")
        if args.save and not ret:
            with open(report_path, "a") as f:
                f.write(str(result))
