import json
import os
import argparse
from pathlib import Path

def analyze_validation_results(directory_path, mode='single_validate'):
    """
    Summarize validation results from all JSON files in the target directory.

    Args:
        directory_path: Directory path containing JSON files
        mode: Mode selection, either 'single_validate' or 'normal'

    Returns:
        dict: Dictionary containing the aggregated statistics
    """
    # Store results
    passed_cases = []
    failed_cases = []
    patches = []

    # Get all JSON files in the directory
    json_files = list(Path(directory_path).glob("*.json"))

    if not json_files:
        print(f"No JSON files found in directory {directory_path}")
        return None

    print(f"Mode: {'Single Shot' if mode == 'single_validate' else 'Normal'}")
    print(f"Found {len(json_files)-1} JSON files\n")

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
                print(f"Warning: {json_file.name} has an invalid or empty data format")
                continue

            if len(contexts) == 0:
                print(f"Warning: {json_file.name} has empty contexts")
                continue

            # Get the last dictionary item
            last_item = contexts[-1]

            # Collect patch information for exporting patches.json
            patch_value_for_export = last_item.get('patch', "") if isinstance(last_item, dict) else ""
            if patch_value_for_export is None:
                patch_value_for_export = ""
            patches.append({
                'cve': json_file.stem,
                'fix_patch': patch_value_for_export
            })

            if mode == 'single_validate':
                # Single Shot mode: inspect patch_validation_results
                if 'patch_validation_results' not in last_item:
                    print(f"Warning: {json_file.name} does not contain the patch_validation_results field")
                    continue

                validation_results = last_item['patch_validation_results']

                # Skip if there are no validation results
                if not validation_results:
                    print(f"Warning: {json_file.name} has empty patch_validation_results")
                    continue

                # Get the last validation result
                last_validation = validation_results[-1]

                if 'validation_passed' not in last_validation:
                    print(f"Warning: {json_file.name} does not contain the validation_passed field")
                    continue

                # Classify based on validation_passed
                if last_validation['validation_passed']:
                    passed_cases.append(json_file.stem)
                else:
                    failed_cases.append(json_file.stem)

            else:  # normal mode
                # Normal mode: inspect whether the patch field is null
                if 'patch' not in last_item:
                    print(f"Warning: {json_file.name} does not contain the patch field")
                    continue

                patch_value = last_item['patch']

                # Treat None or an empty string as failure
                if patch_value is None or patch_value == "":
                    failed_cases.append(json_file.stem)
                else:
                    passed_cases.append(json_file.stem)

        except json.JSONDecodeError as e:
            print(f"Error: Failed to parse JSON in {json_file.name}: {e}")
        except Exception as e:
            print(f"Error: Exception occurred while processing {json_file.name}: {e}")

    # Aggregate statistics
    stats = {
        'mode': mode,
        'total_cases': len(passed_cases) + len(failed_cases),
        'passed_count': len(passed_cases),
        'failed_count': len(failed_cases),
        'passed_cases': passed_cases,
        'failed_cases': failed_cases,
        'patches': patches
    }

    return stats

def print_statistics(stats):
    """Print aggregated statistics."""
    if not stats:
        return

    print("=" * 60)
    print("Validation Results Summary")
    print("=" * 60)
    print(f"Analysis mode: {'Single Shot' if stats['mode'] == 'single_validate' else 'Normal'}")
    print(f"Total cases: {stats['total_cases']}")
    if stats['total_cases'] > 0:
        print(f"Passed cases: {stats['passed_count']} ({stats['passed_count']/stats['total_cases']*100:.1f}%)")
        print(f"Failed cases: {stats['failed_count']} ({stats['failed_count']/stats['total_cases']*100:.1f}%)")
    else:
        print("Passed cases: 0 (0.0%)")
        print("Failed cases: 0 (0.0%)")
    print("\n" + "=" * 60)

    if stats['passed_cases']:
        print("\nPassed cases:")
        for case in stats['passed_cases']:
            print(f"  ✓ {case}")

    if stats['failed_cases']:
        print("\nFailed cases:")
        for case in stats['failed_cases']:
            print(f"  ✗ {case}")

    print("\n" + "=" * 60)

def main():
    """Main function for parsing command-line arguments."""
    parser = argparse.ArgumentParser(
        description='Summarize validation results in JSON files',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        '-d', '--directory',
        help='Directory path containing JSON files'
    )

    parser.add_argument(
        '-m', '--mode',
        choices=['single_validate', 'normal'],
        default='single_validate',
        help='Analysis mode: single_validate=check validation_passed, normal=check whether patch is null (default: single_validate)'
    )

    parser.add_argument(
        '--no-save',
        action='store_true',
        help='Do not save results to a JSON file'
    )

    args = parser.parse_args()

    # Check whether the directory exists
    if not os.path.exists(args.directory):
        print(f"Error: Directory '{args.directory}' does not exist")
        return

    if not os.path.isdir(args.directory):
        print(f"Error: '{args.directory}' is not a directory")
        return

    # Analyze results
    results = analyze_validation_results(args.directory, args.mode)

    # Print statistics
    print_statistics(results)

    # Save results to files
    if results and not args.no_save:
        output_path = f"{args.directory}/final_result.json"
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"\nDetailed results have been saved to {output_path}")

        # Export patches.json by default in the same directory as final_result.json
        patches_output_path = f"{args.directory}/patches.json"
        with open(patches_output_path, 'w', encoding='utf-8') as f:
            json.dump(results.get('patches', []), f, indent=2, ensure_ascii=False)
        print(f"Patch list has been saved to {patches_output_path}")

if __name__ == "__main__":
    main()
