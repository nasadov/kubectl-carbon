#!/usr/bin/env python3

"""
CPU Limiting Wrapper Script

This script wraps subprocess execution to limit CPU usage,
preventing processes from consuming 100% CPU and causing
system instability or connection issues.

Usage:
    python3 limit_cpu.py --cpu-limit 50 --command "command to execute"
"""

import argparse
import os
import subprocess
import signal
import sys
import time
import psutil
import shlex

def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Run a command with CPU usage limits")
    parser.add_argument('--cpu-limit', type=int, default=50,
                        help='CPU usage limit percentage (default: 50)')
    parser.add_argument('--command', type=str, required=True,
                        help='Command to execute (in quotes)')
    parser.add_argument('--check-interval', type=float, default=0.5,
                        help='Interval in seconds to check CPU usage (default: 0.5)')
    parser.add_argument('--pause-duration', type=float, default=0.1,
                        help='Duration in seconds to pause when CPU limit is exceeded (default: 0.1)')
    return parser.parse_args()

def limit_process_cpu(process, cpu_limit, check_interval, pause_duration):
    """Monitor and limit CPU usage of a process."""
    try:
        p = psutil.Process(process.pid)
        
        while process.poll() is None:  # While the process is still running
            try:
                cpu_percent = p.cpu_percent(interval=check_interval)
                
                # Check children processes too
                for child in p.children(recursive=True):
                    try:
                        cpu_percent += child.cpu_percent(interval=0)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                
                if cpu_percent > cpu_limit:
                    # Pause the process if it exceeds the CPU limit
                    process.send_signal(signal.SIGSTOP)
                    time.sleep(pause_duration)
                    process.send_signal(signal.SIGCONT)
                
                time.sleep(check_interval)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                # Process may have terminated
                break
    except Exception as e:
        print(f"Error monitoring process: {e}", file=sys.stderr)

def run_with_cpu_limit():
    """Run the specified command with CPU usage limits."""
    args = parse_args()
    
    # Check if psutil is available
    try:
        import psutil
    except ImportError:
        print("Warning: psutil module not found. CPU limiting will not be available.")
        print("To install: pip install psutil")
        
        # Run the command without limiting
        process = subprocess.Popen(args.command, shell=True)
        return_code = process.wait()
        sys.exit(return_code)
    
    try:
        # Start the process
        process = subprocess.Popen(shlex.split(args.command))
        
        # Monitor and limit CPU usage in a non-blocking way
        limit_process_cpu(process, args.cpu_limit, args.check_interval, args.pause_duration)
        
        # Wait for the process to complete
        return_code = process.wait()
        sys.exit(return_code)
    
    except KeyboardInterrupt:
        print("\nInterrupted by user. Terminating the process...")
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        if 'process' in locals() and process.poll() is None:
            process.terminate()
        sys.exit(1)

if __name__ == "__main__":
    run_with_cpu_limit()