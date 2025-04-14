#!/usr/bin/env python3

"""
Carbon-Aware Scheduler Metrics Analysis Tool

This script analyzes and visualizes metrics data collected by collect_metrics.py.
It generates plots and summary statistics to evaluate the performance of a carbon-aware scheduler.
"""

import argparse
import datetime
import json
import os
import sys
import time
import numpy as np
from typing import Dict, List, Any, Tuple, Optional

class CarbonMetricsAnalyzer:
    """Analyzes and visualizes metrics from carbon-aware scheduler experiments."""
    
    def __init__(self, data_dir: str, output_dir: str = None):
        """
        Initialize the metrics analyzer.
        
        Args:
            data_dir: Directory containing the collected metrics data
            output_dir: Directory to save analysis results (defaults to data_dir if None)
        """
        self.data_dir = data_dir
        self.output_dir = output_dir if output_dir else data_dir
        self.plots_dir = os.path.join(self.output_dir, "plots")
        self.raw_data_dir = os.path.join(data_dir, "raw_data")
        self.results_file = os.path.join(self.output_dir, "results.json")
        self.config_file = os.path.join(data_dir, "experiment_config.json")
        
        # Ensure plots directory exists
        os.makedirs(self.plots_dir, exist_ok=True)
        
        # Set default configuration values
        self.config = {
            "experiment_name": os.path.basename(data_dir),
            "shrink_factor": 1,
            "collection_interval": 60,
        }
        
        # Try to load experiment configuration if it exists (newer format)
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    self.config.update(json.load(f))
                self.log(f"Loaded experiment configuration from {self.config_file}")
            except Exception as e:
                self.log(f"Warning: Failed to load config file: {e}")
        else:
            self.log(f"No experiment_config.json found, using default parameters")
            
            # For backward compatibility: Try to extract start_time from results.json if it exists
            if os.path.exists(self.results_file):
                try:
                    with open(self.results_file, 'r') as f:
                        results = json.load(f)
                        if "start_time" in results:
                            self.config["start_time"] = results["start_time"]
                        if "end_time" in results:
                            self.config["end_time"] = results["end_time"]
                        if "experiment_name" in results:
                            self.config["experiment_name"] = results["experiment_name"]
                    self.log(f"Extracted timing information from results.json")
                except Exception as e:
                    self.log(f"Warning: Failed to extract timing from results.json: {e}")
        
        # Load metrics data
        self.metrics = self._load_metrics_data()
        
        # Get experiment parameters
        self.experiment_name = self.config.get("experiment_name", "Unknown experiment")
        
        # Determine start and end time
        if "start_time" not in self.config or "end_time" not in self.config:
            # If no time information is available, try to infer from metrics
            if "carbon_metrics" in self.metrics and self.metrics["carbon_metrics"]:
                self.config["start_time"] = min(m["timestamp"] for m in self.metrics["carbon_metrics"]) 
                self.config["end_time"] = max(m["timestamp"] for m in self.metrics["carbon_metrics"])
                self.log(f"Inferred timing from metrics data")
            else:
                # Last resort: use current time minus 1 hour
                self.config["start_time"] = time.time() - 3600
                self.config["end_time"] = time.time()
                self.log(f"No timing information available, using defaults")
                
        self.start_time = self.config.get("start_time", 0)
        self.end_time = self.config.get("end_time", self.start_time + 3600)
        self.shrink_factor = self.config.get("shrink_factor", 1)
        
    def log(self, message: str) -> None:
        """Log a message to stdout."""
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] {message}")
        
    def _load_metrics_data(self) -> Dict[str, List[Dict[str, Any]]]:
        """Load all metrics data from JSON files."""
        metrics = {}
        self.log("Loading metrics data...")
        
        expected_files = ["nodes.json", "pods.json", "carbon_metrics.json", 
                          "performance.json", "placements.json", "scheduling.json"]
                          
        for filename in expected_files:
            filepath = os.path.join(self.raw_data_dir, filename)
            if os.path.exists(filepath):
                with open(filepath, 'r') as f:
                    metric_name = filename.split('.')[0]
                    metrics[metric_name] = json.load(f)
                    self.log(f"Loaded {len(metrics[metric_name])} {metric_name} records")
            else:
                metrics[filename.split('.')[0]] = []
                self.log(f"Warning: {filepath} not found")
        
        return metrics
    
    def calculate_summary_statistics(self) -> Dict[str, Any]:
        """Calculate summary statistics from collected metrics."""
        self.log("Calculating summary statistics...")
        
        summary = {
            "experiment_name": self.experiment_name,
            "duration_seconds": self.end_time - self.start_time,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "carbon_metrics": {},
            "performance_metrics": {},
            "placement_metrics": {}
        }
        
        # Calculate carbon metrics
        if "carbon_metrics" in self.metrics and self.metrics["carbon_metrics"]:
            collection_interval = self.config.get("collection_interval", 60)
            total_carbon = sum(m["total_carbon_rate"] for m in self.metrics["carbon_metrics"]) * collection_interval
            total_energy = sum(m["energy_consumption_kwh"] for m in self.metrics["carbon_metrics"])
            avg_carbon_intensity = sum(m["carbon_intensity"] for m in self.metrics["carbon_metrics"]) / len(self.metrics["carbon_metrics"])
            
            summary["carbon_metrics"] = {
                "total_carbon_emissions_g": total_carbon,
                "total_energy_consumption_kwh": total_energy,
                "average_carbon_intensity_gco2_per_kwh": avg_carbon_intensity
            }
        
        # Calculate performance metrics
        if "performance" in self.metrics and self.metrics["performance"]:
            avg_scheduling_latency_values = [m["avg_scheduling_latency"] for m in self.metrics["performance"] if m["avg_scheduling_latency"] is not None]
            
            if avg_scheduling_latency_values:
                avg_scheduling_latency = sum(avg_scheduling_latency_values) / len(avg_scheduling_latency_values)
            else:
                avg_scheduling_latency = None
                
            throughput = self.metrics["performance"][-1]["throughput"] if self.metrics["performance"][-1]["throughput"] is not None else 0
            
            summary["performance_metrics"] = {
                "avg_scheduling_latency_seconds": avg_scheduling_latency,
                "throughput_pods_per_minute": throughput,
                "final_running_pods": self.metrics["performance"][-1]["running_pods"],
                "final_pending_pods": self.metrics["performance"][-1]["pending_pods"],
                "final_failed_pods": self.metrics["performance"][-1]["failed_pods"]
            }
            
        # Calculate performance-carbon trade-off
        if "total_carbon_emissions_g" in summary["carbon_metrics"] and "avg_scheduling_latency_seconds" in summary["performance_metrics"]:
            if summary["performance_metrics"]["avg_scheduling_latency_seconds"] and summary["performance_metrics"]["avg_scheduling_latency_seconds"] > 0:
                summary["performance_carbon_tradeoff"] = summary["carbon_metrics"]["total_carbon_emissions_g"] / summary["performance_metrics"]["avg_scheduling_latency_seconds"]
            else:
                summary["performance_carbon_tradeoff"] = float("inf")
        
        return summary
    
    def generate_plots(self) -> None:
        """Generate visualization plots from the collected metrics."""
        self.log("Generating plots...")
        
        try:
            import matplotlib.pyplot as plt
            from matplotlib.dates import DateFormatter
        except ImportError:
            self.log("Error: matplotlib is required for plotting. Install with: pip install matplotlib")
            return
            
        # Create plots directory if it doesn't exist
        os.makedirs(self.plots_dir, exist_ok=True)
        
        # Generate different types of plots
        self._plot_carbon_metrics(plt)
        self._plot_performance_metrics(plt)
        self._plot_node_utilization(plt)
        self._plot_combined_metrics(plt)
        
        self.log(f"Plots saved to {self.plots_dir}")
    
    def _plot_carbon_metrics(self, plt) -> None:
        """Generate plots for carbon-related metrics."""
        if "carbon_metrics" not in self.metrics or not self.metrics["carbon_metrics"]:
            self.log("No carbon metrics data available for plotting")
            return
            
        carbon_data = self.metrics["carbon_metrics"]
        
        # Convert timestamps to hours from start time
        real_timestamps = [m["timestamp"] - self.start_time for m in carbon_data]
        sim_timestamps_hours = [(t * self.shrink_factor) / 3600 for t in real_timestamps]
        
        # Extract metrics
        carbon_rates = [m["total_carbon_rate"] for m in carbon_data]
        power_usage = [m["total_power_watts"] for m in carbon_data]
        carbon_intensity = [m["carbon_intensity"] for m in carbon_data]
        
        # Plot carbon emission rate
        plt.figure(figsize=(10, 6))
        plt.plot(sim_timestamps_hours, carbon_rates, 'b-', label="Total Carbon Rate")
        plt.xlabel("Simulation Time (hours)")
        plt.ylabel("Carbon Emission Rate (g CO₂/s)")
        plt.title("Carbon Emission Rate Over Time")
        plt.grid(True)
        plt.legend()
        plt.tight_layout()
        plt.savefig(os.path.join(self.plots_dir, "carbon_rate.png"))
        plt.close()
        
        # Plot power usage
        plt.figure(figsize=(10, 6))
        plt.plot(sim_timestamps_hours, power_usage, 'r-', label="Total Power Usage")
        plt.xlabel("Simulation Time (hours)")
        plt.ylabel("Power (W)")
        plt.title("Power Usage Over Time")
        plt.grid(True)
        plt.legend()
        plt.tight_layout()
        plt.savefig(os.path.join(self.plots_dir, "power_usage.png"))
        plt.close()
        
        # Plot carbon intensity
        plt.figure(figsize=(10, 6))
        plt.plot(sim_timestamps_hours, carbon_intensity, 'g-', label="Carbon Intensity")
        plt.xlabel("Simulation Time (hours)")
        plt.ylabel("Carbon Intensity (g CO₂/kWh)")
        plt.title("Carbon Intensity Over Time")
        plt.grid(True)
        plt.legend()
        plt.tight_layout()
        plt.savefig(os.path.join(self.plots_dir, "carbon_intensity.png"))
        plt.close()
        
        # Calculate cumulative carbon emissions
        collection_interval = self.config.get("collection_interval", 60)
        cumulative_carbon = np.cumsum([r * collection_interval for r in carbon_rates])
        
        # Plot cumulative carbon emissions
        plt.figure(figsize=(10, 6))
        plt.plot(sim_timestamps_hours, cumulative_carbon, 'b-', label="Cumulative Carbon Emissions")
        plt.xlabel("Simulation Time (hours)")
        plt.ylabel("Cumulative Emissions (g CO₂)")
        plt.title("Cumulative Carbon Emissions Over Time")
        plt.grid(True)
        plt.legend()
        plt.tight_layout()
        plt.savefig(os.path.join(self.plots_dir, "cumulative_carbon.png"))
        plt.close()
    
    def _plot_performance_metrics(self, plt) -> None:
        """Generate plots for performance-related metrics."""
        if "performance" not in self.metrics or not self.metrics["performance"]:
            self.log("No performance metrics data available for plotting")
            return
            
        performance_data = self.metrics["performance"]
        
        # Convert timestamps to hours from start time
        real_timestamps = [m["timestamp"] - self.start_time for m in performance_data]
        sim_timestamps_hours = [(t * self.shrink_factor) / 3600 for t in real_timestamps]
        
        # Extract metrics
        running_pods = [m["running_pods"] for m in performance_data]
        pending_pods = [m["pending_pods"] for m in performance_data]
        failed_pods = [m["failed_pods"] for m in performance_data]
        
        # Plot pod status
        plt.figure(figsize=(10, 6))
        plt.plot(sim_timestamps_hours, running_pods, 'g-', label="Running Pods")
        plt.plot(sim_timestamps_hours, pending_pods, 'y-', label="Pending Pods")
        plt.plot(sim_timestamps_hours, failed_pods, 'r-', label="Failed Pods")
        plt.xlabel("Simulation Time (hours)")
        plt.ylabel("Pod Count")
        plt.title("Pod Status Over Time")
        plt.grid(True)
        plt.legend()
        plt.tight_layout()
        plt.savefig(os.path.join(self.plots_dir, "pod_status.png"))
        plt.close()
        
        # Plot scheduling latency if available
        latency_data = [m for m in performance_data if m["avg_scheduling_latency"] is not None]
        if latency_data:
            lat_timestamps = [(m["timestamp"] - self.start_time) * self.shrink_factor / 3600 for m in latency_data]
            avg_latencies = [m["avg_scheduling_latency"] for m in latency_data]
            p95_latencies = [m["p95_scheduling_latency"] for m in latency_data if m["p95_scheduling_latency"] is not None]
            
            plt.figure(figsize=(10, 6))
            plt.plot(lat_timestamps, avg_latencies, 'b-', label="Average Scheduling Latency")
            if p95_latencies and len(p95_latencies) == len(lat_timestamps):
                plt.plot(lat_timestamps, p95_latencies, 'r-', label="95th Percentile Latency")
            plt.xlabel("Simulation Time (hours)")
            plt.ylabel("Latency (s)")
            plt.title("Pod Scheduling Latency Over Time")
            plt.grid(True)
            plt.legend()
            plt.tight_layout()
            plt.savefig(os.path.join(self.plots_dir, "scheduling_latency.png"))
            plt.close()
    
    def _plot_node_utilization(self, plt) -> None:
        """Generate plots for node utilization metrics."""
        if "nodes" not in self.metrics or not self.metrics["nodes"]:
            self.log("No node metrics data available for plotting")
            return
            
        # Group nodes by name
        node_names = set(node["node_name"] for node in self.metrics["nodes"])
        
        for node_name in sorted(node_names):
            node_data = [n for n in self.metrics["nodes"] if n["node_name"] == node_name]
            if not node_data:
                continue
                
            # Sort by timestamp
            node_data.sort(key=lambda x: x["timestamp"])
            
            # Convert timestamps to hours from start time
            real_timestamps = [m["timestamp"] - self.start_time for m in node_data]
            sim_timestamps_hours = [(t * self.shrink_factor) / 3600 for t in real_timestamps]
            
            # Extract metrics
            cpu_utilization = [n["cpu_utilization"] for n in node_data]
            power_draw = [n["power_draw"] for n in node_data]
            
            # Plot CPU utilization
            plt.figure(figsize=(10, 6))
            plt.plot(sim_timestamps_hours, cpu_utilization, 'b-', label="CPU Utilization")
            plt.xlabel("Simulation Time (hours)")
            plt.ylabel("CPU Utilization (%)")
            plt.title(f"CPU Utilization for {node_name}")
            plt.grid(True)
            plt.legend()
            plt.tight_layout()
            plt.savefig(os.path.join(self.plots_dir, f"cpu_utilization_{node_name}.png"))
            plt.close()
            
            # Plot power draw
            plt.figure(figsize=(10, 6))
            plt.plot(sim_timestamps_hours, power_draw, 'r-', label="Power Draw")
            plt.xlabel("Simulation Time (hours)")
            plt.ylabel("Power (W)")
            plt.title(f"Power Draw for {node_name}")
            plt.grid(True)
            plt.legend()
            plt.tight_layout()
            plt.savefig(os.path.join(self.plots_dir, f"power_draw_{node_name}.png"))
            plt.close()
            
    def _plot_combined_metrics(self, plt) -> None:
        """Generate combined metric plots showing correlations."""
        if not self.metrics["carbon_metrics"] or not self.metrics["performance"]:
            return
            
        # Plot carbon vs. throughput
        carbon_timestamps = [m["timestamp"] for m in self.metrics["carbon_metrics"]]
        carbon_rates = [m["total_carbon_rate"] for m in self.metrics["carbon_metrics"]]
        
        perf_timestamps = [m["timestamp"] for m in self.metrics["performance"]]
        running_pods = [m["running_pods"] for m in self.metrics["performance"]]
        
        # Find the closest performance data point for each carbon data point
        combined_data = []
        for i, ts in enumerate(carbon_timestamps):
            closest_idx = min(range(len(perf_timestamps)), key=lambda j: abs(perf_timestamps[j] - ts))
            combined_data.append({
                "timestamp": ts,
                "carbon_rate": carbon_rates[i],
                "running_pods": running_pods[closest_idx]
            })
        
        # Sort by timestamp
        combined_data.sort(key=lambda x: x["timestamp"])
        
        # Convert timestamps to hours
        sim_timestamps_hours = [(m["timestamp"] - self.start_time) * self.shrink_factor / 3600 for m in combined_data]
        
        # Create figure with two y-axes
        fig, ax1 = plt.subplots(figsize=(10, 6))
        
        # Plot carbon rate on left y-axis
        ax1.set_xlabel("Simulation Time (hours)")
        ax1.set_ylabel("Carbon Rate (g CO₂/s)", color="b")
        ax1.plot(sim_timestamps_hours, [m["carbon_rate"] for m in combined_data], 'b-', label="Carbon Rate")
        ax1.tick_params(axis="y", labelcolor="b")
        
        # Create second y-axis for running pods
        ax2 = ax1.twinx()
        ax2.set_ylabel("Running Pods", color="g")
        ax2.plot(sim_timestamps_hours, [m["running_pods"] for m in combined_data], 'g-', label="Running Pods")
        ax2.tick_params(axis="y", labelcolor="g")
        
        # Add legend
        lines1, labels1 = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper right")
        
        plt.title("Carbon Rate vs. Running Pods")
        plt.grid(True)
        plt.tight_layout()
        plt.savefig(os.path.join(self.plots_dir, "carbon_vs_pods.png"))
        plt.close()
        
        # Calculate the performance-carbon tradeoff
        if len(combined_data) > 1:
            # Performance (pods) per unit carbon
            pods_per_carbon = [d["running_pods"] / (d["carbon_rate"] if d["carbon_rate"] > 0 else 1.0) 
                              for d in combined_data]
            
            plt.figure(figsize=(10, 6))
            plt.plot(sim_timestamps_hours, pods_per_carbon, 'm-', label="Performance-Carbon Ratio")
            plt.xlabel("Simulation Time (hours)")
            plt.ylabel("Pods per g CO₂/s")
            plt.title("Performance-Carbon Tradeoff Over Time")
            plt.grid(True)
            plt.legend()
            plt.tight_layout()
            plt.savefig(os.path.join(self.plots_dir, "performance_carbon_tradeoff.png"))
            plt.close()
        
    def analyze_metrics(self) -> None:
        """Run the full analysis and generate results."""
        self.log(f"Analyzing metrics for experiment: {self.experiment_name}")
        
        # Calculate summary statistics
        summary = self.calculate_summary_statistics()
        
        # Save results to JSON file
        with open(self.results_file, 'w') as f:
            json.dump(summary, f, indent=2)
            
        self.log(f"Results saved to {self.results_file}")
        
        # Generate plots
        self.generate_plots()
        
        # Print key metrics
        self._print_key_metrics(summary)
        
    def _print_key_metrics(self, summary: Dict[str, Any]) -> None:
        """Print key metrics to the console for quick review."""
        print("\n" + "="*60)
        print(f"SUMMARY: {self.experiment_name}")
        print("="*60)
        
        # Carbon metrics
        carbon = summary.get("carbon_metrics", {})
        if carbon:
            print("\nCARBON METRICS:")
            print(f"Total carbon emissions: {carbon.get('total_carbon_emissions_g', 'N/A')} g CO₂")
            print(f"Total energy consumption: {carbon.get('total_energy_consumption_kwh', 'N/A')} kWh")
            print(f"Average carbon intensity: {carbon.get('average_carbon_intensity_gco2_per_kwh', 'N/A')} g CO₂/kWh")
        
        # Performance metrics
        perf = summary.get("performance_metrics", {})
        if perf:
            print("\nPERFORMANCE METRICS:")
            print(f"Avg scheduling latency: {perf.get('avg_scheduling_latency_seconds', 'N/A')} seconds")
            print(f"Throughput: {perf.get('throughput_pods_per_minute', 'N/A')} pods/minute")
            print(f"Final running pods: {perf.get('final_running_pods', 'N/A')}")
            print(f"Final pending pods: {perf.get('final_pending_pods', 'N/A')}")
        
        # Performance-Carbon tradeoff
        if "performance_carbon_tradeoff" in summary:
            print("\nPERFORMANCE-CARBON TRADEOFF:")
            print(f"Carbon per latency unit: {summary.get('performance_carbon_tradeoff', 'N/A')} g CO₂/s")
            
        print("\n" + "="*60)
        print(f"Plots saved to: {self.plots_dir}")
        print("="*60 + "\n")

def main():
    """Main function to run the metrics analyzer."""
    parser = argparse.ArgumentParser(description="Carbon-Aware Scheduler Metrics Analysis Tool")
    parser.add_argument("--data-dir", required=True,
                        help="Directory containing the collected metrics data")
    parser.add_argument("--output-dir", default=None,
                        help="Directory to save analysis results (defaults to data-dir if not specified)")
    
    args = parser.parse_args()
    
    if not os.path.isdir(args.data_dir):
        print(f"Error: Data directory not found: {args.data_dir}")
        sys.exit(1)
        
    analyzer = CarbonMetricsAnalyzer(
        data_dir=args.data_dir,
        output_dir=args.output_dir
    )
    
    analyzer.analyze_metrics()
    
if __name__ == "__main__":
    main()