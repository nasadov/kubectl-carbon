#!/usr/bin/env python3

"""
Carbon-Aware Scheduler Metrics Analysis Tool

This script analyzes and visualizes metrics data collected by collect_metrics.py.
It generates plots and summary statistics to evaluate the performance of a carbon-aware scheduler.
"""

import argparse
import bisect
import datetime
import json
import os
import sys
import time
import numpy as np
import subprocess
from typing import Dict, List, Any, Tuple, Optional

# Apply NumPy compatibility patch first to ensure np.Inf is available
try:
    from numpy_compat_patch import apply_numpy_compatibility_patch
    apply_numpy_compatibility_patch()
    print("NumPy compatibility patch applied successfully")
except ImportError:
    # If the patch module is not found, use direct patching
    if not hasattr(np, 'Inf'):
        np.__dict__['Inf'] = np.inf
        print("Applied basic NumPy compatibility patch for np.Inf")

class CarbonMetricsAnalyzer:
    """Analyzes and visualizes metrics from carbon-aware scheduler experiments."""
    
    def _convert_to_simulation_hours(self, timestamps, start_time=None):
        """Convert timestamps to simulation hours using the shrink factor.
        
        In a time-accelerated simulation, 1 real second = shrink_factor simulation seconds.
        For example, with shrink_factor=3600, 1 real second = 1 simulation hour.
        
        This function converts real timestamps to simulation hour values,
        where 0 is the simulation start time.
        """
        # If no start_time provided, use the experiment start time
        # This ensures consistent time scale across ALL plots
        if start_time is None:
            start_time = self.start_time
        
        # Convert elapsed real time to simulation hours
        # Formula: simulation_hours = real_seconds * shrink_factor / 3600
        # This shows how many simulation hours have passed since the start
        return [(t - start_time) / 3600 * self.shrink_factor for t in timestamps]
    
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
        
        # Ensure base plots directory exists
        os.makedirs(self.plots_dir, exist_ok=True)
        
        # Define plot subdirectories
        self.carbon_plots_dir = os.path.join(self.plots_dir, "carbon")
        self.performance_plots_dir = os.path.join(self.plots_dir, "performance")
        self.node_plots_dir = os.path.join(self.plots_dir, "nodes")
        self.comparison_plots_dir = os.path.join(self.plots_dir, "comparison")
        
        # Create plot subdirectories
        os.makedirs(self.carbon_plots_dir, exist_ok=True)
        os.makedirs(self.performance_plots_dir, exist_ok=True)
        os.makedirs(self.node_plots_dir, exist_ok=True)
        os.makedirs(self.comparison_plots_dir, exist_ok=True)
        
        # Set default configuration values
        self.config = {
            "experiment_name": os.path.basename(data_dir),
            "shrink_factor": 60,  # Default: 1 real second = 1 simulation minute
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
        self.shrink_factor = self.config.get("shrink_factor", 60)  # Default: 1 second = 1 minute
        
        # Color scheme for plots
        self.colors = {
            "carbon_rate": "#1f77b4",  # Blue
            "power_usage": "#ff7f0e",  # Orange
            "carbon_intensity": "#2ca02c",  # Green
            "cumulative_carbon": "#d62728",  # Red
            "running_pods": "#9467bd",  # Purple
            "pending_pods": "#8c564b",  # Brown
            "failed_pods": "#e377c2",  # Pink
            "regions": {
                "DE": "#1f77b4",  # Blue
                "FR": "#2ca02c",  # Green
                "ES": "#ff7f0e",  # Orange
                "IT-NO": "#d62728",  # Red
                "unknown": "#7f7f7f"  # Gray
            }
        }
        
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
            shrink_factor = self.config.get("shrink_factor", 1) # Get shrink factor
            simulated_interval_seconds = collection_interval * shrink_factor
            simulated_interval_hours = simulated_interval_seconds / 3600.0
            
            # Calculate total carbon using simulated interval
            total_carbon = sum(m["total_carbon_rate"] * simulated_interval_seconds 
                             for m in self.metrics["carbon_metrics"])
            
            # Calculate total energy using simulated interval and power rate
            total_energy = sum(m["total_power_watts"] / 1000.0 * simulated_interval_hours 
                             for m in self.metrics["carbon_metrics"])
            
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
            
        # Create all plot directories (redundant check, but safe)
        os.makedirs(self.carbon_plots_dir, exist_ok=True)
        os.makedirs(self.performance_plots_dir, exist_ok=True)
        os.makedirs(self.node_plots_dir, exist_ok=True)
        os.makedirs(self.comparison_plots_dir, exist_ok=True)
        
        # Generate different types of plots with progress logging
        self.log("Creating carbon metrics plots...")
        self._plot_carbon_metrics(plt)
        
        self.log("Creating performance metrics plots...")
        self._plot_performance_metrics(plt)
        
        self.log("Creating node utilization plots...")
        self._plot_node_utilization(plt)
        
        self.log("Creating comparison plots...")
        self._plot_performance_emissions_tradeoff(plt) # This now saves to comparison_plots_dir
        self._create_aggregated_bar_charts(plt)      # This now saves to comparison_plots_dir
        self._create_algorithm_comparison_charts(plt) # This now saves to comparison_plots_dir
        
        self.log(f"All plots saved to subdirectories within {self.plots_dir}")
    
    def _plot_carbon_metrics(self, plt) -> None:
        """Generate plots for carbon-related metrics."""
        if "carbon_metrics" not in self.metrics or not self.metrics["carbon_metrics"]:
            self.log("No carbon metrics data available for plotting")
            return
            
        carbon_data = self.metrics["carbon_metrics"]
        
        # Convert timestamps to simulation hours from start time using our helper method
        # This ensures consistent time scale across all plots
        timestamps = [m["timestamp"] for m in carbon_data]
        sim_timestamps_hours = self._convert_to_simulation_hours(timestamps)
        
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
        plt.savefig(os.path.join(self.carbon_plots_dir, "carbon_rate.png"))
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
        plt.savefig(os.path.join(self.carbon_plots_dir, "power_usage.png"))
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
        plt.savefig(os.path.join(self.carbon_plots_dir, "carbon_intensity.png"))
        plt.close()
        
        # Calculate cumulative carbon emissions using simulated interval
        collection_interval = self.config.get("collection_interval", 60)
        shrink_factor = self.config.get("shrink_factor", 1)
        simulated_interval_seconds = collection_interval * shrink_factor
        cumulative_carbon = np.cumsum([r * simulated_interval_seconds for r in carbon_rates])
        
        # Plot cumulative carbon emissions
        plt.figure(figsize=(10, 6))
        plt.plot(sim_timestamps_hours, cumulative_carbon, 'b-', label="Cumulative Carbon Emissions (Simulated)")
        plt.xlabel("Simulation Time (hours)")
        plt.ylabel("Cumulative Emissions (g CO₂)")
        plt.title("Cumulative Carbon Emissions Over Simulated Time")
        plt.grid(True)
        plt.legend()
        plt.tight_layout()
        plt.savefig(os.path.join(self.carbon_plots_dir, "cumulative_carbon.png"))
        plt.close()

        self._plot_time_series_by_region(plt)
        self._create_carbon_heatmap(plt)

    def _plot_performance_metrics(self, plt) -> None:
        """Generate plots for performance-related metrics."""
        if "performance" not in self.metrics or not self.metrics["performance"]:
            self.log("No performance metrics data available for plotting")
            return
            
        performance_data = self.metrics["performance"]
        
        # Convert timestamps to simulation hours using our helper method
        # This ensures consistent time scale across all plots
        timestamps = [m["timestamp"] for m in performance_data]
        sim_timestamps_hours = self._convert_to_simulation_hours(timestamps)
        
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
        plt.savefig(os.path.join(self.performance_plots_dir, "pod_status.png"))
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
            plt.savefig(os.path.join(self.performance_plots_dir, "scheduling_latency.png"))
            plt.close()

    def _plot_node_utilization(self, plt) -> None:
        """Generate plots for node utilization metrics."""
        if "nodes" not in self.metrics or not self.metrics["nodes"]:
            self.log("No node metrics data available for plotting")
            return
            
        # Group nodes by name
        node_names = set(node["node_name"] for node in self.metrics["nodes"])
        
        # For debugging, log the first timestamp and simulation hour mapping
        if self.metrics["nodes"]:
            first_ts = self.metrics["nodes"][0]["timestamp"]
            first_sim_hour = self._convert_to_simulation_hours([first_ts])[0]
            self.log(f"DEBUG: First timestamp {first_ts} converts to simulation hour {first_sim_hour}")
            self.log(f"DEBUG: Using shrink factor {self.shrink_factor} for time scale conversion")
        
        for node_name in sorted(node_names):
            node_data = [n for n in self.metrics["nodes"] if n["node_name"] == node_name]
            if not node_data:
                continue
                
            # Sort by timestamp
            node_data.sort(key=lambda x: x["timestamp"])
            
            # Extract raw timestamps and use our dedicated function to convert to simulation hours
            # Always use experiment start_time for consistent time scale across all plots
            timestamps = [m["timestamp"] for m in node_data]
            sim_timestamps_hours = self._convert_to_simulation_hours(timestamps)
            
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
            plt.savefig(os.path.join(self.node_plots_dir, f"cpu_utilization_{node_name}.png"))
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
            plt.savefig(os.path.join(self.node_plots_dir, f"power_draw_{node_name}.png"))
            plt.close()
            
    def _plot_time_series_by_region(self, plt) -> None:
        """Generate time series plots showing metrics broken down by region."""
        if "nodes" not in self.metrics or not self.metrics["nodes"]:
            self.log("No node metrics data available for plotting by region")
            return
            
        # Group nodes by region
        regions = {}
        for node in self.metrics["nodes"]:
            region = node.get("region", "unknown")
            if region not in regions:
                regions[region] = []
            regions[region].append(node)
            
        # Load carbon metrics for combining with region data
        carbon_data = {}
        if "carbon_metrics" in self.metrics and self.metrics["carbon_metrics"]:
            carbon_data = {cm["timestamp"]: cm for cm in self.metrics["carbon_metrics"]}
            
        # Plot carbon intensity by region over time
        plt.figure(figsize=(12, 7))
        
        # Calculate experiment duration in simulation hours
        exp_duration_hours = (self.end_time - self.start_time) / 3600 * self.shrink_factor
        
        for region, nodes in regions.items():
            # Extract unique timestamps for this region's nodes
            timestamps = sorted(set(node["timestamp"] for node in nodes))
            
            region_carbon_intensity = []
            region_sim_hours = self._convert_to_simulation_hours(timestamps)
            
            for i, ts in enumerate(timestamps):
                
                # Default values if no specific forecast is available
                default_intensities = {
                    "DE": 350,
                    "FR": 60, 
                    "ES": 200,
                    "IT-NO": 300,
                    "unknown": 400
                }
                carbon_intensity = default_intensities.get(region, 300)
                
                region_carbon_intensity.append(carbon_intensity)
            
            if region_sim_hours and region_carbon_intensity:
                plt.plot(region_sim_hours, region_carbon_intensity, 
                       label=f"{region} (default)", color=self.colors["regions"].get(region, "#7f7f7f"),
                       linestyle='--')  # Use dashed lines for default values
                
        plt.xlabel("Simulation Time (hours)")
        plt.ylabel("Carbon Intensity (g CO₂/kWh)")
        plt.title("Carbon Intensity by Region Over Time")
        plt.grid(True)
        plt.legend()
        plt.tight_layout()
        plt.savefig(os.path.join(self.carbon_plots_dir, "carbon_intensity_by_region.png"))
        plt.close()
        
    def _create_carbon_heatmap(self, plt) -> None:
        """Create carbon intensity heatmap by region and time."""
        import json
        
        # Load carbon intensity data from all_forecasts.json
        forecasts_path = "/root/carbon/scripts/all_forecasts.json"
        try:
            with open(forecasts_path, 'r') as f:
                forecasts_data = json.load(f)
        except Exception as e:
            self.log(f"Error loading forecasts from {forecasts_path}: {e}")
            # Fall back to local path if absolute path doesn't work
            try:
                local_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "all_forecasts.json")
                with open(local_path, 'r') as f:
                    forecasts_data = json.load(f)
            except Exception as e2:
                self.log(f"Error loading forecasts from fallback path: {e2}")
                return
            
        # Get regions from forecasts data
        regions = sorted(forecasts_data.keys())
        if not regions:
            self.log("No region data found in forecasts file")
            return
            
        # Get all hours from the first region (assuming all regions have the same time points)
        if not forecasts_data[regions[0]].get("forecast"):
            self.log("Invalid forecast data structure")
            return
            
        # Extract hours for x-axis - use all 25 hourly data points (0-24h) 
        hour_buckets = list(range(0, 25))  # Every hour up to 25 hours (0-24)
        
        # Handle NumPy compatibility - using inf_value from numpy
        # This ensures consistent values regardless of NumPy version
        inf_value = np.inf
        
        # Ensure np.Inf is available (it's handled by our patch at the top of the file)
        if not hasattr(np, 'Inf'):
            np.__dict__['Inf'] = np.inf
        
        # Create matrix for heatmap [region × hour]
        heatmap_data = np.zeros((len(regions), len(hour_buckets)))
        
        # For each region and hour, get the carbon intensity
        for i, region in enumerate(regions):
            # Get the region's forecast data
            region_data = forecasts_data.get(region, {})
            region_forecasts = region_data.get("forecast", [])
            
            # Create a direct mapping of hour index to carbon intensity
            forecast_by_hour = {}
            
            # Process forecast data - simply use entry index as the hour
            # This assumes each entry represents one consecutive hour
            if region_forecasts:
                for idx, entry in enumerate(region_forecasts):
                    if "carbonIntensity" in entry:
                        forecast_by_hour[idx] = entry["carbonIntensity"]
            
            # Map the forecast data to our hour buckets - direct 1:1 mapping
            for j, hour in enumerate(hour_buckets):
                # Get the exact hour data when available
                if hour in forecast_by_hour:
                    heatmap_data[i, j] = forecast_by_hour[hour]
                elif region_forecasts and hour < len(region_forecasts):
                    # Fallback: use the index directly if available
                    heatmap_data[i, j] = region_forecasts[hour].get("carbonIntensity", 0)
                else:
                    # Default values when no forecast is available
                    default_values = {
                        "DE": 350,
                        "FR": 60,
                        "ES": 200,
                        "IT-NO": 300
                    }
                    heatmap_data[i, j] = default_values.get(region, 300)
                    heatmap_data[i, j] = 0
        
        # Create heatmap
        plt.figure(figsize=(12, 8))
        
        # Use a color map that goes from green (low carbon) to red (high carbon)
        cmap = plt.cm.RdYlGn_r  # Red-Yellow-Green reversed
        
        # Calculate reasonable min/max for better color contrast
        vmin = np.percentile(heatmap_data[heatmap_data > 0], 5)  # 5th percentile
        vmax = np.percentile(heatmap_data[heatmap_data > 0], 95)  # 95th percentile
        
        im = plt.imshow(heatmap_data, cmap=cmap, aspect='auto', vmin=vmin, vmax=vmax)
        plt.colorbar(im, label="Carbon Intensity (g CO₂/kWh)")
        
        # Add labels
        plt.yticks(range(len(regions)), regions)
        
        # For 25 hours, show tick marks every 3 hours to avoid crowding
        if len(hour_buckets) > 20:
            plt.xticks(range(0, len(hour_buckets), 3), [f"{hour_buckets[i]}h" for i in range(0, len(hour_buckets), 3)])
        else:
            # For fewer hours, we can show every second hour
            plt.xticks(range(0, len(hour_buckets), 2), [f"{hour_buckets[i]}h" for i in range(0, len(hour_buckets), 2)])
        
        plt.xlabel("Simulation Time (hours)")
        plt.ylabel("Region")
        plt.title("Carbon Intensity Heatmap by Region and Time")
        
        plt.tight_layout()
        heatmap_path = os.path.join(self.carbon_plots_dir, "carbon_intensity_heatmap.png")
        plt.savefig(heatmap_path)
        self.log(f"Carbon intensity heatmap saved to: {heatmap_path}")
        plt.close()
        
    def _load_all_experiment_results(self) -> list:
        """Load results from all experiments in the top-level benchmark_results directory."""
        experiments = []
        benchmark_root = os.path.dirname(self.data_dir)
        
        # Skip if we don't have a valid benchmark_results directory
        if not os.path.basename(benchmark_root) == "benchmark_results":
            self.log("Current directory is not inside benchmark_results, skipping comparison")
            return experiments
            
        # List all directories in the benchmark_results folder (top-level only)
        for exp_dir in os.listdir(benchmark_root):
            exp_path = os.path.join(benchmark_root, exp_dir)
            
            # Skip if not a directory or if it's an "archive" directory
            if not os.path.isdir(exp_path) or exp_dir == "archive":
                continue
                
            # Skip directories without a results.json file
            results_file = os.path.join(exp_path, "results.json")
            if not os.path.exists(results_file):
                continue
                
            try:
                with open(results_file, 'r') as f:
                    results = json.load(f)
                    
                # Add the experiment name and directory to the results
                if "experiment_name" not in results:
                    results["experiment_name"] = exp_dir
                results["directory"] = exp_path
                
                # Check if this experiment has the required metrics
                if (results.get("carbon_metrics") and results.get("performance_metrics") and
                    "total_carbon_emissions_g" in results["carbon_metrics"] and
                    "avg_scheduling_latency_seconds" in results["performance_metrics"]):
                    experiments.append(results)
            except Exception as e:
                self.log(f"Error loading results from {exp_dir}: {e}")
                
        self.log(f"Loaded results from {len(experiments)} experiments for comparison")
        return experiments
    
    def _plot_performance_emissions_tradeoff(self, plt, summary=None) -> None:
        """Create a plot showing the trade-off between performance and emissions."""
        if not summary:
            summary = self.calculate_summary_statistics()
            
        # We need both carbon metrics and performance metrics
        if not summary.get("carbon_metrics") or not summary.get("performance_metrics"):
            self.log("Insufficient data for performance-emissions trade-off plot")
            return
            
        # Get results from all experiments
        all_experiments = self._load_all_experiment_results()
        
        # Create scatter plot
        plt.figure(figsize=(12, 8))
        
        # Plot all experiments
        colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', 
                '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf']
        color_idx = 0
        
        for exp in all_experiments:
            carbon = exp["carbon_metrics"]
            perf = exp["performance_metrics"]
            
            if ("total_carbon_emissions_g" in carbon and 
                "avg_scheduling_latency_seconds" in perf and 
                perf["avg_scheduling_latency_seconds"] is not None):
                
                emissions = carbon["total_carbon_emissions_g"]
                latency = perf["avg_scheduling_latency_seconds"]
                if latency <= 0:
                    latency = 0.001  # Avoid zero values
                
                # Highlight current experiment
                if exp["experiment_name"] == self.experiment_name:
                    plt.scatter(latency, emissions, s=200, color='blue', 
                              marker='*', label=exp["experiment_name"])
                else:
                    plt.scatter(latency, emissions, s=100, 
                              color=colors[color_idx % len(colors)],
                              label=exp["experiment_name"])
                
                # Add name label - use full experiment name
                plt.annotate(exp["experiment_name"], 
                           (latency, emissions), 
                           xytext=(5, 5),
                           textcoords='offset points',
                           fontsize=9)
                           
                color_idx += 1
        
        plt.xlabel("Average Scheduling Latency (seconds)")
        plt.ylabel("Total Carbon Emissions (g CO₂)")
        plt.title("Performance vs. Carbon Emissions Trade-off (All Experiments)")
        plt.grid(True)
        
        plt.tight_layout()
        plt.savefig(os.path.join(self.comparison_plots_dir, "performance_emissions_tradeoff.png"))
        plt.close()
        
    def _create_aggregated_bar_charts(self, plt, summary=None) -> None:
        """Create bar charts for aggregated metrics comparison with other runs."""
        if not summary:
            summary = self.calculate_summary_statistics()
            
        # Check if we have data for this experiment
        if not summary.get("carbon_metrics") or not summary.get("performance_metrics"):
            self.log("Insufficient data for bar charts")
            return
            
        # Get results from all experiments
        all_experiments = self._load_all_experiment_results()
        
        # If no other experiments were found, revert to single-experiment display
        if len(all_experiments) <= 1:
            # Extract metrics with proper default values to avoid None
            total_emissions = summary["carbon_metrics"].get("total_carbon_emissions_g")
            if total_emissions is None:
                self.log("Missing total_carbon_emissions_g for bar charts, skipping")
                return
                
            total_energy = summary["carbon_metrics"].get("total_energy_consumption_kwh")
            if total_energy is None:
                self.log("Missing total_energy_consumption_kwh for bar charts, setting to 0")
                total_energy = 0
                
            avg_latency = summary["performance_metrics"].get("avg_scheduling_latency_seconds") 
            if avg_latency is None:
                self.log("Missing avg_scheduling_latency_seconds for bar charts, setting to 0")
                avg_latency = 0
                
            # Create single-experiment bar charts
            self._create_single_experiment_bar_charts(plt, total_emissions, total_energy, avg_latency)
            return
            
        # Prepare data for the multi-experiment bar charts
        experiment_names = []
        emissions_data = []
        energy_data = []
        latency_data = []
        colors = []
        
        # Color palette for bars
        palette = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', 
                  '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf']
        
        # Process each experiment
        for i, exp in enumerate(all_experiments):
            # Use the full experiment name rather than just the algorithm type
            exp_name = exp["experiment_name"]
            experiment_names.append(exp_name)
            
            # Get the metrics
            carbon = exp["carbon_metrics"]
            perf = exp["performance_metrics"]
            
            emissions_data.append(carbon.get("total_carbon_emissions_g", 0))
            energy_data.append(carbon.get("total_energy_consumption_kwh", 0))
            latency_data.append(perf.get("avg_scheduling_latency_seconds", 0) or 0)  # Convert None to 0
            
            # Highlight the current experiment with blue
            if exp["experiment_name"] == self.experiment_name:
                colors.append('#1f77b4')  # Blue for current experiment
            else:
                colors.append(palette[i % len(palette)])
                
        # Create emissions comparison bar chart
        plt.figure(figsize=(max(10, len(experiment_names)), 6))
        bar_positions = range(len(experiment_names))
        bars = plt.bar(bar_positions, emissions_data, color=colors)
        
        # Add value labels on top of bars
        for bar, value in zip(bars, emissions_data):
            height = bar.get_height()
            if height is not None and height > 0:  # Ensure we have a valid height
                plt.text(bar.get_x() + bar.get_width()/2, height + max(emissions_data)*0.01, 
                       f"{value:.1f}", ha='center', va='bottom', fontsize=9, rotation=45)
        
        plt.xlabel("Experiment")
        plt.ylabel("Total Carbon Emissions (g CO₂)")
        plt.title("Carbon Emissions Comparison Across Experiments")
        plt.xticks(bar_positions, experiment_names, rotation=45, ha="right")
        plt.tight_layout()
        plt.savefig(os.path.join(self.comparison_plots_dir, "emissions_comparison.png"))
        plt.close()
        
        # Create energy consumption comparison bar chart
        plt.figure(figsize=(max(10, len(experiment_names)), 6))
        bars = plt.bar(bar_positions, energy_data, color=colors)
        
        # Add value labels on top of bars
        for bar, value in zip(bars, energy_data):
            height = bar.get_height()
            if height is not None and height > 0:  # Ensure we have a valid height
                plt.text(bar.get_x() + bar.get_width()/2, height + max(energy_data)*0.01, 
                       f"{value:.3f}", ha='center', va='bottom', fontsize=9, rotation=45)
        
        plt.xlabel("Experiment")
        plt.ylabel("Total Energy Consumption (kWh)")
        plt.title("Energy Consumption Comparison Across Experiments")
        plt.xticks(bar_positions, experiment_names, rotation=45, ha="right")
        plt.tight_layout()
        plt.savefig(os.path.join(self.comparison_plots_dir, "energy_comparison.png"))
        plt.close()
        
        # Create scheduling latency comparison bar chart
        plt.figure(figsize=(max(10, len(experiment_names)), 6))
        bars = plt.bar(bar_positions, latency_data, color=colors)
        
        # Add value labels on top of bars
        for bar, value in zip(bars, latency_data):
            height = bar.get_height()
            if height is not None and height > 0:  # Ensure we have a valid height
                plt.text(bar.get_x() + bar.get_width()/2, height + max(latency_data)*0.01, 
                       f"{value:.2f}", ha='center', va='bottom', fontsize=9, rotation=45)
        
        plt.xlabel("Experiment")
        plt.ylabel("Average Scheduling Latency (seconds)")
        plt.title("Scheduling Performance Comparison Across Experiments")
        plt.xticks(bar_positions, experiment_names, rotation=45, ha="right")
        plt.tight_layout()
        plt.savefig(os.path.join(self.comparison_plots_dir, "latency_comparison.png"))
        plt.close()
        
    def _create_single_experiment_bar_charts(self, plt, total_emissions, total_energy, avg_latency):
        """Create bar charts for a single experiment."""
        # Create emissions comparison bar chart
        plt.figure(figsize=(10, 6))
        bar_positions = range(1)
        bars = plt.bar(bar_positions, [total_emissions], color=['blue'])
        
        # Add value labels on top of bars
        for bar, value in zip(bars, [total_emissions]):
            height = bar.get_height()
            if height is not None:  # Ensure we have a valid height
                plt.text(bar.get_x() + bar.get_width()/2, height + 5, 
                       f"{value:.1f}", ha='center', va='bottom', fontsize=10)
        
        plt.xlabel("Experiment")
        plt.ylabel("Total Carbon Emissions (g CO₂)")
        plt.title("Carbon Emissions Comparison")
        plt.xticks(bar_positions, [self.experiment_name], rotation=45, ha="right")
        plt.tight_layout()
        plt.savefig(os.path.join(self.comparison_plots_dir, "emissions_comparison.png"))
        plt.close()
        
        # Create energy consumption comparison bar chart
        plt.figure(figsize=(10, 6))
        bars = plt.bar(bar_positions, [total_energy], color=['blue'])
        
        # Add value labels on top of bars
        for bar, value in zip(bars, [total_energy]):
            height = bar.get_height()
            if height is not None:  # Ensure we have a valid height
                plt.text(bar.get_x() + bar.get_width()/2, height + 0.01, 
                       f"{value:.3f}", ha='center', va='bottom', fontsize=10)
        
        plt.xlabel("Experiment")
        plt.ylabel("Total Energy Consumption (kWh)")
        plt.title("Energy Consumption Comparison")
        plt.xticks(bar_positions, [self.experiment_name], rotation=45, ha="right")
        plt.tight_layout()
        plt.savefig(os.path.join(self.comparison_plots_dir, "energy_comparison.png"))
        plt.close()
        
        # Create scheduling latency comparison bar chart
        plt.figure(figsize=(10, 6))
        bars = plt.bar(bar_positions, [avg_latency], color=['blue'])
        
        # Add value labels on top of bars
        for bar, value in zip(bars, [avg_latency]):
            height = bar.get_height()
            if height is not None:  # Ensure we have a valid height
                plt.text(bar.get_x() + bar.get_width()/2, height + 0.1, 
                       f"{value:.2f}", ha='center', va='bottom', fontsize=10)
        
        plt.xlabel("Experiment")
        plt.ylabel("Average Scheduling Latency (seconds)")
        plt.title("Scheduling Performance Comparison")
        plt.xticks(bar_positions, [self.experiment_name], rotation=45, ha="right")
        plt.tight_layout()
        plt.savefig(os.path.join(self.comparison_plots_dir, "latency_comparison.png"))
        plt.close()
        
    def _create_algorithm_comparison_charts(self, plt, summary=None) -> None:
        """Create publication-quality charts comparing results by algorithm type."""
        if not summary:
            summary = self.calculate_summary_statistics()
            
        # Get results from all experiments
        all_experiments = self._load_all_experiment_results()
        
        if len(all_experiments) <= 1:
            self.log("Insufficient experiments for algorithm comparison charts")
            return
            
        # Import required libraries for publication-quality plots
        import numpy as np
        import scipy.stats as stats
        
        try:
            import seaborn as sns
            sns.set_style("whitegrid")
            sns.set_context("paper", font_scale=1.3)
            use_seaborn = True
        except ImportError:
            use_seaborn = False
            self.log("Seaborn not available. Falling back to matplotlib defaults.")
            
        # Group experiments by algorithm type
        algorithm_groups = {
            'vanilla': {'experiments': [], 'emissions': [], 'energy': [], 'latency': []},
            'heuristic': {'experiments': [], 'emissions': [], 'energy': [], 'latency': []},
            'global-optimal': {'experiments': [], 'emissions': [], 'energy': [], 'latency': []}
        }
        
        # Process each experiment and classify by algorithm type
        for exp in all_experiments:
            name = exp["experiment_name"]
            carbon = exp["carbon_metrics"] 
            perf = exp["performance_metrics"]
            
            # Identify algorithm type from experiment name
            algorithm_type = None
            if 'vanilla' in name:
                algorithm_type = 'vanilla'
            elif 'heuristic' in name:
                algorithm_type = 'heuristic'
            elif 'global-optimal' in name:
                algorithm_type = 'global-optimal'
            else:
                continue  # Skip experiments we can't classify
                
            # Collect metrics
            emissions = carbon.get("total_carbon_emissions_g", 0)
            energy = carbon.get("total_energy_consumption_kwh", 0)
            latency = perf.get("avg_scheduling_latency_seconds", 0) or 0  # Convert None to 0
            
            algorithm_groups[algorithm_type]['experiments'].append(name)
            algorithm_groups[algorithm_type]['emissions'].append(emissions)
            algorithm_groups[algorithm_type]['energy'].append(energy)  
            algorithm_groups[algorithm_type]['latency'].append(latency)
        
        # Calculate averages and confidence intervals for each group
        algorithm_types = []
        avg_emissions = []  
        avg_energy = []
        avg_latency = []
        ci_emissions = []
        ci_energy = []
        ci_latency = []
        sample_sizes = []
        
        confidence_level = 0.95  # 95% confidence interval
        
        for alg_type, data in algorithm_groups.items():
            if not data['experiments']:
                continue  # Skip empty groups
                
            algorithm_types.append(alg_type)
            sample_size = len(data['experiments'])
            sample_sizes.append(sample_size)
            
            # Calculate averages
            avg_emissions.append(np.mean(data['emissions']))
            avg_energy.append(np.mean(data['energy']))
            avg_latency.append(np.mean(data['latency']))
            
            # Calculate confidence intervals
            # For small samples (n<30), we use t-distribution
            if sample_size > 1:
                # For emissions
                sem_emissions = stats.sem(data['emissions'])
                ci_emissions.append(sem_emissions * stats.t.ppf((1 + confidence_level) / 2, sample_size-1))
                
                # For energy
                sem_energy = stats.sem(data['energy'])
                ci_energy.append(sem_energy * stats.t.ppf((1 + confidence_level) / 2, sample_size-1))
                
                # For latency
                sem_latency = stats.sem(data['latency'])
                ci_latency.append(sem_latency * stats.t.ppf((1 + confidence_level) / 2, sample_size-1))
            else:
                # No CI possible with single sample
                ci_emissions.append(0)
                ci_energy.append(0)
                ci_latency.append(0)
            
        # If we don't have at least two algorithm types, we can't create a comparison
        if len(algorithm_types) < 2:
            self.log("Insufficient algorithm types for comparison charts")
            return
            
        # Color mapping using a color-blind friendly palette
        colors = {
            'vanilla': '#0173B2',      # Blue 
            'heuristic': '#029E73',    # Green
            'global-optimal': '#D55E00' # Orange/Red
        }
        
        # Set publication-quality figure parameters
        plt.rcParams.update({
            'font.family': 'Times New Roman',  # Standard journal font
            'font.size': 12,
            'axes.labelsize': 14,
            'axes.titlesize': 16,
            'xtick.labelsize': 12,
            'ytick.labelsize': 12,
            'legend.fontsize': 12,
            'figure.titlesize': 18,
            'figure.dpi': 600,               # Higher DPI for print quality
            'axes.linewidth': 1.2,           # Slightly thicker axis lines
            'axes.grid': True,               # Show grid
            'grid.linestyle': '--',          # Dashed grid lines
            'grid.alpha': 0.3                # Subtle grid
        })
        
        # Create subplots for the three metrics side by side
        fig, axes = plt.subplots(1, 3, figsize=(18, 6), constrained_layout=True)
        
        # Common plotting parameters
        bar_colors = [colors.get(alg, '#999999') for alg in algorithm_types]
        x_pos = np.arange(len(algorithm_types))
        bar_width = 0.7
        edgecolor = '#333333'
        hatch_patterns = ['', '///', 'xxx']  # Distinct patterns for black and white printing
        
        # 1. Plot carbon emissions
        ax1 = axes[0]
        bars1 = ax1.bar(x_pos, avg_emissions, width=bar_width, yerr=ci_emissions, capsize=8,
                      color=bar_colors, edgecolor=edgecolor, linewidth=1.5, alpha=0.9)
        
        # Add hatching patterns for better distinction in black and white printing
        for i, bar in enumerate(bars1):
            bar.set_hatch(hatch_patterns[i % len(hatch_patterns)])
            
        ax1.set_xticks(x_pos)
        ax1.set_xticklabels([t.capitalize() for t in algorithm_types], fontweight='bold')
        ax1.set_title('Carbon Emissions', fontweight='bold')
        ax1.set_ylabel('Carbon Emissions (g CO₂)', fontweight='bold')
        ax1.spines['top'].set_visible(False)
        ax1.spines['right'].set_visible(False)
        ax1.grid(axis='y', linestyle='--', alpha=0.3)
        
        # Add minor ticks for more precise reading
        ax1.minorticks_on()
        
        # Set y limit to start slightly below zero for better visualization
        ymin = min(0, min(avg_emissions) - max(ci_emissions) - 0.05 * max(avg_emissions))
        ymax = max(avg_emissions) + max(ci_emissions) + 0.15 * max(avg_emissions)
        ax1.set_ylim(ymin, ymax)
        
        # Add sample size and value labels
        for i, (bar, value, n) in enumerate(zip(bars1, avg_emissions, sample_sizes)):
            height = bar.get_height()
            ax1.annotate(f'{value:.1f}\n(n={n})',
                        xy=(bar.get_x() + bar.get_width() / 2, height),
                        xytext=(0, 5),  # 5 points vertical offset
                        textcoords="offset points",
                        ha='center', va='bottom',
                        fontweight='bold')
        
        # 2. Plot energy consumption
        ax2 = axes[1]
        bars2 = ax2.bar(x_pos, avg_energy, width=bar_width, yerr=ci_energy, capsize=8,
                      color=bar_colors, edgecolor=edgecolor, linewidth=1.5, alpha=0.9)
                      
        # Add hatching patterns
        for i, bar in enumerate(bars2):
            bar.set_hatch(hatch_patterns[i % len(hatch_patterns)])
            
        ax2.set_xticks(x_pos)
        ax2.set_xticklabels([t.capitalize() for t in algorithm_types], fontweight='bold')
        ax2.set_title('Energy Consumption', fontweight='bold')
        ax2.set_ylabel('Energy Consumption (kWh)', fontweight='bold')
        ax2.spines['top'].set_visible(False)
        ax2.spines['right'].set_visible(False)
        ax2.grid(axis='y', linestyle='--', alpha=0.3)
        
        # Add minor ticks for more precise reading
        ax2.minorticks_on()
        
        # Set y limit to start slightly below zero for better visualization
        ymin = min(0, min(avg_energy) - max(ci_energy) - 0.05 * max(avg_energy))
        ymax = max(avg_energy) + max(ci_energy) + 0.15 * max(avg_energy)
        ax2.set_ylim(ymin, ymax)
        
        # Add sample size and value labels
        for i, (bar, value, n) in enumerate(zip(bars2, avg_energy, sample_sizes)):
            height = bar.get_height()
            ax2.annotate(f'{value:.3f}\n(n={n})',
                        xy=(bar.get_x() + bar.get_width() / 2, height),
                        xytext=(0, 5),
                        textcoords="offset points",
                        ha='center', va='bottom',
                        fontweight='bold')
        
        # 3. Plot scheduling latency
        ax3 = axes[2]
        bars3 = ax3.bar(x_pos, avg_latency, width=bar_width, yerr=ci_latency, capsize=8,
                      color=bar_colors, edgecolor=edgecolor, linewidth=1.5, alpha=0.9)
                      
        # Add hatching patterns
        for i, bar in enumerate(bars3):
            bar.set_hatch(hatch_patterns[i % len(hatch_patterns)])
            
        ax3.set_xticks(x_pos)
        ax3.set_xticklabels([t.capitalize() for t in algorithm_types], fontweight='bold')
        ax3.set_title('Scheduling Latency', fontweight='bold')
        ax3.set_ylabel('Scheduling Latency (seconds)', fontweight='bold')
        ax3.spines['top'].set_visible(False)
        ax3.spines['right'].set_visible(False)
        ax3.grid(axis='y', linestyle='--', alpha=0.3)
        
        # Add minor ticks for more precise reading
        ax3.minorticks_on()
        
        # Set y limit to start slightly below zero for better visualization
        ymin = min(0, min(avg_latency) - max(ci_latency) - 0.05 * max(avg_latency))
        ymax = max(avg_latency) + max(ci_latency) + 0.15 * max(avg_latency)
        ax3.set_ylim(ymin, ymax)
        
        # Add sample size and value labels
        for i, (bar, value, n) in enumerate(zip(bars3, avg_latency, sample_sizes)):
            height = bar.get_height()
            ax3.annotate(f'{value:.2f}\n(n={n})',
                        xy=(bar.get_x() + bar.get_width() / 2, height),
                        xytext=(0, 5),
                        textcoords="offset points", 
                        ha='center', va='bottom',
                        fontweight='bold')
        
        # Add a caption about confidence intervals
        fig.suptitle('Carbon-Aware Kubernetes Scheduler Performance Comparison', 
                   fontsize=20, fontweight='bold', y=0.98)
        
        fig.text(0.5, 0.01, 
                f'Error bars represent {confidence_level*100:.0f}% confidence intervals. '+
                f'Sample sizes (n) shown for each scheduler type.', 
                ha='center', va='bottom', fontsize=12, style='italic')
        
        # Add figure labels for publication reference (a, b, c)
        for i, ax in enumerate(axes):
            ax.text(-0.1, 1.05, chr(97 + i), transform=ax.transAxes, 
                   size=20, weight='bold')
        
        # Ensure proper spacing
        plt.tight_layout(rect=[0, 0.05, 1, 0.95])  # Leave room for suptitle and caption
        
        # Save as publication-quality figure with high DPI
        plt.savefig(os.path.join(self.comparison_plots_dir, "algorithm_type_comparison.png"), 
                   dpi=600, bbox_inches='tight')
        plt.savefig(os.path.join(self.comparison_plots_dir, "algorithm_type_comparison.pdf"), 
                   format='pdf', bbox_inches='tight')
        
        # Save as SVG for perfect vector graphics (ideal for publications)
        plt.savefig(os.path.join(self.comparison_plots_dir, "algorithm_type_comparison.svg"), 
                   format='svg', bbox_inches='tight')
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
        print(f"Plots saved to subdirectories within: {self.plots_dir}")
        print("Carbon metrics analysis complete. Performance metrics will be analyzed next (if enabled).")
        print("="*60 + "\n")

def run_perf_metrics_analyzer(data_dir: str) -> bool:
    """
    Run the performance metrics analyzer on the experiment data.
    
    Args:
        data_dir: Directory containing the experiment data
        
    Returns:
        bool: True if analysis was successful, False otherwise
    """
    log_file = os.path.join(data_dir, "performance.log")
    raw_data_dir = os.path.join(data_dir, "raw_data")
    
    # Check if the performance log exists
    if not os.path.exists(log_file):
        print(f"Performance log file not found: {log_file}")
        return False
        
    print("\n" + "="*60)
    print("Running Performance Metrics Analysis...")
    print("="*60)
    
    # Ensure output directory exists
    os.makedirs(raw_data_dir, exist_ok=True)
    
    # Get the path to the perf_metrics_analyzer.py script
    analyzer_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "perf_metrics_analyzer.py")
    
    # Run the analyzer script
    cmd = [
        "python3", 
        analyzer_script,
        "--log-file", log_file,
        "--output-dir", raw_data_dir,
        "--output-csv", "performance_metrics.csv"
    ]
    
    try:
        process = subprocess.run(cmd, check=True, capture_output=True, text=True)
        print(process.stdout)
        
        # Move generated plots to the performance plots directory
        plots_dir = os.path.join(data_dir, "plots", "performance")
        os.makedirs(plots_dir, exist_ok=True)
        
        # Copy any PNG files from raw_data to plots/performance
        for root, _, files in os.walk(raw_data_dir):
            for file in files:
                if file.endswith(".png"):
                    src = os.path.join(root, file)
                    dst = os.path.join(plots_dir, file)
                    os.replace(src, dst)
                    
        print(f"Performance metrics plots moved to: {plots_dir}")
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"Error running performance metrics analyzer: {e}")
        print(f"Error output: {e.stderr}")
        return False
    except Exception as e:
        print(f"Unexpected error running performance metrics analyzer: {e}")
        return False

def main():
    """Main function to run the metrics analyzer."""
    parser = argparse.ArgumentParser(description="Carbon-Aware Scheduler Metrics Analysis Tool")
    parser.add_argument("--data-dir", required=True,
                        help="Directory containing the collected metrics data")
    parser.add_argument("--output-dir", default=None,
                        help="Directory to save analysis results (defaults to data-dir if not specified)")
    parser.add_argument("--skip-perf", action="store_true",
                        help="Skip performance metrics analysis")
    
    args = parser.parse_args()
    
    if not os.path.isdir(args.data_dir):
        print(f"Error: Data directory not found: {args.data_dir}")
        sys.exit(1)
        
    analyzer = CarbonMetricsAnalyzer(
        data_dir=args.data_dir,
        output_dir=args.output_dir
    )
    
    analyzer.analyze_metrics()
    
    # Run performance metrics analyzer if not skipped
    if not args.skip_perf:
        run_perf_metrics_analyzer(args.data_dir)
    
if __name__ == "__main__":
    main()