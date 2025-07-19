import os
import shutil
import datetime
import re
import subprocess
import logging
import json # New import for JSON output

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

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO, # Set to INFO for general messages, DEBUG for more verbose
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler() # Output to console
        # logging.FileHandler(f"evaluation_{datetime.datetime.now().strftime('%Y%m%dT%H%M%S')}.log") # Optional: Output to a file
    ]
)
logger = logging.getLogger(__name__)

# --- Helper Functions ---

def setup_evaluation_run_dirs():
    """
    Sets up the base evaluation directory and the input directory for drivers.
    """
    logger.info("Setting up evaluation directories...")
    os.makedirs(BASE_EVAL_DIR, exist_ok=True)
    os.makedirs(DRIVERS_TO_EVALUATE_DIR, exist_ok=True)
    logger.info(f"Ensuring '{DRIVERS_TO_EVALUATE_DIR}/' and '{BASE_EVAL_DIR}/' exist.")

def print_ai_prompt_instructions(current_run_dir):
    """
    Prints instructions for the user to prompt the AI coding model and place files.
    """
    logger.info("\n--- Linux Device Driver AI Evaluation System ---")
    logger.info("Welcome! To begin, you will prompt your AI coding model for 5 distinct Linux device driver scenarios.")
    logger.info("The AI should return ALL 5 code blocks in a single response.")
    logger.info("For each scenario, the AI's output should be a Markdown code block, preceded by its intended filename.")
    logger.info("Example format:")
    logger.info("char_rw.c")
    logger.info("```c")
    logger.info("// C code for char_rw.c")
    logger.info("```")
    logger.info("platform_gpio_irq.c")
    logger.info("```c")
    logger.info("// C code for platform_gpio_irq.c")
    logger.info("```")
    logger.info(f"\nOnce you have the AI's complete response, copy the ENTIRE response (all code blocks and labels) ")
    logger.info(f"and paste it into a single file named '{AI_OUTPUT_FILENAME}' in the following directory:")
    logger.info(f"  {DRIVERS_TO_EVALUATE_DIR}/")
    logger.info("\nHere are the recommended scenarios and their suggested filenames:")
    logger.info("----------------------------------------------------------------------------------------------------")
    logger.info("Scenario 1 (Character Device - Basic R/W): char_rw.c")
    logger.info("  Create a simple character device driver that supports basic read/write operations with a 1KB internal buffer and registers /dev/mychardev.")
    logger.info("Scenario 2 (Character Device - IOCTL & Concurrency): char_ioctl_sync.c")
    logger.info("  Implement a character device driver with read()/write() operations and an ioctl interface to set/get an integer value. Include mutex-based synchronization for the internal buffer.")
    logger.info("Scenario 3 (Platform Device - GPIO Interrupt): platform_gpio_irq.c")
    logger.info("  Implement a platform device driver for a simulated GPIO. The driver should be able to read and write a GPIO register and handle an interrupt that increments a counter.")
    logger.info("Scenario 4 (Character Device - ProcFS Entry): char_procfs.c")
    logger.info("  Create a character device driver that also exposes an internal value (for example, a counter) via a /proc filesystem entry.")
    logger.info("Scenario 5 (Generic Kernel Module): hello_module.c")
    logger.info("  Generate a simple 'Hello World' Linux kernel module (not a device driver) that prints a message to the kernel log on module load and unload. It should not interact with any hardware devices.")
    logger.info("----------------------------------------------------------------------------------------------------")
    logger.info(f"\nPress Enter once your '{AI_OUTPUT_FILENAME}' file is placed in '{DRIVERS_TO_EVALUATE_DIR}/'.")
    input("Waiting for your input... ") # Keep input() as it's a direct user interaction

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
                # Robust regex to match filenames (allows letters, digits, underscores, hyphens, periods, but ends with .c)
                filename_match = re.match(r'^\s*([a-zA-Z0-9_\-\.]+\.c)\s*$', line)
                
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
        logger.error(f"Error: AI output file '{file_path}' not found.")
        return []
    except Exception as e:
        logger.error(f"Error parsing AI output file: {e}", exc_info=True) # exc_info to log traceback
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

    # More specific keyword-based detection for the 5 scenarios
    if "register_chrdev" in code_content_lower or "cdev_add" in code_content_lower or "file_operations" in code_content_lower:
        if "ioctl" in code_content_lower and "mutex" in code_content_lower:
            category = 'char_device_ioctl_sync'
        elif "proc_create" in code_content_lower or "/proc/" in code_content_lower:
            category = 'char_device_procfs'
        else: # Default if char device but no specific IOCTL/ProcFS keywords
            category = 'char_device_basic_rw'
    elif "platform_driver" in code_content_lower and "probe" in code_content_lower and "remove" in code_content_lower:
        if "gpio_request_one" in code_content_lower or "request_irq" in code_content_lower:
            category = 'platform_device_gpio_irq'
        else:
            category = 'platform_device' # Fallback for a generic platform driver
    elif "hello, kernel" in code_content_lower and "goodbye, kernel" in code_content_lower:
        category = 'generic_kernel_module' # Specific for the "hello_module.c" scenario

    # Manual fallback if category is unknown or needs refinement
    if category == 'unknown':
        logger.warning(f"Could not automatically determine category for '{filename}'.")
        logger.info("Please manually select one of the following categories:")
        logger.info("1. Character Device (Basic R/W)")
        logger.info("2. Character Device (IOCTL & Concurrency)")
        logger.info("3. Platform Device (GPIO Interrupt)")
        logger.info("4. Character Device (ProcFS Entry)")
        logger.info("5. Generic Kernel Module (Hello World)")
        logger.info("6. Other/Unknown (will result in basic compilation/style check only)")

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
                logger.warning("Invalid choice. Please enter a number between 1 and 6.")
    else:
        logger.info(f"Automatically detected '{filename}' as: {category}")

    return category

def run_command(command, cwd, description, check_return=False):
    """
    Helper to run shell commands and capture output.
    """
    logger.info(f"  Running: {description} (CMD: {' '.join(command)}) in {cwd}")
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=check_return # Raises CalledProcessError if return code is non-zero
        )
        if result.returncode != 0 and not check_return: # Log error if not checked and failed
            logger.error(f"  {description} failed with exit code {result.returncode}")
        if result.stdout:
            logger.debug(f"  {description} STDOUT:\n{result.stdout.strip()}")
        if result.stderr:
            logger.debug(f"  {description} STDERR:\n{result.stderr.strip()}")
        return result.returncode, result.stdout, result.stderr
    except FileNotFoundError:
        logger.error(f"  Error: Command not found for {description}. Is it installed and in PATH?")
        return -1, "", "Command not found."
    except subprocess.CalledProcessError as e:
        logger.error(f"  {description} failed with error: {e}")
        logger.error(f"  STDOUT: {e.stdout.strip()}")
        logger.error(f"  STDERR: {e.stderr.strip()}")
        return e.returncode, e.stdout, e.stderr
    except Exception as e:
        logger.error(f"  An unexpected error occurred during {description}: {e}", exc_info=True)
        return -1, "", str(e)


def evaluate_single_driver(driver_path, output_dir, category):
    """
    Evaluates a single driver by attempting compilation, style checks, and static analysis.
    """
    driver_filename = os.path.basename(driver_path)
    driver_name_stem = os.path.splitext(driver_filename)[0]
    metrics = {
        "filename": driver_filename, # Add filename to metrics for overall reporting
        "category": category,        # Add category to metrics
        "compilation": {"success": False, "errors_count": 0, "warnings_count": 0, "output": ""},
        "style": {"warnings_count": 0, "errors_count": 0, "output": ""},
        "static_analysis": {"issues_count": 0, "output": ""},
        "functionality": {"basic_test_passed": False, "kernel_oops_detected": False}, # Still placeholder
        "overall_score": 0
    }
    logger.info(f"\n--- Evaluating Driver: {driver_filename} (Category: {category}) ---")

    # --- Step 6.1: Compilation Assessment ---
    logger.info(f"  [STEP 6.1] Compiling {driver_filename}...")
    
    # Attempt to generate compilation database with bear
    logger.info("  Attempting to generate compilation database with 'bear -- make'...")
    # Clean before building to ensure fresh compilation
    run_command(["make", "clean"], cwd=output_dir, description="make clean", check_return=False)
    bear_return_code, bear_stdout, bear_stderr = run_command(["bear", "--", "make"], cwd=output_dir, description="Bear (make)")
    
    compilation_output = ""
    compile_success = False
    compile_errors = 0
    compile_warnings = 0

    if bear_return_code == 0:
        logger.info("  'bear -- make' completed successfully. Compilation database generated.")
        # We capture output from bear run, so it contains compiler messages
        compilation_output = bear_stdout + bear_stderr
        
        # Basic parsing of compilation output for errors/warnings
        # Using more specific regex to avoid false positives from non-compiler output
        compile_errors = len(re.findall(r'^.*: error:.*$', compilation_output, re.MULTILINE | re.IGNORECASE))
        compile_warnings = len(re.findall(r'^.*: warning:.*$', compilation_output, re.MULTILINE | re.IGNORECASE))

        if compile_errors == 0:
            compile_success = True
            logger.info("  Compilation successful (no errors detected).")
        else:
            logger.error(f"  Compilation failed: {compile_errors} errors, {compile_warnings} warnings.")
    elif bear_return_code == 127: # Command 'bear' not found
        logger.warning("  'bear' command not found. Falling back to 'make' without compilation database.")
        # Fallback to plain 'make' if bear is not installed
        run_command(["make", "clean"], cwd=output_dir, description="make clean fallback", check_return=False)
        make_return_code, make_stdout, make_stderr = run_command(["make"], cwd=output_dir, description="make fallback")
        compilation_output = make_stdout + make_stderr
        
        compile_errors = len(re.findall(r'^.*: error:.*$', compilation_output, re.MULTILINE | re.IGNORECASE))
        compile_warnings = len(re.findall(r'^.*: warning:.*$', compilation_output, re.MULTILINE | re.IGNORECASE))

        if make_return_code == 0 and compile_errors == 0:
            compile_success = True
            logger.info("  Compilation successful (no errors detected).")
        else:
            logger.error(f"  Compilation failed: {compile_errors} errors, {compile_warnings} warnings.")
    else: # Other bear errors (e.g., make itself failed under bear)
        logger.error(f"  'bear -- make' failed with exit code {bear_return_code}. Check stderr for details.")
        compilation_output = bear_stdout + bear_stderr
        compile_errors = len(re.findall(r'^.*: error:.*$', compilation_output, re.MULTILINE | re.IGNORECASE))
        compile_warnings = len(re.findall(r'^.*: warning:.*$', compilation_output, re.MULTILINE | re.IGNORECASE))
        logger.error(f"  Compilation status: {compile_errors} errors, {compile_warnings} warnings.")

    metrics["compilation"]["success"] = compile_success
    metrics["compilation"]["errors_count"] = compile_errors
    metrics["compilation"]["warnings_count"] = compile_warnings
    metrics["compilation"]["output"] = compilation_output.strip()


    # --- Step 6.2: Code Style Compliance (checkpatch.pl) ---
    logger.info(f"  [STEP 6.2] Running checkpatch.pl on {driver_filename}...")
    checkpatch_command = [
        CHECKPATCH_SCRIPT,
        "--no-tree", # Important when running outside kernel source tree
        "-f",        # Treat input as a single source file
        driver_filename
    ]
    checkpatch_return_code, checkpatch_stdout, checkpatch_stderr = run_command(
        checkpatch_command, cwd=output_dir, description="checkpatch.pl"
    )

    style_warnings = 0
    style_errors = 0
    if checkpatch_return_code != -1: # -1 indicates command not found
        # checkpatch.pl uses "WARNING:" and "ERROR:"
        style_warnings = len(re.findall(r'WARNING:', checkpatch_stdout))
        style_errors = len(re.findall(r'ERROR:', checkpatch_stdout))
        logger.info(f"  Checkpatch found {style_errors} errors and {style_warnings} warnings.")
    else:
        logger.error("  Skipping checkpatch: Script not found or executable.")
    
    metrics["style"]["warnings_count"] = style_warnings
    metrics["style"]["errors_count"] = style_errors
    metrics["style"]["output"] = (checkpatch_stdout + checkpatch_stderr).strip()

    # --- Step 6.3: Deep Static Analysis (clang-tidy) ---
    logger.info(f"  [STEP 6.3] Running clang-tidy on {driver_filename}...")
    clang_tidy_issues = 0
    clang_tidy_output = ""

    # clang-tidy requires a compilation database (compile_commands.json)
    if os.path.exists(os.path.join(output_dir, "compile_commands.json")):
        clang_tidy_command = [
            "clang-tidy",
            "-p", ".", # Use compile_commands.json in current directory
            f"--checks='linuxkernel-*,bugprone-*,misc-*,readability-*,performance-*'", # Standard checks
            driver_filename
        ]
        clang_tidy_return_code, clang_tidy_stdout, clang_tidy_stderr = run_command(
            clang_tidy_command, cwd=output_dir, description="clang-tidy"
        )
        clang_tidy_output = clang_tidy_stdout + clang_tidy_stderr
        if clang_tidy_return_code != -1:
            # Clang-tidy typically outputs warnings/errors, count lines that indicate an issue
            # Look for lines starting with filename:line:column: (warning|error):
            clang_tidy_issues = len(re.findall(r'^\s*\S+:\d+:\d+:\s*(warning|error):', clang_tidy_output, re.MULTILINE | re.IGNORECASE))
            logger.info(f"  Clang-tidy found {clang_tidy_issues} issues.")
        else:
            logger.error("  Skipping clang-tidy: Command not found or executable.")
    else:
        logger.warning("  'compile_commands.json' not found. Skipping clang-tidy. Ensure 'bear' is installed and 'make' succeeds.")
    
    metrics["static_analysis"]["issues_count"] = clang_tidy_issues
    metrics["static_analysis"]["output"] = clang_tidy_output.strip()


    # --- Step 6.4: Functional Testing (Placeholder - No change from Commit 2) ---
    logger.info(f"  [STEP 6.4] Running basic functional tests on {driver_filename}...")
    metrics["functionality"]["basic_test_passed"] = True
    logger.info("  Simulated basic functional test passed.")

    # --- Step 6.5: Scoring for the Single File ---
    # More refined score calculation based on actual results
    score = 100
    if not metrics["compilation"]["success"]:
        score -= 50 # Heavy penalty for non-compiling code
        logger.warning("  Score penalty: Non-compiling code.")
    
    # Deduct based on errors and warnings from tools
    score -= metrics["compilation"]["errors_count"] * 10
    score -= metrics["compilation"]["warnings_count"] * 2
    score -= metrics["style"]["errors_count"] * 8
    score -= metrics["style"]["warnings_count"] * 3
    score -= metrics["static_analysis"]["issues_count"] * 5
    
    if metrics["functionality"]["kernel_oops_detected"]: # Still placeholder logic
        score -= 100 # Major penalty for kernel oops
        logger.warning("  Score penalty: Kernel OOPS detected.")

    metrics["overall_score"] = max(0, score) # Ensure score doesn't go below 0
    logger.info(f"  Overall Score for {driver_filename}: {metrics['overall_score']}/100")

    # Save individual file report (JSON for structured data)
    report_path_json = os.path.join(output_dir, "report.json")
    with open(report_path_json, "w") as f:
        json.dump(metrics, f, indent=4)
    logger.info(f"  Individual report saved to {report_path_json}")

    return metrics

def generate_fine_tuning_suggestions(all_results):
    """
    Generates actionable fine-tuning suggestions for the AI model based on aggregated results.
    """
    suggestions = []
    
    total_drivers = len(all_results)
    if total_drivers == 0:
        return ["No drivers evaluated. Unable to provide suggestions."]

    # Aggregate common issues
    failed_compilation_count = sum(1 for r in all_results if not r["compilation"]["success"])
    total_compile_errors = sum(r["compilation"]["errors_count"] for r in all_results)
    total_compile_warnings = sum(r["compilation"]["warnings_count"] for r in all_results)
    total_style_errors = sum(r["style"]["errors_count"] for r in all_results)
    total_style_warnings = sum(r["style"]["warnings_count"] for r in all_results)
    total_static_analysis_issues = sum(r["static_analysis"]["issues_count"] for r in all_results)

    # General suggestions
    if failed_compilation_count > 0:
        suggestions.append(f"Model frequently generates non-compiling code ({failed_compilation_count}/{total_drivers} drivers failed). Focus on:")
        if total_compile_errors > 0:
            suggestions.append(f"  - Resolving {total_compile_errors} total compilation errors. Pay close attention to undefined symbols, incorrect header includes, and mismatched function arguments for kernel APIs.")
        if total_compile_warnings > 0:
            suggestions.append(f"  - Addressing {total_compile_warnings} total compilation warnings. Warnings often indicate potential issues that could lead to errors or unexpected behavior.")
    
    if total_style_errors > 0 or total_style_warnings > 0:
        suggestions.append(f"Model needs improvement in Linux kernel coding style (total {total_style_errors} errors, {total_style_warnings} warnings from checkpatch.pl). Focus on:")
        if "LINE_LENGTH_80" in "".join(r["style"]["output"] for r in all_results): # Check for common checkpatch warning
            suggestions.append("  - Adhering to the 80-character line length limit. Ensure proper line wrapping.")
        if "BRACES" in "".join(r["style"]["output"] for r in all_results):
            suggestions.append("  - Correct brace placement (opening brace on same line as function/control statement).")
        suggestions.append("  - Reviewing variable naming conventions and proper use of spaces/tabs.")

    if total_static_analysis_issues > 0:
        suggestions.append(f"Model generates code with static analysis issues (total {total_static_analysis_issues} issues from clang-tidy). Focus on:")
        # Look for common clang-tidy issues (keywords in output)
        clang_output_combined = "".join(r["static_analysis"]["output"] for r in all_results)
        if "unhandled return value" in clang_output_combined.lower() or "NULL check" in clang_output_combined.lower():
            suggestions.append("  - Robust error handling: Ensure return values from kernel API calls (e.g., kmalloc, register_chrdev) are checked for errors and resources are properly cleaned up on failure paths.")
        if "resource leak" in clang_output_combined.lower():
            suggestions.append("  - Resource management: Ensure allocated resources (memory, IRQs, GPIOs, devices) are freed/released in all exit paths, especially in module_exit and error handlers.")
        if "concurrency" in clang_output_combined.lower() or "race condition" in clang_output_combined.lower():
             suggestions.append("  - Concurrency safety: Pay attention to race conditions and ensure shared data structures are protected with appropriate locking mechanisms (e.g., mutexes, spinlocks).")
        else:
            suggestions.append("  - General code correctness and maintainability based on static analysis warnings.")

    if failed_compilation_count == 0 and total_style_errors == 0 and total_static_analysis_issues == 0:
        suggestions.append("Excellent! The AI model produced a batch of drivers with no compilation errors, style errors, or major static analysis issues detected by automated tools. Consider increasing scenario complexity or focusing on functional correctness.")

    return suggestions


# --- Main Execution Flow ---
if __name__ == "__main__":
    overall_model_scores = []
    all_driver_results = [] # Store all detailed metrics for later use

    # Part 1: Setup & Code Generation (User-Driven, Guided by Script)
    setup_evaluation_run_dirs()

    # Create a unique timestamped directory for the current evaluation run
    timestamp = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
    current_run_dir = os.path.join(BASE_EVAL_DIR, timestamp)
    os.makedirs(current_run_dir, exist_ok=True)
    logger.info(f"Created evaluation run directory: {current_run_dir}")

    # Print instructions and wait for user to place the AI output file
    print_ai_prompt_instructions(current_run_dir)

    ai_output_file_path = os.path.join(DRIVERS_TO_EVALUATE_DIR, AI_OUTPUT_FILENAME)

    # Check if the AI output file exists before parsing
    if not os.path.exists(ai_output_file_path):
        logger.error(f"Error: The expected AI output file '{ai_output_file_path}' was not found.")
        logger.error("Please ensure you have placed the AI's response correctly and try again.")
        exit(1)

    # Parse the single AI output file into individual driver code blocks
    logger.info(f"\nParsing '{AI_OUTPUT_FILENAME}' for individual driver code blocks...")
    parsed_drivers = parse_ai_output_file(ai_output_file_path)

    if not parsed_drivers:
        logger.error("No driver code blocks found in the AI output file. Exiting.")
        exit(1)

    logger.info(f"Found {len(parsed_drivers)} driver code blocks.")

    # Part 2: Automated Evaluation of Each File
    for driver_info in parsed_drivers:
        driver_filename = driver_info['filename']
        driver_code_content = driver_info['code_content']

        # Create a sub-directory for this specific file's evaluation results
        file_eval_dir = os.path.join(current_run_dir, "results", os.path.splitext(driver_filename)[0])
        os.makedirs(file_eval_dir, exist_ok=True)
        logger.info(f"\nProcessing '{driver_filename}' in: {file_eval_dir}")

        # Copy the .c file into its specific evaluation directory
        driver_target_path = os.path.join(file_eval_dir, driver_filename)
        with open(driver_target_path, "w") as f:
            f.write(driver_code_content)
        logger.info(f"  Copied '{driver_filename}' to its evaluation directory.")

        # Copy and modify the template Makefile
        makefile_target_path = os.path.join(file_eval_dir, "Makefile")
        try:
            with open(TEMPLATE_MAKEFILE, 'r') as tmpl_f:
                makefile_content = tmpl_f.read()
            makefile_content = make_content.replace("$(DRIVER_NAME)", os.path.splitext(driver_filename)[0])
            with open(makefile_target_path, "w") as mf:
                mf.write(makefile_content)
            logger.info(f"  Created Makefile for '{driver_filename}'.")
        except FileNotFoundError:
            logger.error(f"Error: Template Makefile '{TEMPLATE_MAKEFILE}' not found. Please ensure it exists.")
            exit(1)
        except Exception as e:
            logger.error(f"Error creating Makefile for '{driver_filename}': {e}", exc_info=True)
            exit(1)


        # Determine Driver Category
        final_category = determine_driver_category(driver_code_content, driver_filename)

        # Execute Category-Specific Evaluation Function
        file_metrics = evaluate_single_driver(driver_target_path, file_eval_dir, final_category)
        all_driver_results.append(file_metrics)
        overall_model_scores.append(file_metrics["overall_score"])

    # Part 3: Overall Model Evaluation & Reporting
    logger.info(f"\n--- Overall AI Model Evaluation ---")
    if overall_model_scores:
        overall_model_average_score = sum(overall_model_scores) / len(overall_model_scores)
        logger.info(f"Average Score Across All Drivers: {overall_model_average_score:.2f}/100")

        # Generate and print fine-tuning suggestions
        logger.info("\n--- Model Fine-tuning Suggestions ---")
        suggestions = generate_fine_tuning_suggestions(all_driver_results)
        for s in suggestions:
            logger.info(f"- {s}")

        # Save comprehensive summary report to JSON
        summary_report_path = os.path.join(current_run_dir, "summary_report.json")
        summary_data = {
            "timestamp": timestamp,
            "overall_average_score": overall_model_average_score,
            "fine_tuning_suggestions": suggestions,
            "individual_driver_results": all_driver_results
        }
        with open(summary_report_path, "w") as f:
            json.dump(summary_data, f, indent=4)
        logger.info(f"\nComprehensive summary report saved to: {summary_report_path}")

    else:
        logger.warning("\nNo drivers were successfully evaluated.")

    logger.info("\nEvaluation complete!")
