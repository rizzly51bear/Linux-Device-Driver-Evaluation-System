import os
import shutil
import datetime
import re
import subprocess

# --- Configuration ---
# Base directory for all evaluation runs
BASE_EVAL_DIR = "eval_runs"
# Directory where the user places AI-generated drivers for evaluation
DRIVERS_TO_EVALUATE_DIR = "drivers_to_evaluate"
# Name of the single file expected from the AI model containing all drivers
AI_OUTPUT_FILENAME = "ai_generated_drivers.txt"
# Path to the template Makefile
TEMPLATE_MAKEFILE = "template_Makefile"
# Path to the checkpatch.pl script
CHECKPATCH_SCRIPT = "tools/checkpatch.pl"

# --- Helper Functions ---

def setup_evaluation_run_dirs():
    """
    Sets up the base evaluation directory and the input directory for drivers.
    """
    print("Setting up evaluation directories...")
    os.makedirs(BASE_EVAL_DIR, exist_ok=True)
    os.makedirs(DRIVERS_TO_EVALUATE_DIR, exist_ok=True)
    print(f"Ensuring '{DRIVERS_TO_EVALUATE_DIR}/' and '{BASE_EVAL_DIR}/' exist.")

def print_ai_prompt_instructions(current_run_dir):
    """
    Prints instructions for the user to prompt the AI coding model and place files.
    """
    print("\n--- Linux Device Driver AI Evaluation System ---")
    print("Welcome! To begin, you will prompt your AI coding model for 5 distinct Linux device driver scenarios.")
    print("The AI should return ALL 5 code blocks in a single response.")
    print("For each scenario, the AI's output should be a Markdown code block, preceded by its intended filename.")
    print("Example format:")
    print("char_rw.c")
    print("```c")
    print("// C code for char_rw.c")
    print("```")
    print("platform_gpio_irq.c")
    print("```c")
    print("// C code for platform_gpio_irq.c")
    print("```")
    print(f"\nOnce you have the AI's complete response, copy the ENTIRE response (all code blocks and labels) ")
    print(f"and paste it into a single file named '{AI_OUTPUT_FILENAME}' in the following directory:")
    print(f"  {DRIVERS_TO_EVALUATE_DIR}/")
    print("\nHere are the recommended scenarios and their suggested filenames:")
    print("----------------------------------------------------------------------------------------------------")
    print("Scenario 1 (Character Device - Basic R/W): char_rw.c")
    print("  Create a simple character device driver that supports basic read/write operations with a 1KB internal buffer and registers /dev/mychardev.")
    print("Scenario 2 (Character Device - IOCTL & Concurrency): char_ioctl_sync.c")
    print("  Implement a character device driver with read()/write() operations and an ioctl interface to set/get an integer value. Include mutex-based synchronization for the internal buffer.")
    print("Scenario 3 (Platform Device - GPIO Interrupt): platform_gpio_irq.c")
    print("  Implement a platform device driver for a simulated GPIO. The driver should be able to read and write a GPIO register and handle an interrupt that increments a counter.")
    print("Scenario 4 (Character Device - ProcFS Entry): char_procfs.c")
    print("  Create a character device driver that also exposes an internal value (for example, a counter) via a /proc filesystem entry.")
    print("Scenario 5 (Generic Kernel Module): hello_module.c")
    print("  Generate a simple 'Hello World' Linux kernel module (not a device driver) that prints a message to the kernel log on module load and unload. It should not interact with any hardware devices.")
    print("----------------------------------------------------------------------------------------------------")
    print(f"\nPress Enter once your '{AI_OUTPUT_FILENAME}' file is placed in '{DRIVERS_TO_EVALUATE_DIR}/'.")
    input("Waiting for your input... ")

def parse_ai_output_file(file_path):
    """
    Parses a single file containing multiple AI-generated C code blocks.
    Each block is expected to be preceded by its filename.

    Args:
        file_path (str): The path to the single file containing AI output.

    Returns:
        list: A list of dictionaries, where each dict is {'filename': str, 'code_content': str}.
    """
    drivers_data = []
    current_filename = None
    current_code_lines = []
    in_code_block = False

    try:
        with open(file_path, 'r') as f:
            for line in f:
                # Check for filename pattern (e.g., "char_rw.c")
                # This regex looks for a line that ends with ".c" and optionally has a space before it.
                # It's flexible to catch filenames like "my_driver.c" or "some_other.c"
                filename_match = re.match(r'^\s*([a-zA-Z0-9_]+\.c)\s*$', line)
                
                if filename_match and not in_code_block:
                    # If we have previous code, save it
                    if current_filename and current_code_lines:
                        drivers_data.append({
                            'filename': current_filename,
                            'code_content': "".join(current_code_lines).strip()
                        })
                    # Start new block
                    current_filename = filename_match.group(1).strip()
                    current_code_lines = []
                    in_code_block = False # Ensure we're not inside a code block yet

                elif line.strip() == "```c":
                    in_code_block = True
                    continue # Don't add the ```c line to code content
                elif line.strip() == "```" and in_code_block:
                    in_code_block = False
                    # End of a code block, save it
                    if current_filename and current_code_lines:
                        drivers_data.append({
                            'filename': current_filename,
                            'code_content': "".join(current_code_lines).strip()
                        })
                        current_filename = None # Reset for next block
                        current_code_lines = []
                elif in_code_block:
                    current_code_lines.append(line)
    except FileNotFoundError:
        print(f"Error: AI output file '{file_path}' not found.")
        return []
    except Exception as e:
        print(f"Error parsing AI output file: {e}")
        return []

    # Handle case where the last code block might not have a trailing filename/new block
    if current_filename and current_code_lines:
        drivers_data.append({
            'filename': current_filename,
            'code_content': "".join(current_code_lines).strip()
        })

    return drivers_data


def determine_driver_category(code_content, filename):
    """
    Attempts to determine the driver category based on keywords in the code content.
    If uncertain, it will prompt the user for manual selection.

    Args:
        code_content (str): The full C code content of the driver.
        filename (str): The filename of the driver.

    Returns:
        str: The determined category (e.g., 'character_device', 'platform_device', 'generic_module', 'unknown').
    """
    code_content_lower = code_content.lower()
    category = 'unknown'

    # Keyword-based detection (can be expanded)
    if "register_chrdev" in code_content_lower or "cdev_add" in code_content_lower or "file_operations" in code_content_lower:
        if "proc_create" in code_content_lower or "/proc/" in code_content_lower:
            category = 'char_device_procfs'
        elif "ioctl" in code_content_lower or "unlocked_ioctl" in code_content_lower:
            category = 'char_device_ioctl_sync' # More specific for the given scenario
        else:
            category = 'char_device_basic_rw' # More specific for the given scenario
    elif "platform_driver" in code_content_lower and ("probe" in code_content_lower or "remove" in code_content_lower):
        if "gpio_request_one" in code_content_lower or "request_irq" in code_content_lower:
            category = 'platform_device_gpio_irq' # More specific for the given scenario
        else:
            category = 'platform_device'
    elif "module_init" in code_content_lower and "module_exit" in code_content_lower and \
         not any(k in code_content_lower for k in ["register_chrdev", "cdev_add", "platform_driver", "net_device", "gendisk"]):
        category = 'generic_kernel_module'

    # Manual fallback if category is unknown or needs refinement
    if category == 'unknown':
        print(f"\nCould not automatically determine category for '{filename}'.")
        print("Please manually select one of the following categories:")
        print("1. Character Device (Basic R/W)")
        print("2. Character Device (IOCTL & Concurrency)")
        print("3. Platform Device (GPIO Interrupt)")
        print("4. Character Device (ProcFS Entry)")
        print("5. Generic Kernel Module (Hello World)")
        print("6. Other/Unknown")

        while True:
            choice = input("Enter your choice (1-6): ").strip()
            if choice == '1':
                category = 'char_device_basic_rw'
                break
            elif choice == '2':
                category = 'char_device_ioctl_sync'
                break
            elif choice == '3':
                category = 'platform_device_gpio_irq'
                break
            elif choice == '4':
                category = 'char_device_procfs'
                break
            elif choice == '5':
                category = 'generic_kernel_module'
                break
            elif choice == '6':
                category = 'unknown'
                break
            else:
                print("Invalid choice. Please enter a number between 1 and 6.")
    else:
        print(f"Automatically detected '{filename}' as: {category}")

    return category

def evaluate_single_driver(driver_path, output_dir, category):
    """
    Placeholder function for evaluating a single driver.
    In future commits, this will contain compilation, static analysis, etc.
    """
    print(f"\n--- Evaluating Driver: {os.path.basename(driver_path)} (Category: {category}) ---")
    metrics = {
        "compilation": {"success": False, "errors_count": 0, "warnings_count": 0, "output": ""},
        "style": {"warnings_count": 0, "errors_count": 0, "output": ""},
        "static_analysis": {"issues_count": 0, "output": ""},
        "functionality": {"basic_test_passed": False, "kernel_oops_detected": False},
        "overall_score": 0
    }

    # --- Step 6.1: Compilation Assessment (Placeholder for now) ---
    print(f"  [STEP 6.1] Compiling {os.path.basename(driver_path)}...")
    # In a later commit, we'll run 'bear -- make' here.
    # For now, simulate success.
    metrics["compilation"]["success"] = True
    metrics["compilation"]["output"] = "Simulated compilation success."
    print("  Simulated compilation success.")

    # --- Step 6.2: Code Style Compliance (checkpatch.pl) (Placeholder for now) ---
    print(f"  [STEP 6.2] Running checkpatch.pl on {os.path.basename(driver_path)}...")
    # In a later commit, we'll run checkpatch.pl here.
    # For now, simulate some warnings.
    metrics["style"]["warnings_count"] = 2
    metrics["style"]["output"] = "Simulated checkpatch warnings."
    print("  Simulated checkpatch warnings.")

    # --- Step 6.3: Deep Static Analysis (clang-tidy) (Placeholder for now) ---
    print(f"  [STEP 6.3] Running clang-tidy on {os.path.basename(driver_path)}...")
    # In a later commit, we'll run clang-tidy here.
    # For now, simulate some issues.
    metrics["static_analysis"]["issues_count"] = 1
    metrics["static_analysis"]["output"] = "Simulated clang-tidy issue."
    print("  Simulated clang-tidy issue.")

    # --- Step 6.4: Functional Testing (Placeholder for now) ---
    print(f"  [STEP 6.4] Running basic functional tests on {os.path.basename(driver_path)}...")
    # In a later commit, we'll run insmod/rmmod and dmesg checks.
    metrics["functionality"]["basic_test_passed"] = True
    print("  Simulated basic functional test passed.")

    # --- Step 6.5: Scoring for the Single File (Placeholder for now) ---
    # Simple placeholder score calculation
    score = 100
    if not metrics["compilation"]["success"]:
        score -= 50
    score -= metrics["style"]["warnings_count"] * 5
    score -= metrics["static_analysis"]["issues_count"] * 10
    if metrics["functionality"]["kernel_oops_detected"]:
        score -= 100 # Major penalty
    metrics["overall_score"] = max(0, score) # Ensure score doesn't go below 0
    print(f"  Overall Score for {os.path.basename(driver_path)}: {metrics['overall_score']}/100")

    # Save individual file report (placeholder)
    with open(os.path.join(output_dir, "report.txt"), "w") as f:
        f.write(f"Evaluation Report for {os.path.basename(driver_path)}\n")
        f.write(f"Category: {category}\n")
        f.write(f"Compilation Success: {metrics['compilation']['success']}\n")
        f.write(f"Style Warnings: {metrics['style']['warnings_count']}\n")
        f.write(f"Static Analysis Issues: {metrics['static_analysis']['issues_count']}\n")
        f.write(f"Basic Functional Test Passed: {metrics['functionality']['basic_test_passed']}\n")
        f.write(f"Overall Score: {metrics['overall_score']}/100\n")
        # Add more details as needed

    return metrics

# --- Main Execution Flow ---
if __name__ == "__main__":
    overall_model_scores = []
    all_driver_results = []

    # Part 1: Setup & Code Generation (User-Driven, Guided by Script)
    setup_evaluation_run_dirs()

    # Create a unique timestamped directory for the current evaluation run
    timestamp = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
    current_run_dir = os.path.join(BASE_EVAL_DIR, timestamp)
    os.makedirs(current_run_dir, exist_ok=True)
    print(f"Created evaluation run directory: {current_run_dir}")

    # Print instructions and wait for user to place the AI output file
    print_ai_prompt_instructions(current_run_dir)

    ai_output_file_path = os.path.join(DRIVERS_TO_EVALUATE_DIR, AI_OUTPUT_FILENAME)

    # Check if the AI output file exists before parsing
    if not os.path.exists(ai_output_file_path):
        print(f"Error: The expected AI output file '{ai_output_file_path}' was not found.")
        print("Please ensure you have placed the AI's response correctly and try again.")
        exit(1)

    # Parse the single AI output file into individual driver code blocks
    print(f"\nParsing '{AI_OUTPUT_FILENAME}' for individual driver code blocks...")
    parsed_drivers = parse_ai_output_file(ai_output_file_path)

    if not parsed_drivers:
        print("No driver code blocks found in the AI output file. Exiting.")
        exit(1)

    print(f"Found {len(parsed_drivers)} driver code blocks.")

    # Part 2: Automated Evaluation of Each File
    for driver_info in parsed_drivers:
        driver_filename = driver_info['filename']
        driver_code_content = driver_info['code_content']

        # Create a sub-directory for this specific file's evaluation results
        file_eval_dir = os.path.join(current_run_dir, "results", os.path.splitext(driver_filename)[0])
        os.makedirs(file_eval_dir, exist_ok=True)
        print(f"\nProcessing '{driver_filename}' in: {file_eval_dir}")

        # Copy the .c file into its specific evaluation directory
        driver_target_path = os.path.join(file_eval_dir, driver_filename)
        with open(driver_target_path, "w") as f:
            f.write(driver_code_content)
        print(f"  Copied '{driver_filename}' to its evaluation directory.")

        # Copy and modify the template Makefile
        makefile_target_path = os.path.join(file_eval_dir, "Makefile")
        try:
            with open(TEMPLATE_MAKEFILE, 'r') as tmpl_f:
                makefile_content = tmpl_f.read()
            makefile_content = makefile_content.replace("$(DRIVER_NAME)", os.path.splitext(driver_filename)[0])
            with open(makefile_target_path, "w") as mf:
                mf.write(makefile_content)
            print(f"  Created Makefile for '{driver_filename}'.")
        except FileNotFoundError:
            print(f"Error: Template Makefile '{TEMPLATE_MAKEFILE}' not found. Please ensure it exists.")
            exit(1)

        # Determine Driver Category
        final_category = determine_driver_category(driver_code_content, driver_filename)

        # Execute Category-Specific Evaluation Function (placeholder for now)
        file_metrics = evaluate_single_driver(driver_target_path, file_eval_dir, final_category)
        all_driver_results.append(file_metrics)
        overall_model_scores.append(file_metrics["overall_score"])

    # Part 3: Overall Model Evaluation & Reporting
    if overall_model_scores:
        overall_model_score = sum(overall_model_scores) / len(overall_model_scores)
        print(f"\n--- Overall AI Model Evaluation ---")
        print(f"Average Score Across All Drivers: {overall_model_score:.2f}/100")

        # Placeholder for fine-tuning suggestions (will be expanded in later commits)
        print("\n--- Model Fine-tuning Suggestions (Placeholder) ---")
        print("Based on this evaluation, here are some areas where the AI model could improve:")
        print("- Ensure all generated modules compile without errors.")
        print("- Pay closer attention to Linux kernel coding style (e.g., line length, brace placement).")
        print("- Improve error handling for kernel API calls (e.g., checking kmalloc return values).")
        print("- Implement robust concurrency primitives where shared resources are used.")
        print("- Verify correct registration and unregistration of device types and /proc entries.")
        print("\nDetailed individual results are available in the 'eval_runs' directory.")
    else:
        print("\nNo drivers were successfully evaluated.")

    print("\nEvaluation complete!")
