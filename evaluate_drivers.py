import os
import shutil
import datetime
import re
import subprocess
import logging
import json

# --- Configuration ---
# Base directory for all evaluation runs
BASE_EVAL_DIR = "eval_runs"
# Directory where the user places AI-generated drivers for evaluation
DRIVERS_TO_EVALUATE_DIR = "drivers_to_evaluate"
# Name of the single file expected from the AI model containing all drivers
AI_OUTPUT_FILENAME = "ai_generated_drivers.txt"
# Path to the template Makefile
TEMPLATE_MAKEFILE = "template_Makefile"

# Path to the checkpatch.pl script - IMPROVED LOGIC
# Auto-detect checkpatch.pl if not defined
CHECKPATCH_SCRIPT = shutil.which("checkpatch.pl")
# If not found in PATH, try common kernel source paths (adjust these for your system)
if not CHECKPATCH_SCRIPT:
    # Common kernel source paths for checkpatch.pl
    possible_paths = [
        "/usr/src/linux/scripts/checkpatch.pl",
        "/usr/src/linux-headers-*/scripts/checkpatch.pl", # For Ubuntu/Debian
        os.path.expanduser("~/linux/scripts/checkpatch.pl"),
        os.path.expanduser("~/kernel/scripts/checkpatch.pl"),
    ]
    for path in possible_paths:
        # Use glob to handle wildcards like linux-headers-*
        import glob
        found_paths = glob.glob(path)
        if found_paths:
            CHECKPATCH_SCRIPT = found_paths[0] # Take the first match
            break

# Define the expected order and mapping of scenarios for parsing and category assignment
SCENARIO_MAP = [
    {"tag": "char_rw", "filename": "char_rw.c", "category": "char_device_basic_rw"},
    {"tag": "char_ioctl_sync", "filename": "char_ioctl_sync.c", "category": "char_device_ioctl_sync"},
    {"tag": "platform_gpio_irq", "filename": "platform_gpio_irq.c", "category": "platform_device_gpio_irq"},
    {"tag": "char_procfs", "filename": "char_procfs.c", "category": "char_device_procfs"},
    {"tag": "hello_module", "filename": "hello_module.c", "category": "generic_kernel_module"}
]

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler()
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
    Refined instructions to help the user generate better formatted AI output for easier parsing.
    """
    print("\n" + "="*80)
    print("                      Linux Device Driver AI Evaluation System")
    print("="*80)
    print("Step 1: Prompt your AI model with the following:")
    print("\n--- AI PROMPT TO USE (Copy-Paste and Modify as needed) ---")
    print("Generate exactly 5 distinct Linux kernel modules in C, each representing one scenario described below.")
    print("Each module's code block should be explicitly delimited by comments of the format:")
    print("    // START:<unique_scenario_tag>")
    print("    // ... C code for the module ...")
    print("    // END:<same_tag>")
    print("Do NOT include file name comments or excessive text between modules. Ensure NO Markdown fences (` ```c `) are used.")
    print("Adhere strictly to Linux kernel coding standards (e.g., 80-char line limit, tab indentation, specific brace style).")
    print("Ensure robust error handling for all kernel API calls.")
    print("Ensure all allocated resources are properly freed in error paths and the module exit function.")
    print("Include necessary printk messages at KERN_INFO level for module load and unload events, precisely matching the specified strings below.")
    print("List the modules in this exact order:")

    # Detailed instructions for each scenario, matching SCENARIO_MAP order
    print("\n1. char_rw.c (Scenario Tag: char_rw)")
    print("    * A basic character device driver that supports read and write operations.")
    print("    * Required printk on load: \"char_rw: device registered\"")
    print("    * Required printk on unload: \"char_rw: device unregistered\"")

    print("\n2. char_ioctl_sync.c (Scenario Tag: char_ioctl_sync)")
    print("    * A character device driver that demonstrates `ioctl` with synchronous operations.")
    print("    * Required printk on load: \"char_ioctl_sync: device registered\"")
    print("    * Required printk on unload: \"char_ioctl_sync: device unregistered\"")

    print("\n3. platform_gpio_irq.c (Scenario Tag: platform_gpio_irq)")
    print("    * A platform device driver that interacts with GPIOs and handles interrupts (e.g., simple button press).")
    print("    * Required printk on load: \"platform_gpio_irq: platform driver loaded\"")
    print("    * Required printk on unload: \"platform_gpio_irq: platform driver unloaded\"")
    print("    * CRITICAL GUIDELINES for successful compilation and execution:")
    print("        - MUST use modern GPIO descriptor API: `devm_gpiod_get()` and `gpiod_to_irq()`")
    print("        - DO NOT use deprecated functions like `of_get_named_gpio()` or legacy `gpio_*()` APIs")
    print("        - Must support Device Tree via `of_match_table` and use `irq-gpios` phandle in DT")
    print("        - Ensure `platform_probe()` returns `int`, and `platform_remove()` returns `int` or `void`")
    print("        - Use `devm_request_irq()` or `devm_request_threaded_irq()` for IRQ handling")
    print("        - Handle all failure paths robustly with proper cleanup")
    print("        - Add meaningful `dev_info()` or `pr_info()` log messages for load/unload")
    print("        - Comply with kernel 6.x+ style and API standards to avoid implicit declarations or warnings")


    print("\n4. char_procfs.c (Scenario Tag: char_procfs)")
    print("    * A character device driver that exposes information or allows control via a procfs entry.")
    print("    * Required printk on load: \"char_procfs: procfs entry created\"")
    print("    * Required printk on unload: \"char_procfs: procfs entry removed\"")
    print("    * Important: Use the modern `proc_ops` structure for procfs operations.")

    print("\n5. hello_module.c (Scenario Tag: hello_module)")
    print("    * A very basic \"Hello World\" kernel module.")
    print("    * Required printk on load: \"hello_module: Hello World!\"")
    print("    * Required printk on unload: \"hello_module: Goodbye, World!\"")
    
    print("\n--- END AI PROMPT ---")
    
    print("\nStep 2: Once you have the AI's complete response, copy the ENTIRE response ")
    print(f"and paste it into a single file named '{AI_OUTPUT_FILENAME}' in the following directory:")
    print(f"  {DRIVERS_TO_EVALUATE_DIR}/")
    print("\nStep 3: Functional testing involves loading kernel modules. This requires 'sudo' privileges.")
    print(f"A buggy module could potentially destabilize your VM's kernel. Proceed with caution.")
    print(f"\nStep 4: Press Enter here to begin evaluation...")
    input("Waiting for your input... ")


def parse_ai_output_file(file_path):
    """
    Parses a single file containing multiple AI-generated C code blocks,
    delimited by // START:<tag> and // END:<tag> comments.
    Assigns filenames and categories based on SCENARIO_MAP order.

    Args:
        file_path (str): The path to the single file containing AI output.

    Returns:
        list: A list of dictionaries, where each dict is {'filename': str, 'code_content': str, 'category': str}.
    """
    drivers_data = []
    current_tag = None
    current_code_lines = []
    
    # Regex for START and END tags
    start_tag_re = re.compile(r'^\s*//\s*START:([a-zA-Z0-9_\-]+)\s*$')
    end_tag_re = re.compile(r'^\s*//\s*END:([a-zA-Z0-9_\-]+)\s*$')

    try:
        with open(file_path, 'r') as f:
            lines = f.readlines()

        scenario_index = 0
        i = 0
        while i < len(lines):
            line = lines[i]
            start_match = start_tag_re.match(line)
            end_match = end_tag_re.match(line)

            if start_match:
                current_tag = start_match.group(1)
                current_code_lines = []
                logger.debug(f"Found START tag: {current_tag}")
                i += 1 # Move past the START tag
                continue
            
            if end_match:
                matched_tag = end_match.group(1)
                logger.debug(f"Found END tag: {matched_tag}")
                if current_tag and current_tag == matched_tag:
                    if scenario_index < len(SCENARIO_MAP):
                        expected_scenario = SCENARIO_MAP[scenario_index]
                        if current_tag == expected_scenario["tag"]:
                            drivers_data.append({
                                'filename': expected_scenario["filename"],
                                'code_content': "".join(current_code_lines).strip(),
                                'category': expected_scenario["category"]
                            })
                            logger.info(f"  Successfully parsed '{expected_scenario['filename']}' (Tag: {current_tag}).")
                            scenario_index += 1
                        else:
                            logger.error(f"  Tag mismatch for scenario {scenario_index+1}. Expected '{expected_scenario['tag']}', but found '{current_tag}'. Skipping this block.")
                    else:
                        logger.warning(f"  Found more driver blocks than expected. Skipping extra block with tag '{current_tag}'.")
                    current_tag = None
                    current_code_lines = []
                else:
                    logger.warning(f"  Mismatched END tag '{matched_tag}' or no START tag found. Skipping block.")
                i += 1 # Move past the END tag
                continue
            
            if current_tag: # Only append if we are inside a defined block
                current_code_lines.append(line)
            
            i += 1

    except FileNotFoundError:
        logger.error(f"Error: AI output file '{file_path}' not found.")
        return []
    except Exception as e:
        logger.error(f"Error parsing AI output file: {e}", exc_info=True)
        return []

    # Final check: Ensure we parsed the expected number of drivers
    if len(drivers_data) != len(SCENARIO_MAP):
        logger.error(f"Expected to parse {len(SCENARIO_MAP)} drivers, but found {len(drivers_data)}. Check AI output format.")
        # Optionally, you might want to clear drivers_data here or exit,
        # but for now, we'll let it proceed with what it found.

    return drivers_data

def run_command(command, cwd, description, allow_failure=False):
    """
    Helper to run shell commands and capture output.
    Logs command details at DEBUG level for less console noise.
    `allow_failure` can be set to True if the command is expected to sometimes fail (e.g., rmmod if module not loaded).
    """
    logger.debug(f"  Running: {description} (CMD: {' '.join(command)}) in {cwd}")
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False # Always capture output and let caller decide to check return code
        )
        if result.returncode != 0 and not allow_failure:
            logger.debug(f"  {description} failed with exit code {result.returncode}")
            if result.stdout:
                logger.debug(f"  {description} STDOUT:\n{result.stdout.strip()}")
            if result.stderr:
                logger.debug(f"  {description} STDERR:\n{result.stderr.strip()}")
        elif result.returncode != 0 and allow_failure:
             logger.debug(f"  {description} failed as expected (return code {result.returncode}), STDOUT: {result.stdout.strip()}, STDERR: {result.stderr.strip()}")
        else: # Command succeeded
            if result.stdout:
                logger.debug(f"  {description} STDOUT:\n{result.stdout.strip()}")
            if result.stderr:
                logger.debug(f"  {description} STDERR:\n{result.stderr.strip()}")

        return result.returncode, result.stdout, result.stderr
    except FileNotFoundError:
        logger.error(f"  Error: Command not found for {description}. Is it installed and in PATH?")
        return -1, "", "Command not found."
    except Exception as e:
        logger.error(f"  An unexpected error occurred during {description}: {e}", exc_info=True)
        return -1, "", str(e)


def functional_test_driver(module_ko_path, module_name, output_dir, expected_load_msg=None, expected_unload_msg=None):
    """
    Attempts to load and unload a kernel module and checks dmesg for messages and oopses.

    Args:
        module_ko_path (str): Full path to the .ko file.
        module_name (str): The name of the module (e.g., "hello_module").
        output_dir (str): Directory for saving dmesg logs.
        expected_load_msg (str, optional): Message expected in dmesg on load.
        expected_unload_msg (str, optional): Message expected in dmesg on unload.

    Returns:
        dict: Test results including success, oops detection, and dmesg outputs.
    """
    logger.info(f"    Starting functional test for {module_name}.ko")
    results = {
        "load_success": False,
        "unload_success": False,
        "kernel_oops_detected": False,
        "load_dmesg": "",
        "unload_dmesg": "",
        "load_msg_found": False,
        "unload_msg_found": False,
        "test_passed": False
    }

    abs_module_ko_path = os.path.abspath(module_ko_path)
    logger.info(f"    Attempting to load module using insmod at absolute path: {abs_module_ko_path}")

    if not os.path.exists(abs_module_ko_path):
        logger.error(f"    .ko file NOT FOUND at runtime path: {abs_module_ko_path}. This is critical!")
        return results

    # --- Pre-check: Attempt to unload if already loaded ---
    lsmod_return_code, lsmod_stdout, _ = run_command(["lsmod"], cwd=output_dir, description="lsmod")
    if lsmod_return_code == 0 and module_name in lsmod_stdout:
        logger.warning(f"    Module {module_name} already loaded. Attempting to unload...")
        rmmod_return_code, _, rmmod_stderr = run_command(
            ["sudo", "rmmod", module_name], cwd=output_dir,
            description=f"Pre-emptive rmmod {module_name}", allow_failure=True
        )
        if rmmod_return_code != 0:
            logger.error(f"    Pre-emptive rmmod failed: {rmmod_stderr.strip()}")
        else:
            logger.info(f"    Pre-emptive rmmod successful.")

    # Clear dmesg
    run_command(["sudo", "dmesg", "-c"], cwd=output_dir, description="Clear dmesg")

    # --- Load the module ---
    logger.info(f"    Attempting to load module: {module_name}.ko")
    load_return_code, load_stdout, load_stderr = run_command(
        ["sudo", "insmod", abs_module_ko_path],
        cwd=output_dir,
        description=f"insmod {module_name}.ko"
    )

    if load_stdout:
        logger.debug(f"    insmod stdout:\n{load_stdout.strip()}")
    if load_stderr:
        logger.error(f"    insmod stderr:\n{load_stderr.strip()}")

    _, dmesg_after_load, _ = run_command(["sudo", "dmesg"], cwd=output_dir, description="dmesg after load")
    results["load_dmesg"] = dmesg_after_load

    failure_indicators = [
        r'insmod: ERROR:',
        r'No such file or directory',
        r'Invalid module format',
        r'unresolved symbol',
        r'Unknown symbol',
        r'kernel panic',
        r'oops',
        r'tainted'
    ]
    failure_detected = any(re.search(pattern, dmesg_after_load, re.IGNORECASE) for pattern in failure_indicators)

    if load_return_code == 0 and not failure_detected:
        results["load_success"] = True
        logger.info(f"    Module {module_name}.ko loaded successfully.")
    else:
        logger.error(f"    Module {module_name}.ko failed to load properly.")
        logger.debug(f"    Full dmesg after load:\n{dmesg_after_load}")
        if load_return_code != 0:
            _, recent_dmesg, _ = run_command(["sudo", "dmesg", "-t"], cwd=output_dir, description="dmesg after failed load")
            results["load_dmesg"] += "\n--- Recent dmesg after failed load ---\n" + recent_dmesg
            logger.error(f"    Recent dmesg output:\n{recent_dmesg.strip()}")

    if re.search(r'kernel (panic|oops|bug):', dmesg_after_load, re.IGNORECASE):
        results["kernel_oops_detected"] = True
        logger.error(f"    !!!!! KERNEL OOPS DETECTED AFTER LOADING {module_name}.ko !!!!!")

    if expected_load_msg:
        if re.search(re.escape(expected_load_msg), dmesg_after_load, re.IGNORECASE):
            results["load_msg_found"] = True
            logger.info(f"    Expected load message found: '{expected_load_msg}'")
        else:
            logger.warning(f"    Expected load message NOT found: '{expected_load_msg}'")
            logger.debug(dmesg_after_load[-1000:])

    with open(os.path.join(output_dir, f"{module_name}_dmesg_load.log"), "w") as f:
        f.write(dmesg_after_load)

    # --- Unload ---
    if results["load_success"] and not results["kernel_oops_detected"]:
        run_command(["sudo", "dmesg", "-c"], cwd=output_dir, description="Clear dmesg before unload")

        logger.info(f"    Attempting to unload module: {module_name}")
        unload_return_code, _, unload_stderr = run_command(
            ["sudo", "rmmod", module_name], cwd=output_dir, description=f"rmmod {module_name}"
        )

        _, dmesg_after_unload, _ = run_command(["sudo", "dmesg"], cwd=output_dir, description="dmesg after unload")
        results["unload_dmesg"] = dmesg_after_unload

        if unload_return_code == 0:
            if not re.search(r'rmmod: ERROR:|fail|error|Device or resource busy', dmesg_after_unload, re.IGNORECASE):
                results["unload_success"] = True
                logger.info(f"    Module {module_name} unloaded successfully.")
            else:
                logger.error(f"    rmmod returned 0 but dmesg shows problems.")
        else:
            logger.error(f"    Failed to unload module {module_name}: {unload_stderr.strip()}")

        if re.search(r'kernel (panic|oops|bug):', dmesg_after_unload, re.IGNORECASE):
            results["kernel_oops_detected"] = True
            logger.error(f"    !!!!! KERNEL OOPS DETECTED AFTER UNLOADING {module_name}.ko !!!!!")

        if expected_unload_msg:
            if re.search(re.escape(expected_unload_msg), dmesg_after_unload, re.IGNORECASE):
                results["unload_msg_found"] = True
                logger.info(f"    Expected unload message found: '{expected_unload_msg}'")
            else:
                logger.warning(f"    Expected unload message NOT found: '{expected_unload_msg}'")
                logger.debug(dmesg_after_unload[-1000:])

        with open(os.path.join(output_dir, f"{module_name}_dmesg_unload.log"), "w") as f:
            f.write(dmesg_after_unload)
    else:
        logger.warning("    Skipping unload due to load failure or detected oops.")
        run_command(["sudo", "rmmod", module_name], cwd=output_dir, description=f"Final cleanup rmmod {module_name}", allow_failure=True)

    results["test_passed"] = (
        results["load_success"]
        and results["unload_success"]
        and not results["kernel_oops_detected"]
        and (not expected_load_msg or results["load_msg_found"])
        and (not expected_unload_msg or results["unload_msg_found"])
    )

    logger.info(f"    Functional test overall result for {module_name}.ko: {'PASS' if results['test_passed'] else 'FAIL'}")
    return results


def evaluate_char_rw_driver(driver_path, output_dir, category):
    """
    Evaluates a char_device_basic_rw driver.
    Handles compilation, style checks, static analysis, and functional tests.
    """
    driver_filename = os.path.basename(driver_path)
    driver_name_stem = os.path.splitext(driver_filename)[0]
    module_ko_path = os.path.join(output_dir, f"{driver_name_stem}.ko")

    metrics = {
        "filename": driver_filename,
        "category": category,
        "compilation": {"success": False, "errors_count": 0, "warnings_count": 0, "output": ""},
        "style": {"warnings_count": 0, "errors_count": 0, "output": ""},
        "static_analysis": {"issues_count": 0, "output": ""},
        "functionality": {
            "test_attempted": False, "load_success": False, "unload_success": False,
            "kernel_oops_detected": False, "load_msg_found": False, "unload_msg_found": False,
            "test_passed": False, "dmesg_output_load": "", "dmesg_output_unload": ""
        },
        "overall_score": 0
    }
    logger.info(f"\n--- Evaluating Driver: {driver_filename} (Category: {category}) ---")

    # Corrected expected messages for char_rw driver to match AI prompt and functional test
    expected_load_msg = f"{driver_name_stem}: device registered"
    expected_unload_msg = f"{driver_name_stem}: device unregistered"


    # --- Step 6.1: Compilation Assessment ---
    logger.info(f"  [STEP 6.1] Compiling {driver_filename}...")
    
    run_command(["make", "clean"], cwd=output_dir, description="make clean")
    
    bear_return_code, bear_stdout, bear_stderr = run_command(["bear", "--", "make"], cwd=output_dir, description="Bear (make)")
    compilation_output = bear_stdout + bear_stderr
    
    if bear_return_code == -1:
        logger.warning("  'bear' command not found. Falling back to 'make' without compilation database.")
        make_return_code, make_stdout, make_stderr = run_command(["make"], cwd=output_dir, description="make fallback")
        compilation_output = make_stdout + make_stderr
        final_make_return_code = make_return_code
    else:
        final_make_return_code = bear_return_code

    compile_errors = len(re.findall(r'^(?!.*warning:.*$).*:\s*(error|fatal error):.*$', compilation_output, re.MULTILINE | re.IGNORECASE))
    compile_warnings = len(re.findall(r'^\s*.*:\d+:\d+:\s*warning:.*$', compilation_output, re.MULTILINE | re.IGNORECASE))

    metrics["compilation"]["errors_count"] = compile_errors
    metrics["compilation"]["warnings_count"] = compile_warnings
    metrics["compilation"]["output"] = compilation_output.strip()

    logger.info(f"  Expected .ko path: {module_ko_path}")
    logger.info(f"  Checking if .ko file exists after compilation command: {os.path.exists(module_ko_path)}")
    try:
        logger.info(f"  Files in output_dir after make: {os.listdir(output_dir)}")
    except OSError as e:
        logger.error(f"  Could not list directory {output_dir}: {e}")

    if final_make_return_code == 0 and compile_errors == 0:
        if os.path.exists(module_ko_path):
            metrics["compilation"]["success"] = True
            logger.info("  Compilation successful (no errors detected, .ko generated).")
        else:
            logger.error("  Compilation reported success (exit 0, no errors in output), but .ko file is missing!")
            logger.error(f"  Expected .ko at: {module_ko_path}. Directory contents: {os.listdir(output_dir)}")
            metrics["compilation"]["success"] = False
    else:
        logger.error(f"  Compilation failed: Make exit code {final_make_return_code}, Errors in output {compile_errors}.")
        logger.debug(f"  Full Compilation Output:\n{compilation_output.strip()}")


    # --- Step 6.2: Code Style Compliance (checkpatch.pl) ---
    logger.info(f"  [STEP 6.2] Running checkpatch.pl on {driver_filename}...")
    
    style_warnings = 0
    style_errors = 0

    if CHECKPATCH_SCRIPT and os.path.exists(CHECKPATCH_SCRIPT) and os.access(CHECKPATCH_SCRIPT, os.X_OK): # Check if executable
        checkpatch_command = [CHECKPATCH_SCRIPT, "--no-tree", "-f", driver_filename]
        checkpatch_return_code, checkpatch_stdout, checkpatch_stderr = run_command(
            checkpatch_command, cwd=output_dir, description="checkpatch.pl"
        )

        style_warnings = len(re.findall(r'WARNING:', checkpatch_stdout))
        style_errors = len(re.findall(r'ERROR:', checkpatch_stdout))
        logger.info(f"  Checkpatch found {style_errors} errors and {style_warnings} warnings.")
        metrics["style"]["output"] = (checkpatch_stdout + checkpatch_stderr).strip()
    else:
        logger.error(f"  Error: checkpatch.pl not found or not executable at '{CHECKPATCH_SCRIPT}'. Is it installed and in PATH? You might need to 'chmod +x {CHECKPATCH_SCRIPT}' if it exists.")
        logger.error("  Skipping checkpatch: Script not found or executable.")
    
    metrics["style"]["warnings_count"] = style_warnings
    metrics["style"]["errors_count"] = style_errors


    # --- Step 6.3: Deep Static Analysis (clang-tidy) ---
    logger.info(f"  [STEP 6.3] Running clang-tidy on {driver_filename}...")
    clang_tidy_issues = 0
    clang_tidy_output = ""

    if os.path.exists(os.path.join(output_dir, "compile_commands.json")):
        clang_tidy_command = [
            "clang-tidy",
            "-p", ".",
            f"--checks='linuxkernel-*,bugprone-*,misc-*,readability-*,performance-*'",
            "-system-headers=false",
            driver_filename
        ]
        clang_tidy_return_code, clang_tidy_stdout, clang_tidy_stderr = run_command(
            clang_tidy_command, cwd=output_dir, description="clang-tidy"
        )
        clang_tidy_output = clang_tidy_stdout + clang_tidy_stderr
        clang_tidy_issues = len(re.findall(r'^\s*\S+:\d+:\d+:\s*(warning|error):', clang_tidy_output, re.MULTILINE | re.IGNORECASE))
        logger.info(f"  Clang-tidy found {clang_tidy_issues} issues.")
    else:
        logger.warning("  'compile_commands.json' not found. Skipping clang-tidy. Ensure 'bear' is installed and 'make' succeeds.")
    
    metrics["static_analysis"]["issues_count"] = clang_tidy_issues
    metrics["static_analysis"]["output"] = clang_tidy_output.strip()


    # --- Step 6.4: Functional Testing ---
    logger.info(f"  [STEP 6.4] Running functional tests on {driver_filename}...")
    metrics["functionality"]["test_attempted"] = True

    if metrics["compilation"]["success"] and os.path.exists(module_ko_path):
        functional_results = functional_test_driver(
            module_ko_path,
            driver_name_stem,
            output_dir,
            expected_load_msg,
            expected_unload_msg
        )
        metrics["functionality"].update(functional_results)
    else:
        logger.warning("  Skipping functional testing: Module did not compile successfully or .ko file missing.")
        if not os.path.exists(module_ko_path):
            logger.warning("  Score penalty: Functional test skipped because .ko file was not truly available for `insmod`.")
            metrics["functionality"]["load_success"] = False
        else:
            logger.warning("  Score penalty: Functional test not attempted (due to compilation issues).")


    # --- Step 6.5: Calculate Detailed and Overall Scores ---
    detailed_metrics = {
        "correctness": {
            "weight": 0.4,
            "compilation_success": 0.0,
            "functionality_pass": 0.0,
            "kernel_api_usage": 1.0 
        },
        "security_safety": {
            "weight": 0.25,
            "memory_safety": 1.0, 
            "resource_management": 1.0, 
            "race_conditions": 1.0, 
            "input_validation": 1.0 
        },
        "code_quality": {
            "weight": 0.2,
            "style_compliance": 1.0, 
            "error_handling": 1.0, 
            "documentation": 0.7, 
            "maintainability": 0.8 
        },
        "performance": {
            "weight": 0.1,
            "efficiency": 0.75, 
            "scalability": 0.6, 
            "memory_usage": 0.75 
        },
        "advanced_features": {
            "weight": 0.05,
            "power_management": 0.5, 
            "device_tree_support": 0.4, 
            "debug_support": 0.9 
        }
    }

    # --- Populate Correctness Scores ---
    detailed_metrics["correctness"]["compilation_success"] = 1.0 if metrics["compilation"]["success"] else 0.0
    detailed_metrics["correctness"]["functionality_pass"] = 1.0 if metrics["functionality"]["test_passed"] else 0.0

    api_misuse_penalty = 0
    api_misuse_issues = len(re.findall(r'linuxkernel-.*:', metrics["static_analysis"]["output"], re.IGNORECASE | re.MULTILINE))
    api_misuse_penalty += api_misuse_issues * 0.05 
    detailed_metrics["correctness"]["kernel_api_usage"] = max(0.0, 1.0 - api_misuse_penalty)

    # --- Populate Security & Safety Scores ---
    mem_safety_penalty = 0
    mem_safety_issues = len(re.findall(r'bugprone-(null-dereference|use-after-free|double-free)|clang-analyzer-security.insecureAPI\.memcpy|memory leak', metrics["static_analysis"]["output"], re.IGNORECASE | re.MULTILINE))
    mem_safety_penalty += mem_safety_issues * 0.05
    detailed_metrics["security_safety"]["memory_safety"] = max(0.0, 1.0 - mem_safety_penalty)

    resource_mgmt_penalty = 0
    resource_mgmt_issues = len(re.findall(r'resource leak|unhandled return value', metrics["static_analysis"]["output"], re.IGNORECASE | re.MULTILINE))
    resource_mgmt_penalty += resource_mgmt_issues * 0.05
    detailed_metrics["security_safety"]["resource_management"] = max(0.0, 1.0 - resource_mgmt_penalty)

    race_cond_penalty = 0
    race_cond_issues = len(re.findall(r'concurrency-.*|race condition', metrics["static_analysis"]["output"], re.IGNORECASE | re.MULTILINE)) 
    race_cond_penalty += race_cond_issues * 0.05
    detailed_metrics["security_safety"]["race_conditions"] = max(0.0, 1.0 - race_cond_penalty)

    input_val_penalty = 0
    input_val_issues = len(re.findall(r'clang-analyzer-security.insecureAPI|buffer-overflow|bounds check', metrics["static_analysis"]["output"], re.IGNORECASE | re.MULTILINE))
    input_val_penalty += input_val_issues * 0.05
    detailed_metrics["security_safety"]["input_validation"] = max(0.0, 1.0 - input_val_penalty)


    # --- Populate Code Quality Scores ---
    style_compliance_score = 1.0
    if CHECKPATCH_SCRIPT and os.path.exists(CHECKPATCH_SCRIPT) and os.access(CHECKPATCH_SCRIPT, os.X_OK):
        style_compliance_score -= (metrics["style"]["errors_count"] * 0.01) # Example penalty
        style_compliance_score -= (metrics["style"]["warnings_count"] * 0.005) # Example penalty
    detailed_metrics["code_quality"]["style_compliance"] = max(0.0, style_compliance_score)

    error_handling_score = 1.0
    error_handling_score -= (metrics["compilation"]["warnings_count"] * 0.005)
    error_handling_issues = len(re.findall(r'error handling|return value ignored', metrics["static_analysis"]["output"], re.IGNORECASE | re.MULTILINE)) 
    error_handling_score -= error_handling_issues * 0.02
    detailed_metrics["code_quality"]["error_handling"] = max(0.0, error_handling_score)

    # Documentation and Maintainability are largely subjective/require more advanced tools. Keeping defaults.


    # --- Calculate Overall Score based on new weighted metrics ---
    overall_score_sum = 0
    for category_name, category_data in detailed_metrics.items():
        if category_name in ["overall_score"]: 
            continue 

        weight = category_data.get("weight", 0)
        category_sub_score_sum = 0
        sub_criteria_count = 0
        
        for key, value in category_data.items():
            if key != "weight": 
                category_sub_score_sum += value
                sub_criteria_count += 1
        
        if sub_criteria_count > 0:
            overall_score_sum += (category_sub_score_sum / sub_criteria_count) * weight
        else:
            logger.warning(f"Category '{category_name}' has no sub-criteria for scoring. Check detailed_metrics definition.")

    final_calculated_score = overall_score_sum * 100
    detailed_metrics["overall_score"] = round(final_calculated_score, 2)

    metrics["detailed_scores"] = detailed_metrics
    metrics["overall_score"] = detailed_metrics["overall_score"]

    logger.info(f"  Overall Score for {driver_filename}: {metrics['overall_score']}/100")

    report_path_json = os.path.join(output_dir, "report.json")
    with open(report_path_json, "w") as f:
        json.dump(metrics, f, indent=4)
    logger.info(f"  Individual report saved to {report_path_json}")

    return metrics




def evaluate_char_ioctl_sync_driver(driver_path, output_dir, category):
    """
    Evaluates a char_device_ioctl driver.
    Handles compilation, style checks, static analysis, and functional tests.
    """
    driver_filename = os.path.basename(driver_path)
    driver_name_stem = os.path.splitext(driver_filename)[0]
    module_ko_path = os.path.join(output_dir, f"{driver_name_stem}.ko")

    metrics = {
        "filename": driver_filename,
        "category": category,
        "compilation": {"success": False, "errors_count": 0, "warnings_count": 0, "output": ""},
        "style": {"warnings_count": 0, "errors_count": 0, "output": ""},
        "static_analysis": {"issues_count": 0, "output": ""},
        "functionality": {
            "test_attempted": False, "load_success": False, "unload_success": False,
            "kernel_oops_detected": False, "load_msg_found": False, "unload_msg_found": False,
            "test_passed": False, "dmesg_output_load": "", "dmesg_output_unload": ""
        },
        "overall_score": 0
    }
    logger.info(f"\n--- Evaluating Driver: {driver_filename} (Category: {category}) ---")

    # Expected messages for char_ioctl_sync driver
    expected_load_msg = f"{driver_name_stem}: device registered"
    expected_unload_msg = f"{driver_name_stem}: device unregistered"


    # --- Step 6.1: Compilation Assessment ---
    logger.info(f"  [STEP 6.1] Compiling {driver_filename}...")
    
    run_command(["make", "clean"], cwd=output_dir, description="make clean")
    
    bear_return_code, bear_stdout, bear_stderr = run_command(["bear", "--", "make"], cwd=output_dir, description="Bear (make)")
    compilation_output = bear_stdout + bear_stderr
    
    if bear_return_code == -1:
        logger.warning("  'bear' command not found. Falling back to 'make' without compilation database.")
        make_return_code, make_stdout, make_stderr = run_command(["make"], cwd=output_dir, description="make fallback")
        compilation_output = make_stdout + make_stderr
        final_make_return_code = make_return_code
    else:
        final_make_return_code = bear_return_code

    compile_errors = len(re.findall(r'^(?!.*warning:.*$).*:\s*(error|fatal error):.*$', compilation_output, re.MULTILINE | re.IGNORECASE))
    compile_warnings = len(re.findall(r'^\s*.*:\d+:\d+:\s*warning:.*$', compilation_output, re.MULTILINE | re.IGNORECASE))

    metrics["compilation"]["errors_count"] = compile_errors
    metrics["compilation"]["warnings_count"] = compile_warnings
    metrics["compilation"]["output"] = compilation_output.strip()

    logger.info(f"  Expected .ko path: {module_ko_path}")
    logger.info(f"  Checking if .ko file exists after compilation command: {os.path.exists(module_ko_path)}")
    try:
        logger.info(f"  Files in output_dir after make: {os.listdir(output_dir)}")
    except OSError as e:
        logger.error(f"  Could not list directory {output_dir}: {e}")

    if final_make_return_code == 0 and compile_errors == 0:
        if os.path.exists(module_ko_path):
            metrics["compilation"]["success"] = True
            logger.info("  Compilation successful (no errors detected, .ko generated).")
        else:
            logger.error("  Compilation reported success (exit 0, no errors in output), but .ko file is missing!")
            logger.error(f"  Expected .ko at: {module_ko_path}. Directory contents: {os.listdir(output_dir)}")
            metrics["compilation"]["success"] = False
    else:
        logger.error(f"  Compilation failed: Make exit code {final_make_return_code}, Errors in output {compile_errors}.")
        logger.debug(f"  Full Compilation Output:\n{compilation_output.strip()}")


    # --- Step 6.2: Code Style Compliance (checkpatch.pl) ---
    logger.info(f"  [STEP 6.2] Running checkpatch.pl on {driver_filename}...")
    
    style_warnings = 0
    style_errors = 0

    if CHECKPATCH_SCRIPT and os.path.exists(CHECKPATCH_SCRIPT) and os.access(CHECKPATCH_SCRIPT, os.X_OK): # Check if executable
        checkpatch_command = [CHECKPATCH_SCRIPT, "--no-tree", "-f", driver_filename]
        checkpatch_return_code, checkpatch_stdout, checkpatch_stderr = run_command(
            checkpatch_command, cwd=output_dir, description="checkpatch.pl"
        )

        style_warnings = len(re.findall(r'WARNING:', checkpatch_stdout))
        style_errors = len(re.findall(r'ERROR:', checkpatch_stdout))
        logger.info(f"  Checkpatch found {style_errors} errors and {style_warnings} warnings.")
        metrics["style"]["output"] = (checkpatch_stdout + checkpatch_stderr).strip()
    else:
        logger.error(f"  Error: checkpatch.pl not found or not executable at '{CHECKPATCH_SCRIPT}'. Is it installed and in PATH? You might need to 'chmod +x {CHECKPATCH_SCRIPT}' if it exists.")
        logger.error("  Skipping checkpatch: Script not found or executable.")
    
    metrics["style"]["warnings_count"] = style_warnings
    metrics["style"]["errors_count"] = style_errors


    # --- Step 6.3: Deep Static Analysis (clang-tidy) ---
    logger.info(f"  [STEP 6.3] Running clang-tidy on {driver_filename}...")
    clang_tidy_issues = 0
    clang_tidy_output = ""

    if os.path.exists(os.path.join(output_dir, "compile_commands.json")):
        clang_tidy_command = [
            "clang-tidy",
            "-p", ".",
            f"--checks='linuxkernel-*,bugprone-*,misc-*,readability-*,performance-*'",
            "-system-headers=false",
            driver_filename
        ]
        clang_tidy_return_code, clang_tidy_stdout, clang_tidy_stderr = run_command(
            clang_tidy_command, cwd=output_dir, description="clang-tidy"
        )
        clang_tidy_output = clang_tidy_stdout + clang_tidy_stderr
        clang_tidy_issues = len(re.findall(r'^\s*\S+:\d+:\d+:\s*(warning|error):', clang_tidy_output, re.MULTILINE | re.IGNORECASE))
        logger.info(f"  Clang-tidy found {clang_tidy_issues} issues.")
    else:
        logger.warning("  'compile_commands.json' not found. Skipping clang-tidy. Ensure 'bear' is installed and 'make' succeeds.")
    
    metrics["static_analysis"]["issues_count"] = clang_tidy_issues
    metrics["static_analysis"]["output"] = clang_tidy_output.strip()


    # --- Step 6.4: Functional Testing ---
    logger.info(f"  [STEP 6.4] Running functional tests on {driver_filename}...")
    metrics["functionality"]["test_attempted"] = True

    if metrics["compilation"]["success"] and os.path.exists(module_ko_path):
        functional_results = functional_test_driver(
            module_ko_path,
            driver_name_stem,
            output_dir,
            expected_load_msg,
            expected_unload_msg
        )
        metrics["functionality"].update(functional_results)
    else:
        logger.warning("  Skipping functional testing: Module did not compile successfully or .ko file missing.")
        if not os.path.exists(module_ko_path):
            logger.warning("  Score penalty: Functional test skipped because .ko file was not truly available for `insmod`.")
            metrics["functionality"]["load_success"] = False
        else:
            logger.warning("  Score penalty: Functional test not attempted (due to compilation issues).")


    # --- Step 6.5: Calculate Detailed and Overall Scores ---
    detailed_metrics = {
        "correctness": {
            "weight": 0.4,
            "compilation_success": 0.0,
            "functionality_pass": 0.0,
            "kernel_api_usage": 1.0 
        },
        "security_safety": {
            "weight": 0.25,
            "memory_safety": 1.0, 
            "resource_management": 1.0, 
            "race_conditions": 1.0, 
            "input_validation": 1.0 
        },
        "code_quality": {
            "weight": 0.2,
            "style_compliance": 1.0, 
            "error_handling": 1.0, 
            "documentation": 0.7, 
            "maintainability": 0.8 
        },
        "performance": {
            "weight": 0.1,
            "efficiency": 0.75, 
            "scalability": 0.6, 
            "memory_usage": 0.75 
        },
        "advanced_features": {
            "weight": 0.05,
            "power_management": 0.5, 
            "device_tree_support": 0.4, 
            "debug_support": 0.9 
        }
    }

    # --- Populate Correctness Scores ---
    detailed_metrics["correctness"]["compilation_success"] = 1.0 if metrics["compilation"]["success"] else 0.0
    detailed_metrics["correctness"]["functionality_pass"] = 1.0 if metrics["functionality"]["test_passed"] else 0.0

    api_misuse_penalty = 0
    api_misuse_issues = len(re.findall(r'linuxkernel-.*:', metrics["static_analysis"]["output"], re.IGNORECASE | re.MULTILINE))
    api_misuse_penalty += api_misuse_issues * 0.05 
    detailed_metrics["correctness"]["kernel_api_usage"] = max(0.0, 1.0 - api_misuse_penalty)

    # --- Populate Security & Safety Scores ---
    mem_safety_penalty = 0
    mem_safety_issues = len(re.findall(r'bugprone-(null-dereference|use-after-free|double-free)|clang-analyzer-security.insecureAPI\.memcpy|memory leak', metrics["static_analysis"]["output"], re.IGNORECASE | re.MULTILINE))
    mem_safety_penalty += mem_safety_issues * 0.05
    detailed_metrics["security_safety"]["memory_safety"] = max(0.0, 1.0 - mem_safety_penalty)

    resource_mgmt_penalty = 0
    resource_mgmt_issues = len(re.findall(r'resource leak|unhandled return value', metrics["static_analysis"]["output"], re.IGNORECASE | re.MULTILINE))
    resource_mgmt_penalty += resource_mgmt_issues * 0.05
    detailed_metrics["security_safety"]["resource_management"] = max(0.0, 1.0 - resource_mgmt_penalty)

    race_cond_penalty = 0
    race_cond_issues = len(re.findall(r'concurrency-.*|race condition', metrics["static_analysis"]["output"], re.IGNORECASE | re.MULTILINE)) 
    race_cond_penalty += race_cond_issues * 0.05
    detailed_metrics["security_safety"]["race_conditions"] = max(0.0, 1.0 - race_cond_penalty)

    input_val_penalty = 0
    input_val_issues = len(re.findall(r'clang-analyzer-security.insecureAPI|buffer-overflow|bounds check', metrics["static_analysis"]["output"], re.IGNORECASE | re.MULTILINE))
    input_val_penalty += input_val_issues * 0.05
    detailed_metrics["security_safety"]["input_validation"] = max(0.0, 1.0 - input_val_penalty)


    # --- Populate Code Quality Scores ---
    style_compliance_score = 1.0
    if CHECKPATCH_SCRIPT and os.path.exists(CHECKPATCH_SCRIPT) and os.access(CHECKPATCH_SCRIPT, os.X_OK):
        style_compliance_score -= (metrics["style"]["errors_count"] * 0.01) # Example penalty
        style_compliance_score -= (metrics["style"]["warnings_count"] * 0.005) # Example penalty
    detailed_metrics["code_quality"]["style_compliance"] = max(0.0, style_compliance_score)

    error_handling_score = 1.0
    error_handling_score -= (metrics["compilation"]["warnings_count"] * 0.005)
    error_handling_issues = len(re.findall(r'error handling|return value ignored', metrics["static_analysis"]["output"], re.IGNORECASE | re.MULTILINE)) 
    error_handling_score -= error_handling_issues * 0.02
    detailed_metrics["code_quality"]["error_handling"] = max(0.0, error_handling_score)

    # Documentation and Maintainability are largely subjective/require more advanced tools. Keeping defaults.


    # --- Calculate Overall Score based on new weighted metrics ---
    overall_score_sum = 0
    for category_name, category_data in detailed_metrics.items():
        if category_name in ["overall_score"]: 
            continue 

        weight = category_data.get("weight", 0)
        category_sub_score_sum = 0
        sub_criteria_count = 0
        
        for key, value in category_data.items():
            if key != "weight": 
                category_sub_score_sum += value
                sub_criteria_count += 1
        
        if sub_criteria_count > 0:
            overall_score_sum += (category_sub_score_sum / sub_criteria_count) * weight
        else:
            logger.warning(f"Category '{category_name}' has no sub-criteria for scoring. Check detailed_metrics definition.")

    final_calculated_score = overall_score_sum * 100
    detailed_metrics["overall_score"] = round(final_calculated_score, 2)

    metrics["detailed_scores"] = detailed_metrics
    metrics["overall_score"] = detailed_metrics["overall_score"]

    logger.info(f"  Overall Score for {driver_filename}: {metrics['overall_score']}/100")

    report_path_json = os.path.join(output_dir, "report.json")
    with open(report_path_json, "w") as f:
        json.dump(metrics, f, indent=4)
    logger.info(f"  Individual report saved to {report_path_json}")

    return metrics
   




def evaluate_platform_gpio_irq_driver(driver_path, output_dir, category):
    """
    Evaluates a platform_driver_gpio_irq driver.
    Handles compilation, style checks, static analysis, and functional tests.
    """
    driver_filename = os.path.basename(driver_path)
    driver_name_stem = os.path.splitext(driver_filename)[0]
    module_ko_path = os.path.join(output_dir, f"{driver_name_stem}.ko")

    metrics = {
        "filename": driver_filename,
        "category": category,
        "compilation": {"success": False, "errors_count": 0, "warnings_count": 0, "output": ""},
        "style": {"warnings_count": 0, "errors_count": 0, "output": ""},
        "static_analysis": {"issues_count": 0, "output": ""},
        "functionality": {
            "test_attempted": False, "load_success": False, "unload_success": False,
            "kernel_oops_detected": False, "load_msg_found": False, "unload_msg_found": False,
            "test_passed": False, "dmesg_output_load": "", "dmesg_output_unload": ""
        },
        "overall_score": 0
    }
    logger.info(f"\n--- Evaluating Driver: {driver_filename} (Category: {category}) ---")

    # Expected messages for platform_gpio_irq driver
    # The AI should be prompted to use these specific messages.
    expected_load_msg = f"{driver_name_stem}: platform driver loaded"
    expected_unload_msg = f"{driver_name_stem}: platform driver unloaded"


    # --- Step 6.1: Compilation Assessment ---
    logger.info(f"  [STEP 6.1] Compiling {driver_filename}...")
    
    run_command(["make", "clean"], cwd=output_dir, description="make clean")
    
    bear_return_code, bear_stdout, bear_stderr = run_command(["bear", "--", "make"], cwd=output_dir, description="Bear (make)")
    compilation_output = bear_stdout + bear_stderr
    
    if bear_return_code == -1:
        logger.warning("  'bear' command not found. Falling back to 'make' without compilation database.")
        make_return_code, make_stdout, make_stderr = run_command(["make"], cwd=output_dir, description="make fallback")
        compilation_output = make_stdout + make_stderr
        final_make_return_code = make_return_code
    else:
        final_make_return_code = bear_return_code

    compile_errors = len(re.findall(r'^(?!.*warning:.*$).*:\s*(error|fatal error):.*$', compilation_output, re.MULTILINE | re.IGNORECASE))
    compile_warnings = len(re.findall(r'^\s*.*:\d+:\d+:\s*warning:.*$', compilation_output, re.MULTILINE | re.IGNORECASE))

    metrics["compilation"]["errors_count"] = compile_errors
    metrics["compilation"]["warnings_count"] = compile_warnings
    metrics["compilation"]["output"] = compilation_output.strip()

    logger.info(f"  Expected .ko path: {module_ko_path}")
    logger.info(f"  Checking if .ko file exists after compilation command: {os.path.exists(module_ko_path)}")
    try:
        logger.info(f"  Files in output_dir after make: {os.listdir(output_dir)}")
    except OSError as e:
        logger.error(f"  Could not list directory {output_dir}: {e}")

    if final_make_return_code == 0 and compile_errors == 0:
        if os.path.exists(module_ko_path):
            metrics["compilation"]["success"] = True
            logger.info("  Compilation successful (no errors detected, .ko generated).")
        else:
            logger.error("  Compilation reported success (exit 0, no errors in output), but .ko file is missing!")
            logger.error(f"  Expected .ko at: {module_ko_path}. Directory contents: {os.listdir(output_dir)}")
            metrics["compilation"]["success"] = False
    else:
        logger.error(f"  Compilation failed: Make exit code {final_make_return_code}, Errors in output {compile_errors}.")
        logger.debug(f"  Full Compilation Output:\n{compilation_output.strip()}")


    # --- Step 6.2: Code Style Compliance (checkpatch.pl) ---
    logger.info(f"  [STEP 6.2] Running checkpatch.pl on {driver_filename}...")
    
    style_warnings = 0
    style_errors = 0

    if CHECKPATCH_SCRIPT and os.path.exists(CHECKPATCH_SCRIPT) and os.access(CHECKPATCH_SCRIPT, os.X_OK): # Check if executable
        checkpatch_command = [CHECKPATCH_SCRIPT, "--no-tree", "-f", driver_filename]
        checkpatch_return_code, checkpatch_stdout, checkpatch_stderr = run_command(
            checkpatch_command, cwd=output_dir, description="checkpatch.pl"
        )

        style_warnings = len(re.findall(r'WARNING:', checkpatch_stdout))
        style_errors = len(re.findall(r'ERROR:', checkpatch_stdout))
        logger.info(f"  Checkpatch found {style_errors} errors and {style_warnings} warnings.")
        metrics["style"]["output"] = (checkpatch_stdout + checkpatch_stderr).strip()
    else:
        logger.error(f"  Error: checkpatch.pl not found or not executable at '{CHECKPATCH_SCRIPT}'. Is it installed and in PATH? You might need to 'chmod +x {CHECKPATCH_SCRIPT}' if it exists.")
        logger.error("  Skipping checkpatch: Script not found or executable.")
    
    metrics["style"]["warnings_count"] = style_warnings
    metrics["style"]["errors_count"] = style_errors


    # --- Step 6.3: Deep Static Analysis (clang-tidy) ---
    logger.info(f"  [STEP 6.3] Running clang-tidy on {driver_filename}...")
    clang_tidy_issues = 0
    clang_tidy_output = ""

    if os.path.exists(os.path.join(output_dir, "compile_commands.json")):
        clang_tidy_command = [
            "clang-tidy",
            "-p", ".",
            f"--checks='linuxkernel-*,bugprone-*,misc-*,readability-*,performance-*'",
            "-system-headers=false",
            driver_filename
        ]
        clang_tidy_return_code, clang_tidy_stdout, clang_tidy_stderr = run_command(
            clang_tidy_command, cwd=output_dir, description="clang-tidy"
        )
        clang_tidy_output = clang_tidy_stdout + clang_tidy_stderr
        clang_tidy_issues = len(re.findall(r'^\s*\S+:\d+:\d+:\s*(warning|error):', clang_tidy_output, re.MULTILINE | re.IGNORECASE))
        logger.info(f"  Clang-tidy found {clang_tidy_issues} issues.")
    else:
        logger.warning("  'compile_commands.json' not found. Skipping clang-tidy. Ensure 'bear' is installed and 'make' succeeds.")
    
    metrics["static_analysis"]["issues_count"] = clang_tidy_issues
    metrics["static_analysis"]["output"] = clang_tidy_output.strip()


    # --- Step 6.4: Functional Testing ---
    logger.info(f"  [STEP 6.4] Running functional tests on {driver_filename}...")
    metrics["functionality"]["test_attempted"] = True

    if metrics["compilation"]["success"] and os.path.exists(module_ko_path):
        functional_results = functional_test_driver(
            module_ko_path,
            driver_name_stem,
            output_dir,
            expected_load_msg,
            expected_unload_msg
        )
        metrics["functionality"].update(functional_results)
    else:
        logger.warning("  Skipping functional testing: Module did not compile successfully or .ko file missing.")
        if not os.path.exists(module_ko_path):
            logger.warning("  Score penalty: Functional test skipped because .ko file was not truly available for `insmod`.")
            metrics["functionality"]["load_success"] = False
        else:
            logger.warning("  Score penalty: Functional test not attempted (due to compilation issues).")


    # --- Step 6.5: Calculate Detailed and Overall Scores ---
    detailed_metrics = {
        "correctness": {
            "weight": 0.4,
            "compilation_success": 0.0,
            "functionality_pass": 0.0,
            "kernel_api_usage": 1.0 
        },
        "security_safety": {
            "weight": 0.25,
            "memory_safety": 1.0, 
            "resource_management": 1.0, 
            "race_conditions": 1.0, 
            "input_validation": 1.0 
        },
        "code_quality": {
            "weight": 0.2,
            "style_compliance": 1.0, 
            "error_handling": 1.0, 
            "documentation": 0.7, 
            "maintainability": 0.8 
        },
        "performance": {
            "weight": 0.1,
            "efficiency": 0.75, 
            "scalability": 0.6, 
            "memory_usage": 0.75 
        },
        "advanced_features": {
            "weight": 0.05,
            "power_management": 0.5, 
            "device_tree_support": 0.4, 
            "debug_support": 0.9 
        }
    }

    # --- Populate Correctness Scores ---
    detailed_metrics["correctness"]["compilation_success"] = 1.0 if metrics["compilation"]["success"] else 0.0
    detailed_metrics["correctness"]["functionality_pass"] = 1.0 if metrics["functionality"]["test_passed"] else 0.0

    api_misuse_penalty = 0
    api_misuse_issues = len(re.findall(r'linuxkernel-.*:', metrics["static_analysis"]["output"], re.IGNORECASE | re.MULTILINE))
    api_misuse_penalty += api_misuse_issues * 0.05 
    detailed_metrics["correctness"]["kernel_api_usage"] = max(0.0, 1.0 - api_misuse_penalty)

    # --- Populate Security & Safety Scores ---
    mem_safety_penalty = 0
    mem_safety_issues = len(re.findall(r'bugprone-(null-dereference|use-after-free|double-free)|clang-analyzer-security.insecureAPI\.memcpy|memory leak', metrics["static_analysis"]["output"], re.IGNORECASE | re.MULTILINE))
    mem_safety_penalty += mem_safety_issues * 0.05
    detailed_metrics["security_safety"]["memory_safety"] = max(0.0, 1.0 - mem_safety_penalty)

    resource_mgmt_penalty = 0
    resource_mgmt_issues = len(re.findall(r'resource leak|unhandled return value', metrics["static_analysis"]["output"], re.IGNORECASE | re.MULTILINE))
    resource_mgmt_penalty += resource_mgmt_issues * 0.05
    detailed_metrics["security_safety"]["resource_management"] = max(0.0, 1.0 - resource_mgmt_penalty)

    race_cond_penalty = 0
    race_cond_issues = len(re.findall(r'concurrency-.*|race condition', metrics["static_analysis"]["output"], re.IGNORECASE | re.MULTILINE)) 
    race_cond_penalty += race_cond_issues * 0.05
    detailed_metrics["security_safety"]["race_conditions"] = max(0.0, 1.0 - race_cond_penalty)

    input_val_penalty = 0
    input_val_issues = len(re.findall(r'clang-analyzer-security.insecureAPI|buffer-overflow|bounds check', metrics["static_analysis"]["output"], re.IGNORECASE | re.MULTILINE))
    input_val_penalty += input_val_issues * 0.05
    detailed_metrics["security_safety"]["input_validation"] = max(0.0, 1.0 - input_val_penalty)


    # --- Populate Code Quality Scores ---
    style_compliance_score = 1.0
    if CHECKPATCH_SCRIPT and os.path.exists(CHECKPATCH_SCRIPT) and os.access(CHECKPATCH_SCRIPT, os.X_OK):
        style_compliance_score -= (metrics["style"]["errors_count"] * 0.01) 
        style_compliance_score -= (metrics["style"]["warnings_count"] * 0.005) 
    detailed_metrics["code_quality"]["style_compliance"] = max(0.0, style_compliance_score)

    error_handling_score = 1.0
    error_handling_score -= (metrics["compilation"]["warnings_count"] * 0.005)
    error_handling_issues = len(re.findall(r'error handling|return value ignored', metrics["static_analysis"]["output"], re.IGNORECASE | re.MULTILINE)) 
    error_handling_score -= error_handling_issues * 0.02
    detailed_metrics["code_quality"]["error_handling"] = max(0.0, error_handling_score)

    # Documentation and Maintainability are largely subjective/require more advanced tools. Keeping defaults.


    # --- Calculate Overall Score based on new weighted metrics ---
    overall_score_sum = 0
    for category_name, category_data in detailed_metrics.items():
        if category_name in ["overall_score"]: 
            continue 

        weight = category_data.get("weight", 0)
        category_sub_score_sum = 0
        sub_criteria_count = 0
        
        for key, value in category_data.items():
            if key != "weight": 
                category_sub_score_sum += value
                sub_criteria_count += 1
        
        if sub_criteria_count > 0:
            overall_score_sum += (category_sub_score_sum / sub_criteria_count) * weight
        else:
            logger.warning(f"Category '{category_name}' has no sub-criteria for scoring. Check detailed_metrics definition.")

    final_calculated_score = overall_score_sum * 100
    detailed_metrics["overall_score"] = round(final_calculated_score, 2)

    metrics["detailed_scores"] = detailed_metrics
    metrics["overall_score"] = detailed_metrics["overall_score"]

    logger.info(f"  Overall Score for {driver_filename}: {metrics['overall_score']}/100")

    report_path_json = os.path.join(output_dir, "report.json")
    with open(report_path_json, "w") as f:
        json.dump(metrics, f, indent=4)
    logger.info(f"  Individual report saved to {report_path_json}")

    return metrics
    


def evaluate_char_procfs_driver(driver_path, output_dir, category):
    """
    Evaluates a char_device_procfs driver.
    Handles compilation, style checks, static analysis, and functional tests.
    """
    driver_filename = os.path.basename(driver_path)
    driver_name_stem = os.path.splitext(driver_filename)[0]
    module_ko_path = os.path.join(output_dir, f"{driver_name_stem}.ko")

    metrics = {
        "filename": driver_filename,
        "category": category,
        "compilation": {"success": False, "errors_count": 0, "warnings_count": 0, "output": ""},
        "style": {"warnings_count": 0, "errors_count": 0, "output": ""},
        "static_analysis": {"issues_count": 0, "output": ""},
        "functionality": {
            "test_attempted": False, "load_success": False, "unload_success": False,
            "kernel_oops_detected": False, "load_msg_found": False, "unload_msg_found": False,
            "test_passed": False, "dmesg_output_load": "", "dmesg_output_unload": ""
        },
        "overall_score": 0
    }
    logger.info(f"\n--- Evaluating Driver: {driver_filename} (Category: {category}) ---")

    # Expected messages for char_procfs driver
    # The AI should be prompted to use these specific messages.
    expected_load_msg = f"{driver_name_stem}: procfs entry created"
    expected_unload_msg = f"{driver_name_stem}: procfs entry removed"


    # --- Step 6.1: Compilation Assessment ---
    logger.info(f"  [STEP 6.1] Compiling {driver_filename}...")
    
    run_command(["make", "clean"], cwd=output_dir, description="make clean")
    
    bear_return_code, bear_stdout, bear_stderr = run_command(["bear", "--", "make"], cwd=output_dir, description="Bear (make)")
    compilation_output = bear_stdout + bear_stderr
    
    if bear_return_code == -1:
        logger.warning("  'bear' command not found. Falling back to 'make' without compilation database.")
        make_return_code, make_stdout, make_stderr = run_command(["make"], cwd=output_dir, description="make fallback")
        compilation_output = make_stdout + make_stderr
        final_make_return_code = make_return_code
    else:
        final_make_return_code = bear_return_code

    compile_errors = len(re.findall(r'^(?!.*warning:.*$).*:\s*(error|fatal error):.*$', compilation_output, re.MULTILINE | re.IGNORECASE))
    compile_warnings = len(re.findall(r'^\s*.*:\d+:\d+:\s*warning:.*$', compilation_output, re.MULTILINE | re.IGNORECASE))

    metrics["compilation"]["errors_count"] = compile_errors
    metrics["compilation"]["warnings_count"] = compile_warnings
    metrics["compilation"]["output"] = compilation_output.strip()

    logger.info(f"  Expected .ko path: {module_ko_path}")
    logger.info(f"  Checking if .ko file exists after compilation command: {os.path.exists(module_ko_path)}")
    try:
        logger.info(f"  Files in output_dir after make: {os.listdir(output_dir)}")
    except OSError as e:
        logger.error(f"  Could not list directory {output_dir}: {e}")

    if final_make_return_code == 0 and compile_errors == 0:
        if os.path.exists(module_ko_path):
            metrics["compilation"]["success"] = True
            logger.info("  Compilation successful (no errors detected, .ko generated).")
        else:
            logger.error("  Compilation reported success (exit 0, no errors in output), but .ko file is missing!")
            logger.error(f"  Expected .ko at: {module_ko_path}. Directory contents: {os.listdir(output_dir)}")
            metrics["compilation"]["success"] = False
    else:
        logger.error(f"  Compilation failed: Make exit code {final_make_return_code}, Errors in output {compile_errors}.")
        logger.debug(f"  Full Compilation Output:\n{compilation_output.strip()}")


    # --- Step 6.2: Code Style Compliance (checkpatch.pl) ---
    logger.info(f"  [STEP 6.2] Running checkpatch.pl on {driver_filename}...")
    
    style_warnings = 0
    style_errors = 0

    if CHECKPATCH_SCRIPT and os.path.exists(CHECKPATCH_SCRIPT) and os.access(CHECKPATCH_SCRIPT, os.X_OK): # Check if executable
        checkpatch_command = [CHECKPATCH_SCRIPT, "--no-tree", "-f", driver_filename]
        checkpatch_return_code, checkpatch_stdout, checkpatch_stderr = run_command(
            checkpatch_command, cwd=output_dir, description="checkpatch.pl"
        )

        style_warnings = len(re.findall(r'WARNING:', checkpatch_stdout))
        style_errors = len(re.findall(r'ERROR:', checkpatch_stdout))
        logger.info(f"  Checkpatch found {style_errors} errors and {style_warnings} warnings.")
        metrics["style"]["output"] = (checkpatch_stdout + checkpatch_stderr).strip()
    else:
        logger.error(f"  Error: checkpatch.pl not found or not executable at '{CHECKPATCH_SCRIPT}'. Is it installed and in PATH? You might need to 'chmod +x {CHECKPATCH_SCRIPT}' if it exists.")
        logger.error("  Skipping checkpatch: Script not found or executable.")
    
    metrics["style"]["warnings_count"] = style_warnings
    metrics["style"]["errors_count"] = style_errors


    # --- Step 6.3: Deep Static Analysis (clang-tidy) ---
    logger.info(f"  [STEP 6.3] Running clang-tidy on {driver_filename}...")
    clang_tidy_issues = 0
    clang_tidy_output = ""

    if os.path.exists(os.path.join(output_dir, "compile_commands.json")):
        clang_tidy_command = [
            "clang-tidy",
            "-p", ".",
            f"--checks='linuxkernel-*,bugprone-*,misc-*,readability-*,performance-*'",
            "-system-headers=false",
            driver_filename
        ]
        clang_tidy_return_code, clang_tidy_stdout, clang_tidy_stderr = run_command(
            clang_tidy_command, cwd=output_dir, description="clang-tidy"
        )
        clang_tidy_output = clang_tidy_stdout + clang_tidy_stderr
        clang_tidy_issues = len(re.findall(r'^\s*\S+:\d+:\d+:\s*(warning|error):', clang_tidy_output, re.MULTILINE | re.IGNORECASE))
        logger.info(f"  Clang-tidy found {clang_tidy_issues} issues.")
    else:
        logger.warning("  'compile_commands.json' not found. Skipping clang-tidy. Ensure 'bear' is installed and 'make' succeeds.")
    
    metrics["static_analysis"]["issues_count"] = clang_tidy_issues
    metrics["static_analysis"]["output"] = clang_tidy_output.strip()


    # --- Step 6.4: Functional Testing ---
    logger.info(f"  [STEP 6.4] Running functional tests on {driver_filename}...")
    metrics["functionality"]["test_attempted"] = True

    if metrics["compilation"]["success"] and os.path.exists(module_ko_path):
        functional_results = functional_test_driver(
            module_ko_path,
            driver_name_stem,
            output_dir,
            expected_load_msg,
            expected_unload_msg
        )
        metrics["functionality"].update(functional_results)
    else:
        logger.warning("  Skipping functional testing: Module did not compile successfully or .ko file missing.")
        if not os.path.exists(module_ko_path):
            logger.warning("  Score penalty: Functional test skipped because .ko file was not truly available for `insmod`.")
            metrics["functionality"]["load_success"] = False
        else:
            logger.warning("  Score penalty: Functional test not attempted (due to compilation issues).")


    # --- Step 6.5: Calculate Detailed and Overall Scores ---
    detailed_metrics = {
        "correctness": {
            "weight": 0.4,
            "compilation_success": 0.0,
            "functionality_pass": 0.0,
            "kernel_api_usage": 1.0 
        },
        "security_safety": {
            "weight": 0.25,
            "memory_safety": 1.0, 
            "resource_management": 1.0, 
            "race_conditions": 1.0, 
            "input_validation": 1.0 
        },
        "code_quality": {
            "weight": 0.2,
            "style_compliance": 1.0, 
            "error_handling": 1.0, 
            "documentation": 0.7, 
            "maintainability": 0.8 
        },
        "performance": {
            "weight": 0.1,
            "efficiency": 0.75, 
            "scalability": 0.6, 
            "memory_usage": 0.75 
        },
        "advanced_features": {
            "weight": 0.05,
            "power_management": 0.5, 
            "device_tree_support": 0.4, 
            "debug_support": 0.9 
        }
    }

    # --- Populate Correctness Scores ---
    detailed_metrics["correctness"]["compilation_success"] = 1.0 if metrics["compilation"]["success"] else 0.0
    detailed_metrics["correctness"]["functionality_pass"] = 1.0 if metrics["functionality"]["test_passed"] else 0.0

    api_misuse_penalty = 0
    api_misuse_issues = len(re.findall(r'linuxkernel-.*:', metrics["static_analysis"]["output"], re.IGNORECASE | re.MULTILINE))
    api_misuse_penalty += api_misuse_issues * 0.05 
    detailed_metrics["correctness"]["kernel_api_usage"] = max(0.0, 1.0 - api_misuse_penalty)

    # --- Populate Security & Safety Scores ---
    mem_safety_penalty = 0
    mem_safety_issues = len(re.findall(r'bugprone-(null-dereference|use-after-free|double-free)|clang-analyzer-security.insecureAPI\.memcpy|memory leak', metrics["static_analysis"]["output"], re.IGNORECASE | re.MULTILINE))
    mem_safety_penalty += mem_safety_issues * 0.05
    detailed_metrics["security_safety"]["memory_safety"] = max(0.0, 1.0 - mem_safety_penalty)

    resource_mgmt_penalty = 0
    resource_mgmt_issues = len(re.findall(r'resource leak|unhandled return value', metrics["static_analysis"]["output"], re.IGNORECASE | re.MULTILINE))
    resource_mgmt_penalty += resource_mgmt_issues * 0.05
    detailed_metrics["security_safety"]["resource_management"] = max(0.0, 1.0 - resource_mgmt_penalty)

    race_cond_penalty = 0
    race_cond_issues = len(re.findall(r'concurrency-.*|race condition', metrics["static_analysis"]["output"], re.IGNORECASE | re.MULTILINE)) 
    race_cond_penalty += race_cond_issues * 0.05
    detailed_metrics["security_safety"]["race_conditions"] = max(0.0, 1.0 - race_cond_penalty)

    input_val_penalty = 0
    input_val_issues = len(re.findall(r'clang-analyzer-security.insecureAPI|buffer-overflow|bounds check', metrics["static_analysis"]["output"], re.IGNORECASE | re.MULTILINE))
    input_val_penalty += input_val_issues * 0.05
    detailed_metrics["security_safety"]["input_validation"] = max(0.0, 1.0 - input_val_penalty)


    # --- Populate Code Quality Scores ---
    style_compliance_score = 1.0
    if CHECKPATCH_SCRIPT and os.path.exists(CHECKPATCH_SCRIPT) and os.access(CHECKPATCH_SCRIPT, os.X_OK):
        style_compliance_score -= (metrics["style"]["errors_count"] * 0.01) 
        style_compliance_score -= (metrics["style"]["warnings_count"] * 0.005) 
    detailed_metrics["code_quality"]["style_compliance"] = max(0.0, style_compliance_score)

    error_handling_score = 1.0
    error_handling_score -= (metrics["compilation"]["warnings_count"] * 0.005)
    error_handling_issues = len(re.findall(r'error handling|return value ignored', metrics["static_analysis"]["output"], re.IGNORECASE | re.MULTILINE)) 
    error_handling_score -= error_handling_issues * 0.02
    detailed_metrics["code_quality"]["error_handling"] = max(0.0, error_handling_score)

    # Documentation and Maintainability are largely subjective/require more advanced tools. Keeping defaults.


    # --- Calculate Overall Score based on new weighted metrics ---
    overall_score_sum = 0
    for category_name, category_data in detailed_metrics.items():
        if category_name in ["overall_score"]: 
            continue 

        weight = category_data.get("weight", 0)
        category_sub_score_sum = 0
        sub_criteria_count = 0
        
        for key, value in category_data.items():
            if key != "weight": 
                category_sub_score_sum += value
                sub_criteria_count += 1
        
        if sub_criteria_count > 0:
            overall_score_sum += (category_sub_score_sum / sub_criteria_count) * weight
        else:
            logger.warning(f"Category '{category_name}' has no sub-criteria for scoring. Check detailed_metrics definition.")

    final_calculated_score = overall_score_sum * 100
    detailed_metrics["overall_score"] = round(final_calculated_score, 2)

    metrics["detailed_scores"] = detailed_metrics
    metrics["overall_score"] = detailed_metrics["overall_score"]

    logger.info(f"  Overall Score for {driver_filename}: {metrics['overall_score']}/100")

    report_path_json = os.path.join(output_dir, "report.json")
    with open(report_path_json, "w") as f:
        json.dump(metrics, f, indent=4)
    logger.info(f"  Individual report saved to {report_path_json}")

    return metrics





def evaluate_hello_module_driver(driver_path, output_dir, category):
    """
    Evaluates a basic_kernel_module driver (like a "hello world" module).
    Handles compilation, style checks, static analysis, and functional tests.
    """
    driver_filename = os.path.basename(driver_path)
    driver_name_stem = os.path.splitext(driver_filename)[0]
    module_ko_path = os.path.join(output_dir, f"{driver_name_stem}.ko")

    metrics = {
        "filename": driver_filename,
        "category": category,
        "compilation": {"success": False, "errors_count": 0, "warnings_count": 0, "output": ""},
        "style": {"warnings_count": 0, "errors_count": 0, "output": ""},
        "static_analysis": {"issues_count": 0, "output": ""},
        "functionality": {
            "test_attempted": False, "load_success": False, "unload_success": False,
            "kernel_oops_detected": False, "load_msg_found": False, "unload_msg_found": False,
            "test_passed": False, "dmesg_output_load": "", "dmesg_output_unload": ""
        },
        "overall_score": 0
    }
    logger.info(f"\n--- Evaluating Driver: {driver_filename} (Category: {category}) ---")

    # Expected messages for a basic "hello world" module
    # Ensure the AI generates these exact messages for successful detection.
    expected_load_msg = f"{driver_name_stem}: Hello World!"
    expected_unload_msg = f"{driver_name_stem}: Goodbye, World!"


    # --- Step 6.1: Compilation Assessment ---
    logger.info(f"  [STEP 6.1] Compiling {driver_filename}...")
    
    run_command(["make", "clean"], cwd=output_dir, description="make clean")
    
    bear_return_code, bear_stdout, bear_stderr = run_command(["bear", "--", "make"], cwd=output_dir, description="Bear (make)")
    compilation_output = bear_stdout + bear_stderr
    
    if bear_return_code == -1:
        logger.warning("  'bear' command not found. Falling back to 'make' without compilation database.")
        make_return_code, make_stdout, make_stderr = run_command(["make"], cwd=output_dir, description="make fallback")
        compilation_output = make_stdout + make_stderr
        final_make_return_code = make_return_code
    else:
        final_make_return_code = bear_return_code

    compile_errors = len(re.findall(r'^(?!.*warning:.*$).*:\s*(error|fatal error):.*$', compilation_output, re.MULTILINE | re.IGNORECASE))
    compile_warnings = len(re.findall(r'^\s*.*:\d+:\d+:\s*warning:.*$', compilation_output, re.MULTILINE | re.IGNORECASE))

    metrics["compilation"]["errors_count"] = compile_errors
    metrics["compilation"]["warnings_count"] = compile_warnings
    metrics["compilation"]["output"] = compilation_output.strip()

    logger.info(f"  Expected .ko path: {module_ko_path}")
    logger.info(f"  Checking if .ko file exists after compilation command: {os.path.exists(module_ko_path)}")
    try:
        logger.info(f"  Files in output_dir after make: {os.listdir(output_dir)}")
    except OSError as e:
        logger.error(f"  Could not list directory {output_dir}: {e}")

    if final_make_return_code == 0 and compile_errors == 0:
        if os.path.exists(module_ko_path):
            metrics["compilation"]["success"] = True
            logger.info("  Compilation successful (no errors detected, .ko generated).")
        else:
            logger.error("  Compilation reported success (exit 0, no errors in output), but .ko file is missing!")
            logger.error(f"  Expected .ko at: {module_ko_path}. Directory contents: {os.listdir(output_dir)}")
            metrics["compilation"]["success"] = False
    else:
        logger.error(f"  Compilation failed: Make exit code {final_make_return_code}, Errors in output {compile_errors}.")
        logger.debug(f"  Full Compilation Output:\n{compilation_output.strip()}")


    # --- Step 6.2: Code Style Compliance (checkpatch.pl) ---
    logger.info(f"  [STEP 6.2] Running checkpatch.pl on {driver_filename}...")
    
    style_warnings = 0
    style_errors = 0

    if CHECKPATCH_SCRIPT and os.path.exists(CHECKPATCH_SCRIPT) and os.access(CHECKPATCH_SCRIPT, os.X_OK): # Check if executable
        checkpatch_command = [CHECKPATCH_SCRIPT, "--no-tree", "-f", driver_filename]
        checkpatch_return_code, checkpatch_stdout, checkpatch_stderr = run_command(
            checkpatch_command, cwd=output_dir, description="checkpatch.pl"
        )

        style_warnings = len(re.findall(r'WARNING:', checkpatch_stdout))
        style_errors = len(re.findall(r'ERROR:', checkpatch_stdout))
        logger.info(f"  Checkpatch found {style_errors} errors and {style_warnings} warnings.")
        metrics["style"]["output"] = (checkpatch_stdout + checkpatch_stderr).strip()
    else:
        logger.error(f"  Error: checkpatch.pl not found or not executable at '{CHECKPATCH_SCRIPT}'. Is it installed and in PATH? You might need to 'chmod +x {CHECKPATCH_SCRIPT}' if it exists.")
        logger.error("  Skipping checkpatch: Script not found or executable.")
    
    metrics["style"]["warnings_count"] = style_warnings
    metrics["style"]["errors_count"] = style_errors


    # --- Step 6.3: Deep Static Analysis (clang-tidy) ---
    logger.info(f"  [STEP 6.3] Running clang-tidy on {driver_filename}...")
    clang_tidy_issues = 0
    clang_tidy_output = ""

    if os.path.exists(os.path.join(output_dir, "compile_commands.json")):
        clang_tidy_command = [
            "clang-tidy",
            "-p", ".",
            f"--checks='linuxkernel-*,bugprone-*,misc-*,readability-*,performance-*'",
            "-system-headers=false",
            driver_filename
        ]
        clang_tidy_return_code, clang_tidy_stdout, clang_tidy_stderr = run_command(
            clang_tidy_command, cwd=output_dir, description="clang-tidy"
        )
        clang_tidy_output = clang_tidy_stdout + clang_tidy_stderr
        clang_tidy_issues = len(re.findall(r'^\s*\S+:\d+:\d+:\s*(warning|error):', clang_tidy_output, re.MULTILINE | re.IGNORECASE))
        logger.info(f"  Clang-tidy found {clang_tidy_issues} issues.")
    else:
        logger.warning("  'compile_commands.json' not found. Skipping clang-tidy. Ensure 'bear' is installed and 'make' succeeds.")
    
    metrics["static_analysis"]["issues_count"] = clang_tidy_issues
    metrics["static_analysis"]["output"] = clang_tidy_output.strip()


    # --- Step 6.4: Functional Testing ---
    logger.info(f"  [STEP 6.4] Running functional tests on {driver_filename}...")
    metrics["functionality"]["test_attempted"] = True

    if metrics["compilation"]["success"] and os.path.exists(module_ko_path):
        functional_results = functional_test_driver(
            module_ko_path,
            driver_name_stem,
            output_dir,
            expected_load_msg,
            expected_unload_msg
        )
        metrics["functionality"].update(functional_results)
    else:
        logger.warning("  Skipping functional testing: Module did not compile successfully or .ko file missing.")
        if not os.path.exists(module_ko_path):
            logger.warning("  Score penalty: Functional test skipped because .ko file was not truly available for `insmod`.")
            metrics["functionality"]["load_success"] = False
        else:
            logger.warning("  Score penalty: Functional test not attempted (due to compilation issues).")


    # --- Step 6.5: Calculate Detailed and Overall Scores ---
    detailed_metrics = {
        "correctness": {
            "weight": 0.4,
            "compilation_success": 0.0,
            "functionality_pass": 0.0,
            "kernel_api_usage": 1.0 
        },
        "security_safety": {
            "weight": 0.25,
            "memory_safety": 1.0, 
            "resource_management": 1.0, 
            "race_conditions": 1.0, 
            "input_validation": 1.0 
        },
        "code_quality": {
            "weight": 0.2,
            "style_compliance": 1.0, 
            "error_handling": 1.0, 
            "documentation": 0.7, 
            "maintainability": 0.8 
        },
        "performance": {
            "weight": 0.1,
            "efficiency": 0.75, 
            "scalability": 0.6, 
            "memory_usage": 0.75 
        },
        "advanced_features": {
            "weight": 0.05,
            "power_management": 0.5, 
            "device_tree_support": 0.4, 
            "debug_support": 0.9 
        }
    }

    # --- Populate Correctness Scores ---
    detailed_metrics["correctness"]["compilation_success"] = 1.0 if metrics["compilation"]["success"] else 0.0
    detailed_metrics["correctness"]["functionality_pass"] = 1.0 if metrics["functionality"]["test_passed"] else 0.0

    api_misuse_penalty = 0
    api_misuse_issues = len(re.findall(r'linuxkernel-.*:', metrics["static_analysis"]["output"], re.IGNORECASE | re.MULTILINE))
    api_misuse_penalty += api_misuse_issues * 0.05 
    detailed_metrics["correctness"]["kernel_api_usage"] = max(0.0, 1.0 - api_misuse_penalty)

    # --- Populate Security & Safety Scores ---
    mem_safety_penalty = 0
    mem_safety_issues = len(re.findall(r'bugprone-(null-dereference|use-after-free|double-free)|clang-analyzer-security.insecureAPI\.memcpy|memory leak', metrics["static_analysis"]["output"], re.IGNORECASE | re.MULTILINE))
    mem_safety_penalty += mem_safety_issues * 0.05
    detailed_metrics["security_safety"]["memory_safety"] = max(0.0, 1.0 - mem_safety_penalty)

    resource_mgmt_penalty = 0
    resource_mgmt_issues = len(re.findall(r'resource leak|unhandled return value', metrics["static_analysis"]["output"], re.IGNORECASE | re.MULTILINE))
    resource_mgmt_penalty += resource_mgmt_issues * 0.05
    detailed_metrics["security_safety"]["resource_management"] = max(0.0, 1.0 - resource_mgmt_penalty)

    race_cond_penalty = 0
    race_cond_issues = len(re.findall(r'concurrency-.*|race condition', metrics["static_analysis"]["output"], re.IGNORECASE | re.MULTILINE)) 
    race_cond_penalty += race_cond_issues * 0.05
    detailed_metrics["security_safety"]["race_conditions"] = max(0.0, 1.0 - race_cond_penalty)

    input_val_penalty = 0
    input_val_issues = len(re.findall(r'clang-analyzer-security.insecureAPI|buffer-overflow|bounds check', metrics["static_analysis"]["output"], re.IGNORECASE | re.MULTILINE))
    input_val_penalty += input_val_issues * 0.05
    detailed_metrics["security_safety"]["input_validation"] = max(0.0, 1.0 - input_val_penalty)


    # --- Populate Code Quality Scores ---
    style_compliance_score = 1.0
    if CHECKPATCH_SCRIPT and os.path.exists(CHECKPATCH_SCRIPT) and os.access(CHECKPATCH_SCRIPT, os.X_OK):
        style_compliance_score -= (metrics["style"]["errors_count"] * 0.01) 
        style_compliance_score -= (metrics["style"]["warnings_count"] * 0.005) 
    detailed_metrics["code_quality"]["style_compliance"] = max(0.0, style_compliance_score)

    error_handling_score = 1.0
    error_handling_score -= (metrics["compilation"]["warnings_count"] * 0.005)
    error_handling_issues = len(re.findall(r'error handling|return value ignored', metrics["static_analysis"]["output"], re.IGNORECASE | re.MULTILINE)) 
    error_handling_score -= error_handling_issues * 0.02
    detailed_metrics["code_quality"]["error_handling"] = max(0.0, error_handling_score)

    # Documentation and Maintainability are largely subjective/require more advanced tools. Keeping defaults.


    # --- Calculate Overall Score based on new weighted metrics ---
    overall_score_sum = 0
    for category_name, category_data in detailed_metrics.items():
        if category_name in ["overall_score"]: 
            continue 

        weight = category_data.get("weight", 0)
        category_sub_score_sum = 0
        sub_criteria_count = 0
        
        for key, value in category_data.items():
            if key != "weight": 
                category_sub_score_sum += value
                sub_criteria_count += 1
        
        if sub_criteria_count > 0:
            overall_score_sum += (category_sub_score_sum / sub_criteria_count) * weight
        else:
            logger.warning(f"Category '{category_name}' has no sub-criteria for scoring. Check detailed_metrics definition.")

    final_calculated_score = overall_score_sum * 100
    detailed_metrics["overall_score"] = round(final_calculated_score, 2)

    metrics["detailed_scores"] = detailed_metrics
    metrics["overall_score"] = detailed_metrics["overall_score"]

    logger.info(f"  Overall Score for {driver_filename}: {metrics['overall_score']}/100")

    report_path_json = os.path.join(output_dir, "report.json")
    with open(report_path_json, "w") as f:
        json.dump(metrics, f, indent=4)
    logger.info(f"  Individual report saved to {report_path_json}")

    return metrics




def print_driver_summary(metrics):
    """
    Prints a clean, readable summary for a single driver.
    """
    print("\n" + "="*60)
    print(f"  Driver Summary: {metrics['filename']}")
    print("="*60)
    print(f"  Category: {metrics['category']}")
    print(f"  Compilation: {'PASS' if metrics['compilation']['success'] else 'FAIL'} (Errors: {metrics['compilation']['errors_count']}, Warnings: {metrics['compilation']['warnings_count']})")
    print(f"  Style Check (checkpatch.pl): Errors: {metrics['style']['errors_count']}, Warnings: {metrics['style']['warnings_count']}")
    print(f"  Static Analysis (clang-tidy): Issues: {metrics['static_analysis']['issues_count']}")
    
    func_status = "NOT ATTEMPTED"
    if metrics["functionality"]["test_attempted"]:
        func_status = "PASS" if metrics["functionality"]["test_passed"] else "FAIL"
        print(f"  Functional Test: {func_status}")
        print(f"    Load Success: {'Yes' if metrics['functionality']['load_success'] else 'No'}")
        print(f"    Unload Success: {'Yes' if metrics['functionality']['unload_success'] else 'No'}")
        print(f"    Kernel Oops Detected: {'Yes' if metrics['functionality']['kernel_oops_detected'] else 'No'}")
        if metrics["functionality"]["load_success"]:
             print(f"    Expected Load Message Found: {'Yes' if metrics['functionality']['load_msg_found'] else 'No'}")
        if metrics["functionality"]["unload_success"]:
            print(f"    Expected Unload Message Found: {'Yes' if metrics['functionality']['unload_msg_found'] else 'No'}")
    else:
        print(f"  Functional Test: {func_status} (due to compilation issues or .ko missing at runtime)")
        
    print(f"  Overall Score: {metrics['overall_score']}/100")
    print("="*60 + "\n")


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
    
    failed_load_count = sum(1 for r in all_results if r["functionality"]["test_attempted"] and not r["functionality"]["load_success"])
    failed_unload_count = sum(1 for r in all_results if r["functionality"]["load_success"] and not r["functionality"]["unload_success"])
    oops_detected_count = sum(1 for r in all_results if r["functionality"]["kernel_oops_detected"])
    missing_load_msg_count = sum(1 for r in all_results if r["functionality"]["test_attempted"] and r["functionality"]["load_success"] and not r["functionality"]["load_msg_found"])
    missing_unload_msg_count = sum(1 for r in all_results if r["functionality"]["test_attempted"] and r["functionality"]["unload_success"] and not r["functionality"]["unload_msg_found"])


    # General suggestions
    if failed_compilation_count > 0:
        suggestions.append(f"Model frequently generates non-compiling code ({failed_compilation_count}/{total_drivers} drivers failed). Focus on:")
        if total_compile_errors > 0:
            suggestions.append(f"  - Resolving {total_compile_errors} total compilation errors. Pay close attention to undefined symbols, incorrect header includes, and mismatched function arguments for kernel APIs.")
        if total_compile_warnings > 0:
            suggestions.append(f"  - Addressing {total_compile_warnings} total compilation warnings. Warnings often indicate potential issues that could lead to errors or unexpected behavior.")
    
    if CHECKPATCH_SCRIPT and (total_style_errors > 0 or total_style_warnings > 0):
        suggestions.append(f"Model needs improvement in Linux kernel coding style (total {total_style_errors} errors, {total_style_warnings} warnings from checkpatch.pl). Focus on:")
        checkpatch_output_combined = "".join(r["style"]["output"] for r in all_results)
        if "LINE_LENGTH_80" in checkpatch_output_combined:
            suggestions.append("  - Adhering to the 80-character line length limit. Ensure proper line wrapping.")
        if "BRACES" in checkpatch_output_combined:
            suggestions.append("  - Correct brace placement (opening brace on same line as function/control statement).")
        if "SPACING" in checkpatch_output_combined.lower() or "indentation" in checkpatch_output_combined.lower():
            suggestions.append("  - Consistent indentation (tabs not spaces) and proper spacing around operators.")
        suggestions.append("  - Reviewing variable naming conventions and proper use of 'static' and 'const'.")
    elif not CHECKPATCH_SCRIPT:
        suggestions.append("Checkpatch.pl was not found/executable. Consider installing it to get style feedback.")


    if total_static_analysis_issues > 0:
        suggestions.append(f"Model generates code with static analysis issues (total {total_static_analysis_issues} issues from clang-tidy). Focus on:")
        clang_output_combined = "".join(r["static_analysis"]["output"] for r in all_results)
        if "unhandled return value" in clang_output_combined.lower() or "NULL check" in clang_output_combined.lower():
            suggestions.append("  - Robust error handling: Ensure return values from kernel API calls (e.g., kmalloc, register_chrdev, class_create, device_create) are checked for errors.")
        if "resource leak" in clang_output_combined.lower() or "not freed" in clang_output_combined.lower():
            suggestions.append("  - Resource management: Ensure allocated resources (memory, IRQs, GPIOs, devices, /proc entries) are properly freed/released in all exit paths, especially in module_exit and error handlers.")
        if "concurrency" in clang_output_combined.lower() or "race condition" in clang_output_combined.lower() or "shared data" in clang_output_combined.lower():
             suggestions.append("  - Concurrency safety: Pay attention to race conditions and ensure shared data structures are protected with appropriate locking mechanisms (e.g., mutexes, spinlocks, atomic_t).")
        if "use after free" in clang_output_combined.lower():
            suggestions.append("  - Memory safety: Avoid use-after-free and double-free issues.")
        suggestions.append("  - General code correctness and adherence to kernel API usage patterns.")

    if oops_detected_count > 0:
        suggestions.append(f"Critical: {oops_detected_count} kernel oopses/panics detected during functional testing. This is a severe issue. Focus on:")
        suggestions.append("  - Dereferencing NULL pointers or invalid memory addresses.")
        suggestions.append("  - Incorrect use of kernel APIs leading to unexpected behavior or crashes.")
        suggestions.append("  - Race conditions leading to corrupted data structures or invalid state.")
    
    if failed_load_count > 0:
        suggestions.append(f"Model frequently generates modules that fail to load ({failed_load_count}/{total_drivers} drivers). Ensure `module_init` correctly registers all necessary components and handles errors.")

    if failed_unload_count > 0:
        suggestions.append(f"Model often generates modules that fail to unload ({failed_unload_count}/{total_drivers} drivers). Ensure `module_exit` correctly unregisters and frees all allocated resources.")
    
    if missing_load_msg_count > 0 or missing_unload_msg_count > 0:
        suggestions.append(f"Model sometimes misses expected printk messages ({missing_load_msg_count} load, {missing_unload_msg_count} unload). **Crucially, ensure appropriate `printk` messages are used for module lifecycle events, matching the expected format like '{SCENARIO_MAP[0]['filename'].split('.')[0]}: registered with major' and '{SCENARIO_MAP[0]['filename'].split('.')[0]}: unregistered'.**")
    
    if any("proc_create" in r["compilation"]["output"] and "proc_ops" in r["compilation"]["output"] for r in all_results):
        suggestions.append("Specific: The AI is using an outdated API for '/proc' filesystem entries (e.g., `proc_create`). It needs to use `const struct proc_ops *` instead of `struct file_operations *` for `proc_create` in modern kernels.")


    if failed_compilation_count == 0 and total_style_errors == 0 and total_static_analysis_issues == 0 and oops_detected_count == 0:
        suggestions.append("Excellent! The AI model produced a batch of drivers with no compilation errors, style errors, static analysis issues, or kernel oopses detected by automated tools. Consider increasing scenario complexity or focusing on advanced functional correctness.")

    return suggestions


# --- Main Execution Flow ---
if __name__ == "__main__":
    overall_model_scores = []
    all_driver_results = []

    setup_evaluation_run_dirs()

    timestamp = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
    current_run_dir = os.path.join(BASE_EVAL_DIR, timestamp)
    os.makedirs(current_run_dir, exist_ok=True)
    logger.info(f"Created evaluation run directory: {current_run_dir}")

    print_ai_prompt_instructions(current_run_dir)

    ai_output_file_path = os.path.join(DRIVERS_TO_EVALUATE_DIR, AI_OUTPUT_FILENAME)

    if not os.path.exists(ai_output_file_path):
        logger.error(f"Error: The expected AI output file '{ai_output_file_path}' not found.")
        logger.error("Please ensure you have placed the AI's response correctly and try again.")
        exit(1)

    logger.info(f"\nParsing '{AI_OUTPUT_FILENAME}' for individual driver code blocks...")
    parsed_drivers = parse_ai_output_file(ai_output_file_path)

    if not parsed_drivers:
        logger.error("No driver code blocks found in the AI output file. Exiting.")
        exit(1)

    if len(parsed_drivers) != len(SCENARIO_MAP):
        logger.error(f"Mismatch: Expected {len(SCENARIO_MAP)} drivers based on SCENARIO_MAP, but parsed {len(parsed_drivers)}.")
        logger.error("Please ensure the AI output contains exactly 5 delimited code blocks in the specified order.")
        exit(1)

    logger.info(f"Found {len(parsed_drivers)} driver code blocks.")

    # --- Dispatcher for evaluation functions ---
    evaluation_functions = {
        "char_device_basic_rw": evaluate_char_rw_driver,
        "char_device_ioctl_sync": evaluate_char_ioctl_sync_driver,
        "platform_device_gpio_irq": evaluate_platform_gpio_irq_driver,
        "char_device_procfs": evaluate_char_procfs_driver,
        "generic_kernel_module": evaluate_hello_module_driver,
    }

    for i, driver_info in enumerate(parsed_drivers):
        driver_filename = driver_info['filename']
        driver_code_content = driver_info['code_content']
        final_category = driver_info['category']

        file_eval_dir = os.path.join(current_run_dir, "results", os.path.splitext(driver_filename)[0])
        os.makedirs(file_eval_dir, exist_ok=True)
        
        driver_target_path = os.path.join(file_eval_dir, driver_filename)
        with open(driver_target_path, "w") as f:
            f.write(driver_code_content)
        logger.info(f"  Copied '{driver_filename}' to its evaluation directory.")

        makefile_target_path = os.path.join(file_eval_dir, "Makefile")
        try:
            with open(TEMPLATE_MAKEFILE, 'r') as tmpl_f:
                makefile_content = tmpl_f.read()
            makefile_content = makefile_content.replace("$(DRIVER_NAME)", os.path.splitext(driver_filename)[0])
            with open(makefile_target_path, "w") as mf:
                mf.write(makefile_content)
            logger.info(f"  Created Makefile for '{driver_filename}'.")
        except FileNotFoundError:
            logger.error(f"Error: Template Makefile '{TEMPLATE_MAKEFILE}' not found. Please ensure it exists.")
            exit(1)
        except Exception as e:
            logger.error(f"Error creating Makefile for '{driver_filename}': {e}", exc_info=True)
            exit(1)

        logger.info(f"Automatically detected '{driver_filename}' as: {final_category}")

        evaluation_func = evaluation_functions.get(final_category)
        if evaluation_func:
            file_metrics = evaluation_func(driver_target_path, file_eval_dir, final_category)
            all_driver_results.append(file_metrics)
            overall_model_scores.append(file_metrics["overall_score"])
            print_driver_summary(file_metrics)
        else:
            logger.error(f"No evaluation function defined for category: {final_category}. Skipping {driver_filename}.")
            all_driver_results.append({
                "filename": driver_filename, "category": final_category,
                "compilation": {"success": False, "errors_count": 99, "warnings_count": 0, "output": "No evaluation function."},
                "style": {"warnings_count": 0, "errors_count": 0, "output": ""},
                "static_analysis": {"issues_count": 0, "output": ""},
                "functionality": {"test_attempted": False, "load_success": False, "unload_success": False,
                                  "kernel_oops_detected": False, "load_msg_found": False, "unload_msg_found": False,
                                  "test_passed": False, "dmesg_output_load": "", "dmesg_output_unload": ""},
                "overall_score": 0
            })
            overall_model_scores.append(0)


    print("\n" + "="*80)
    print("           Overall AI Model Evaluation Results")
    print("="*80)
    if overall_model_scores:
        overall_model_average_score = sum(overall_model_scores) / len(overall_model_scores)
        print(f"Average Score Across All Drivers: {overall_model_average_score:.2f}/100\n")

        print("Detailed Results:")
        header = "| Driver Name        | Category                 | Compile | Style (E/W) | SA (Issues) | Func Test | Score |"
        separator = "|--------------------|--------------------------|---------|-------------|-------------|-----------|-------|"
        print(header)
        print(separator)
        
        for r in all_driver_results:
            compile_status = "PASS" if r["compilation"]["success"] else "FAIL"
            style_status = f"{r['style']['errors_count']}/{r['style']['warnings_count']}"
            sa_issues = r["static_analysis"]["issues_count"]
            func_test_status = "N/A"
            if r["functionality"]["test_attempted"]:
                func_test_status = "PASS" if r["functionality"]["test_passed"] else "FAIL"

            print(f"| {r['filename']:<18} | {r['category']:<24} | {compile_status:<7} | {style_status:<11} | {sa_issues:<11} | {func_test_status:<9} | {r['overall_score']:<5} |")
        print(separator)

        print("\n" + "="*80)
        print("             Model Fine-tuning Suggestions")
        print("="*80)
        suggestions = generate_fine_tuning_suggestions(all_driver_results)
        for s in suggestions:
            print(f"- {s}")
        print("="*80)


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

    print("\n" + "="*80)
    print("                   Evaluation complete!")
    print("="*80 + "\n")

