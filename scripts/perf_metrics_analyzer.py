#!/usr/bin/env python3

"""
Performance Metrics Analyzer for Carbon-Aware Scheduler

This script parses logs containing <PERF> metrics, saves them to a CSV file,
and generates visualizations showing how these metrics change over time.
"""

import argparse
import csv
import datetime
import matplotlib.pyplot as plt
import os
import re
import sys
from collections import defaultdict

def parse_log_file(log_file_path):
    """Parse log file to extract performance metrics."""
    if not os.path.exists(log_file_path):
        print(f"Error: Log file {log_file_path} not found")
        return None
        
    perf_metrics = defaultdict(list)
    iteration_markers = []
    current_iteration = 0
    timestamp_pattern = re.compile(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)')
    
    with open(log_file_path, 'r') as f:
        for line in f:
            # Check if this is a new iteration marker (a line indicating a new timeslot)
            if 'Processing timeslot' in line or 'Processing: timeslot_' in line:
                iteration_match = re.search(r'timeslot (\d+)/(\d+)|timeslot_(\d+)\.yaml', line)
                if iteration_match:
                    # Extract iteration number from either format
                    if iteration_match.group(1):
                        current_iteration = int(iteration_match.group(1))
                    elif iteration_match.group(3):
                        current_iteration = int(iteration_match.group(3)) + 1  # Convert to 1-indexed
                    
                    # Get timestamp if available
                    ts_match = timestamp_pattern.search(line)
                    if not ts_match:
                        # Try different timestamp format
                        ts_match = re.search(r'(\w{3} \w{3} \d{1,2} \d{2}:\d{2}:\d{2} \w{2} \w{3} \d{4})', line)
                    
                    timestamp = ts_match.group(1) if ts_match else ""
                    iteration_markers.append((current_iteration, timestamp))

            # Check for perf metrics in the line
            if '<PERF>' in line:
                match = re.search(r'<PERF> Elapsed time for (\w+) is (\d+\.\d+\w*)', line)
                if match:
                    metric_name = match.group(1)
                    value_str = match.group(2)
                    
                    # Parse value with units (ms, s, etc.)
                    if 'ms' in value_str:
                        value = float(value_str.replace('ms', '')) / 1000  # Convert ms to seconds
                    elif 'µs' in value_str or 'us' in value_str:
                        value = float(re.sub(r'[µu]s', '', value_str)) / 1000000  # Convert µs to seconds
                    elif 'ns' in value_str:
                        value = float(value_str.replace('ns', '')) / 1000000000  # Convert ns to seconds
                    else:
                        value = float(re.sub(r'[^\d.]', '', value_str))  # Assume seconds if no unit

                    # Store metric with iteration number
                    perf_metrics[metric_name].append((current_iteration, value))
                    
                    # Extract timestamp if available
                    ts_match = timestamp_pattern.search(line)
                    timestamp = ts_match.group(1) if ts_match else ""
    
    return perf_metrics, iteration_markers

def save_to_csv(perf_metrics, output_file):
    """Save the parsed metrics to a CSV file."""
    # First, determine all unique metric names
    metric_names = sorted(perf_metrics.keys())
    
    # Create a dictionary to hold data by iteration
    data_by_iteration = {}
    
    # Populate the dictionary
    for metric_name in metric_names:
        for iteration, value in perf_metrics[metric_name]:
            if iteration not in data_by_iteration:
                data_by_iteration[iteration] = {'iteration': iteration}
            data_by_iteration[iteration][metric_name] = value
    
    # Convert to a list and sort by iteration
    rows = sorted(data_by_iteration.values(), key=lambda x: x['iteration'])
    
    # Write to CSV
    with open(output_file, 'w', newline='') as f:
        fieldnames = ['iteration'] + metric_names
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    
    print(f"Metrics saved to {output_file}")

def generate_plots(perf_metrics, output_dir):
    """Generate plots visualizing the performance metrics."""
    os.makedirs(output_dir, exist_ok=True)
    
    # Individual plots for each metric
    for metric_name, values in perf_metrics.items():
        if not values:
            continue
            
        iterations = [v[0] for v in values]
        metric_values = [v[1] for v in values]
        
        plt.figure(figsize=(10, 6))
        plt.plot(iterations, metric_values, 'o-', linewidth=2)
        plt.title(f'{metric_name} Performance Over Time')
        plt.xlabel('Iteration')
        plt.ylabel('Time (seconds)')
        plt.grid(True)
        
        # Add data points with values
        for i, (x, y) in enumerate(zip(iterations, metric_values)):
            plt.annotate(f'{y:.4f}s', (x, y), textcoords="offset points", 
                        xytext=(0,10), ha='center')
        
        plt.savefig(os.path.join(output_dir, f'{metric_name}_performance.png'))
        plt.close()
    
    # Combined plot with all metrics
    plt.figure(figsize=(12, 8))
    
    for metric_name, values in perf_metrics.items():
        if not values:
            continue
            
        iterations = [v[0] for v in values]
        metric_values = [v[1] for v in values]
        
        plt.plot(iterations, metric_values, 'o-', linewidth=2, label=metric_name)
    
    plt.title('Performance Metrics Comparison')
    plt.xlabel('Iteration')
    plt.ylabel('Time (seconds)')
    plt.legend()
    plt.grid(True)
    plt.savefig(os.path.join(output_dir, 'combined_performance.png'))
    
    # Log scale version (for better visibility of small values)
    plt.yscale('log')
    plt.title('Performance Metrics Comparison (Log Scale)')
    plt.savefig(os.path.join(output_dir, 'combined_performance_log.png'))
    plt.close()
    
    print(f"Plots saved to {output_dir}")

def main():
    parser = argparse.ArgumentParser(description='Analyze performance metrics from carbon-aware scheduler logs')
    parser.add_argument('--log-file', required=True, help='Path to the log file containing perf metrics')
    parser.add_argument('--output-dir', default='./perf_metrics', help='Directory to save output files')
    parser.add_argument('--output-csv', default='performance_metrics.csv', help='Filename for the CSV output')
    
    args = parser.parse_args()
    
    os.makedirs(args.output_dir, exist_ok=True)
    csv_path = os.path.join(args.output_dir, args.output_csv)
    
    # Parse the log file
    perf_metrics, iteration_markers = parse_log_file(args.log_file)
    
    if not perf_metrics:
        print("No performance metrics found in the log file.")
        sys.exit(1)
    
    # Show summary of metrics found
    print("\nPerformance Metrics Found:")
    for metric_name, values in perf_metrics.items():
        if values:
            min_value = min([v[1] for v in values])
            max_value = max([v[1] for v in values])
            avg_value = sum([v[1] for v in values]) / len(values)
            print(f"  {metric_name}: {len(values)} data points, Min={min_value:.4f}s, Max={max_value:.4f}s, Avg={avg_value:.4f}s")
    
    # Save to CSV
    save_to_csv(perf_metrics, csv_path)
    
    # Generate plots
    generate_plots(perf_metrics, args.output_dir)

if __name__ == "__main__":
    main()