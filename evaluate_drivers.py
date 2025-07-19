import os
import subprocess
import datetime
import json
import shutil # For copying files and directories

# --- Configuration ---
# Define your scenarios with filenames and basic descriptions
# This can eventually be loaded from scenarios.json if you make it more complex
SCENARIOS = [
    {"name": "char_rw", "category": "character_device", "filename": "char_rw.c",
     "prompt_desc": "Create a simple character device driver that supports basic read/write operations with a 1KB internal buffer and registers `/dev/mychardev`."},
    {"name": "char_ioctl_sync", "category": "character_device", "filename": "char_ioctl_sync.c",
     "prompt_desc": "Implement a character device driver with read/write, plus an `ioctl` to set/get an integer. Include basic mutex-based synchronization for its internal buffer."},
    {"name": "platform_gpio_irq", "category": "platform_device", "filename": "platform_gpio_irq.c",
     "prompt_desc": "Implement a platform device driver for a simulated GPIO. It should read/write to a GPIO register and handle an interrupt incrementing a counter."},
    {"name": "char_procfs", "category": "character_device", "filename": "char_procfs.c",
     "prompt_desc": "Create a character device driver that exposes information (e.g., a simple counter) via a `/proc` file system entry."},
    {"name": "hello_module", "category": "generic_kernel_module", "filename": "hello_module.c",
     "prompt_desc": "Generate a simple 'Hello World' kernel module that prints a message on load and unload, but does not interact with any hardware devices."}
]

TEMPLATE_MAKEFILE = "template_Makefile"
CHECKPATCH_PL_PATH = "tools/checkpatch.pl" # Adjust if you cloned full kernel source

# --- Helper Functions (will be expanded) ---

def setup_evaluation_run_dirs():
    """Creates the necessary directory structure for a new evaluation run."""
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = os.path.join("eval_runs", f"run_{timestamp}")
    drivers_dir = os.path.join(run_dir, "drivers_to_evaluate")
    results_dir = os.path.join(run_dir, "results")

    os.makedirs(drivers_dir, exist_ok=True)
    os.makedirs(results_dir, exist_ok=True)

    print(f"\nEvaluation run directory created: {run_dir}")
    print(f"Please place your AI-generated C files into: {drivers_dir}/\n")
    return run_dir, drivers_dir, results_dir

def print_ai_prompt_instructions(drivers_dir):
    """Prints instructions for the user to prompt the AI."""
    print("--- AI Code Generation Instructions ---")
    print("You will now prompt your AI coding model for the following 5 distinct Linux device driver scenarios.")
    print("For each scenario, copy the AI's generated C code into a separate `.c` file.")
    print(f"**IMPORTANT**: Save these 5 files in the following directory: {drivers_dir}/\n")

    for i, scenario in enumerate(SCENARIOS):
        print(f"Scenario {i+1} ({scenario['name']}):")
        print(f"  Suggested Filename: {scenario['filename']}")
        print(f"  Prompt Description: \"{scenario['prompt_desc']}\"\n")

    input("Press Enter once all 5 files are placed in the specified directory and you are ready to start evaluation...\n")

def determine_driver_category(code_content):
    """
    Analyzes code content to guess the driver category.
    This is your keyword-based detection logic.
    """
    code_content = code_content.lower()

    char_keywords = ["struct file_operations", "register_chrdev", "alloc_chrdev_region", "cdev_init", "cdev_add"]
    if any(keyword in code_content for keyword in char_keywords):
        return "character_device"

    platform_keywords = ["struct platform_driver", "platform_driver_register", "platform_device", "platform_get_resource", "platform_get_irq"]
    if any(keyword in code_content for keyword in platform_keywords):
        return "platform_device"

    # For the 'hello_module.c' scenario, specifically check for generic module init/exit
    # This should be less specific than device drivers
    generic_module_keywords = ["module_init", "module_exit", "printk(kern_info"] # Check for specific printk level
    if all(keyword in code_content for keyword in generic_module_keywords) and not any(k in code_content for k in char_keywords + platform_keywords):
        return "generic_kernel_module"

    return "unknown" # Fallback

def evaluate_single_driver(driver_filepath, results_dir, actual_category=None):
    """Evaluates a single driver file."""
    print(f"\n--- Evaluating {os.path.basename(driver_filepath)} ---")
    file_metrics = {
        "filename": os.path.basename(driver_filepath),
        "detected_category": None,
        "final_category": actual_category, # Pre-set if provided
        "compilation": {"success": False, "errors_count": 0, "warnings_count": 0, "output": ""},
        "checkpatch": {"warnings_count": 0, "errors_count": 0, "output": ""},
        "clang_tidy": {"warnings_count": 0, "errors_count": 0, "output": ""},
        "functionality": {"basic_test_passed": False, "kernel_oops_detected": False, "output": ""},
        "overall_score_for_file": 0
    }

    # Determine/Confirm Category
    with open(driver_filepath, 'r') as f:
        code_content = f.read()
    
    detected_cat = determine_driver_category(code_content)
    file_metrics["detected_category"] = detected_cat

    if file_metrics["final_category"] is None: # If not pre-set (e.g., from SCENARIOS config)
        if detected_cat == "unknown":
            print(f"WARNING: Automatic category detection failed for {file_metrics['filename']}.")
            print("Please manually input the category:")
            print("  1. character_device")
            print("  2. platform_device")
            print("  3. generic_kernel_module")
            while True:
                choice = input("Enter choice (1/2/3): ")
                if choice == '1':
                    file_metrics["final_category"] = "character_device"
                    break
                elif choice == '2':
                    file_metrics["final_category"] = "platform_device"
                    break
                elif choice == '3':
                    file_metrics["final_category"] = "generic_kernel_module"
                    break
                else:
                    print("Invalid choice. Please enter 1, 2, or 3.")
        else:
            file_metrics["final_category"] = detected_cat
            print(f"Category automatically detected as: {detected_cat}")
    else:
        print(f"Category pre-defined as: {file_metrics['final_category']}")

    # Create a unique directory for this driver's specific evaluation
    driver_eval_dir = os.path.join(results_dir, os.path.splitext(file_metrics['filename'])[0])
    os.makedirs(driver_eval_dir, exist_ok=True)
    shutil.copy(driver_filepath, driver_eval_dir)

    # Prepare Makefile for this specific driver
    driver_name = os.path.splitext(file_metrics['filename'])[0]
    local_makefile_path = os.path.join(driver_eval_dir, "Makefile")
    with open(TEMPLATE_MAKEFILE, 'r') as f_in:
        template_content = f_in.read()
    with open(local_makefile_path, 'w') as f_out:
        f_out.write(template_content.replace("$(DRIVER_NAME)", driver_name))

    # --- Step 1: Compilation Assessment ---
    print("Running compilation check...")
    try:
        # Use bear to generate compile_commands.json
        compile_command = f"bear -- make -C {driver_eval_dir}"
        process = subprocess.run(compile_command, shell=True, capture_output=True, text=True, cwd=driver_eval_dir)
        file_metrics["compilation"]["output"] = process.stdout + process.stderr
        file_metrics["compilation"]["success"] = process.returncode == 0
        file_metrics["compilation"]["errors_count"] = file_metrics["compilation"]["output"].lower().count("error:")
        file_metrics["compilation"]["warnings_count"] = file_metrics["compilation"]["output"].lower().count("warning:")
        if file_metrics["compilation"]["success"]:
            print("Compilation: SUCCESS")
        else:
            print(f"Compilation: FAILED ({file_metrics['compilation']['errors_count']} errors, {file_metrics['compilation']['warnings_count']} warnings)")
    except Exception as e:
        print(f"Error during compilation: {e}")
        file_metrics["compilation"]["output"] += f"\nError during script execution: {e}"

    # --- Step 2: Checkpatch.pl Assessment ---
    if os.path.exists(CHECKPATCH_PL_PATH):
        print("Running checkpatch.pl...")
        try:
            # --no-tree for standalone file, --file to treat as file not patch
            checkpatch_command = f"{CHECKPATCH_PL_PATH} --no-tree --file {os.path.join(driver_eval_dir, file_metrics['filename'])}"
            process = subprocess.run(checkpatch_command, shell=True, capture_output=True, text=True, cwd=driver_eval_dir)
            file_metrics["checkpatch"]["output"] = process.stdout + process.stderr
            # Simple counting for now, can be refined with regex
            file_metrics["checkpatch"]["errors_count"] = file_metrics["checkpatch"]["output"].count("ERROR:")
            file_metrics["checkpatch"]["warnings_count"] = file_metrics["checkpatch"]["output"].count("WARNING:")
            print(f"Checkpatch: {file_metrics['checkpatch']['errors_count']} errors, {file_metrics['checkpatch']['warnings_count']} warnings")
        except Exception as e:
            print(f"Error during checkpatch.pl: {e}")
            file_metrics["checkpatch"]["output"] += f"\nError during script execution: {e}"
    else:
        print(f"Skipping checkpatch.pl: {CHECKPATCH_PL_PATH} not found.")

    # --- Step 3: Clang-Tidy Assessment ---
    print("Running clang-tidy...")
    try:
        # -p . tells clang-tidy to use compile_commands.json in current dir
        clang_tidy_command = f"clang-tidy -p . --checks='linuxkernel-*,bugprone-*,misc-*,readability-*,performance-*' {os.path.join(driver_eval_dir, file_metrics['filename'])}"
        process = subprocess.run(clang_tidy_command, shell=True, capture_output=True, text=True, cwd=driver_eval_dir)
        file_metrics["clang_tidy"]["output"] = process.stdout + process.stderr
        # Clang-tidy usually outputs warnings and errors, count lines starting with error/warning
        file_metrics["clang_tidy"]["errors_count"] = file_metrics["clang_tidy"]["output"].lower().count("error:")
        file_metrics["clang_tidy"]["warnings_count"] = file_metrics["clang_tidy"]["output"].lower().count("warning:")
        print(f"Clang-Tidy: {file_metrics['clang_tidy']['errors_count']} errors, {file_metrics['clang_tidy']['warnings_count']} warnings")
    except Exception as e:
        print(f"Error during clang-tidy: {e}")
        file_metrics["clang_tidy"]["output"] += f"\nError during script execution: {e}"

    # --- Step 4: Basic Functional Testing (Placeholder for now) ---
    # This is where you'd add insmod/rmmod and dmesg checks, or simple userland interaction scripts
    print("Skipping detailed functional testing for now (placeholder).")
    file_metrics["functionality"]["basic_test_passed"] = True # Assume success for now

    # --- Score Calculation for this file ---
    # You'll need to define scoring logic here. Example weights:
    # Compilation: 40% (critical)
    # Clang-tidy: 30% (correctness, security)
    # Checkpatch: 20% (style)
    # Functionality: 10% (basic runtime)

    score = 0
    if file_metrics["compilation"]["success"]:
        score += 40
        # Deduct for warnings
        score -= min(file_metrics["compilation"]["warnings_count"], 10) # Max 10 pts deduction for warnings
    
    # Deduct for clang-tidy issues
    clang_tidy_deduction = (file_metrics["clang_tidy"]["errors_count"] * 5) + (file_metrics["clang_tidy"]["warnings_count"] * 2)
    score -= min(clang_tidy_deduction, 30) # Max 30 pts deduction

    # Deduct for checkpatch issues
    checkpatch_deduction = (file_metrics["checkpatch"]["errors_count"] * 3) + (file_metrics["checkpatch"]["warnings_count"] * 1)
    score -= min(checkpatch_deduction, 20) # Max 20 pts deduction

    if file_metrics["functionality"]["basic_test_passed"]:
        score += 10 # Only if basic tests pass

    file_metrics["overall_score_for_file"] = max(0, score) # Ensure score is not negative

    print(f"--- Finished evaluation for {file_metrics['filename']}. Score: {file_metrics['overall_score_for_file']}/100 ---\n")
    return file_metrics


# --- Main Execution Logic ---
if __name__ == "__main__":
    all_file_results = []
    
    # 1. Setup & Guide User
    run_base_dir, drivers_input_dir, results_output_dir = setup_evaluation_run_dirs()
    print_ai_prompt_instructions(drivers_input_dir)

    # 2. Automated Evaluation of Each File
    for scenario_info in SCENARIOS:
        expected_filepath = os.path.join(drivers_input_dir, scenario_info['filename'])
        
        if not os.path.exists(expected_filepath):
            print(f"ERROR: Expected file '{expected_filepath}' not found. Please ensure all 5 files are placed correctly.")
            print("Aborting evaluation. Please re-run the script after placing all files.")
            exit(1) # Exit if not all files are present
        
        file_results = evaluate_single_driver(expected_filepath, results_output_dir, actual_category=scenario_info['category'])
        all_file_results.append(file_results)
        
        # Save individual file metrics to its specific results directory
        file_specific_results_path = os.path.join(results_output_dir, os.path.splitext(scenario_info['filename'])[0], "metrics.json")
        with open(file_specific_results_path, 'w') as f:
            json.dump(file_results, f, indent=4)

    # 3. Calculate Overall Model Score & Generate Summary
    print("\n--- Overall Model Evaluation Summary ---")
    
    total_scores = 0
    num_evaluated_files = 0
    
    for res in all_file_results:
        total_scores += res["overall_score_for_file"]
        num_evaluated_files += 1

    overall_model_score = total_scores / num_evaluated_files if num_evaluated_files > 0 else 0
    print(f"\nOverall AI Model Score (Average across {num_evaluated_files} scenarios): {overall_model_score:.2f}/100")

    # Generate fine-tuning suggestions (simple placeholder for now)
    print("\n--- Model Fine-tuning Suggestions ---")
    suggestions = []

    # Example: Check for common compilation errors/warnings
    compilation_failures = [f for f in all_file_results if not f["compilation"]["success"]]
    if compilation_failures:
        suggestions.append(f"Model failed to compile in {len(compilation_failures)} out of {num_evaluated_files} scenarios. Focus on basic C syntax, missing headers, and linking issues in kernel modules.")
    
    total_checkpatch_warnings = sum(f["checkpatch"]["warnings_count"] for f in all_file_results)
    total_checkpatch_errors = sum(f["checkpatch"]["errors_count"] for f in all_file_results)
    if total_checkpatch_warnings > 0 or total_checkpatch_errors > 0:
        suggestions.append(f"Model generated code with {total_checkpatch_warnings} checkpatch warnings and {total_checkpatch_errors} errors overall. Emphasize adherence to Linux kernel coding style (e.g., line length, indentation, brace placement).")

    total_clang_tidy_warnings = sum(f["clang_tidy"]["warnings_count"] for f in all_file_results)
    total_clang_tidy_errors = sum(f["clang_tidy"]["errors_count"] for f in all_file_results)
    if total_clang_tidy_warnings > 0 or total_clang_tidy_errors > 0:
        suggestions.append(f"Model had {total_clang_tidy_warnings} clang-tidy warnings and {total_clang_tidy_errors} errors overall. Prioritize: \n  - Correct error handling and resource cleanup (e.g., `goto` on error paths, `IS_ERR` checks).\n  - Proper use of kernel APIs and data structures (e.g., memory management, synchronization primitives like mutexes/spinlocks).")

    if not suggestions:
        suggestions.append("Model performed very well! No specific critical fine-tuning suggestions at this time based on static analysis.")

    for s in suggestions:
        print(f"- {s}")
    
    # Save overall summary
    overall_summary = {
        "overall_model_score": f"{overall_model_score:.2f}/100",
        "individual_file_results": all_file_results,
        "fine_tuning_suggestions": suggestions
    }
    with open(os.path.join(run_base_dir, "overall_summary.json"), 'w') as f:
        json.dump(overall_summary, f, indent=4)

    print(f"\nDetailed results saved in: {run_base_dir}/")
    print("Evaluation complete!")
