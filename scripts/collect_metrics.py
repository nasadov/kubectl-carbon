#!/usr/bin/env python3

"""
Carbon-Aware Scheduler Metrics Collection Tool

This script collects metrics from a Kubernetes cluster running a carbon-aware scheduler.
It stores raw data that can be later analyzed and visualized using the analyze_metrics.py script.
"""

import argparse
import csv
import datetime
import json
import os
import subprocess
import sys
import time
from typing import Dict, List, Any, Tuple, Optional
import signal

class CarbonMetricsCollector:
    """Collects metrics from a carbon-aware scheduled Kubernetes cluster."""
    
    def __init__(self, 
                 output_dir: str, 
                 experiment_name: str,
                 collection_interval: int = 60,
                 duration: int = 3600,
                 namespace: str = "default",
                 shrink_factor: int = 1,
                 forecast_file: str = "/root/carbon-aware-orchestrator/pkg/carbon-aware/server-python/all_forecasts.json"):
        """
        Initialize the metrics collector.
        
        Args:
            output_dir: Directory to save metrics data
            experiment_name: Name of the experiment
            collection_interval: Time between metrics collection in seconds
            duration: Total duration of metrics collection in seconds
            namespace: Kubernetes namespace to monitor
            shrink_factor: The time shrink factor (simulation time = real time * shrink factor)
            forecast_file: Path to the carbon intensity forecasts file
        """
        self.output_dir = os.path.join(output_dir, experiment_name)
        self.experiment_name = experiment_name
        self.collection_interval = collection_interval
        self.duration = duration
        self.namespace = namespace
        self.shrink_factor = shrink_factor
        self.forecast_file = forecast_file
        self.start_time = None
        self.metrics = {
            "nodes": [],
            "pods": [],
            "placements": [],
            "carbon_metrics": [],
            "scheduling": [],
            "performance": []
        }
        
        # Load carbon intensity forecasts
        self.forecasts = self._load_forecasts()
        
        # Create output directory if it doesn't exist
        os.makedirs(self.output_dir, exist_ok=True)
        
        # Setup logging
        self.log_file = os.path.join(self.output_dir, "collection.log")
        
        # Initialize results file paths
        self.config_file = os.path.join(self.output_dir, "experiment_config.json")
        self.raw_data_dir = os.path.join(self.output_dir, "raw_data")
        os.makedirs(self.raw_data_dir, exist_ok=True)
        
    def _load_forecasts(self) -> Dict[str, List[Dict[str, Any]]]:
        """Load carbon intensity forecasts from file."""
        try:
            with open(self.forecast_file, 'r') as f:
                forecasts_data = json.load(f)
                
            # Convert to a more usable format
            parsed_forecasts = {}
            for region, data in forecasts_data.items():
                parsed_forecasts[region] = []
                for entry in data.get('forecast', []):
                    try:
                        # Convert datetime string to timestamp
                        dt = datetime.datetime.fromisoformat(entry['datetime'].replace('Z', '+00:00'))
                        timestamp = dt.timestamp()
                        parsed_forecasts[region].append({
                            'timestamp': timestamp,
                            'carbon_intensity': entry['carbonIntensity']
                        })
                    except (ValueError, KeyError) as e:
                        # Skip invalid entries
                        continue
                        
            return parsed_forecasts
        except Exception as e:
            self.log(f"Warning: Failed to load carbon intensity forecasts: {e}")
            self.log("Falling back to default carbon intensity values")
            return {}
        
    def get_carbon_intensity(self, region: str, timestamp: float) -> float:
        """
        Get carbon intensity for a region at a specific time.
        
        Uses real forecast data if available, otherwise falls back to defaults.
        """
        # Default values as fallback
        default_intensities = {
            "DE": 350,
            "FR": 60,
            "ES": 200,
            "IT-NO": 300,
            "unknown": 400
        }
        
        # If we have forecast data for this region, use it
        if region in self.forecasts and self.forecasts[region]:
            # Convert real timestamp to simulation time
            sim_time = self.start_time + ((timestamp - self.start_time) * self.shrink_factor)
            
            # Find the closest forecast entry
            forecast_entries = self.forecasts[region]
            
            if forecast_entries:
                # Sort by absolute time difference to find closest match
                closest_entry = min(forecast_entries, 
                                   key=lambda x: abs(x['timestamp'] - sim_time))
                                   
                return closest_entry['carbon_intensity']
        
        # Fall back to default if no forecast or error
        return default_intensities.get(region, default_intensities["unknown"])
        
    def log(self, message: str) -> None:
        """Log a message to the log file and stdout."""
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_message = f"[{timestamp}] {message}"
        print(log_message)
        with open(self.log_file, "a") as f:
            f.write(log_message + "\n")
            
    def run_kubectl(self, command: List[str]) -> str:
        """Run a kubectl command and return the output."""
        try:
            full_command = ["kubectl"] + command
            result = subprocess.run(full_command, capture_output=True, text=True, check=True)
            return result.stdout
        except subprocess.CalledProcessError as e:
            self.log(f"Error running kubectl command: {e}")
            self.log(f"Error output: {e.stderr}")
            return ""
            
    def collect_node_metrics(self) -> List[Dict[str, Any]]:
        """Collect metrics about nodes in the cluster."""
        self.log(f"Collecting node metrics...")
        node_metrics = []
        
        # Get all nodes in JSON format
        nodes_json = self.run_kubectl(["get", "nodes", "-o", "json"])
        if not nodes_json:
            self.log("Failed to collect node metrics")
            return node_metrics
        
        nodes_data = json.loads(nodes_json)
        
        for node in nodes_data.get("items", []):
            node_name = node.get("metadata", {}).get("name", "unknown")
            annotations = node.get("metadata", {}).get("annotations", {})
            labels = node.get("metadata", {}).get("labels", {})
            
            # Extract carbon and power information from annotations
            embodied_emissions = self._clean_and_parse_float(annotations.get("hardware.carbon/embodied_emissions", "0"))
            lifetime_years = self._clean_and_parse_float(annotations.get("hardware.carbon/lifetime_years", "0"))
            idle_watts = self._clean_and_parse_float(annotations.get("hardware.power/idle_watts", "0"))
            active_watts = self._clean_and_parse_float(annotations.get("hardware.power/active_watts", "0"))
            max_watts = self._clean_and_parse_float(annotations.get("hardware.power/max_watts", "0"))
            
            # Get node resource utilization
            cpu_capacity = node.get("status", {}).get("capacity", {}).get("cpu", "0")
            cpu_allocatable = node.get("status", {}).get("allocatable", {}).get("cpu", "0")
            memory_capacity = node.get("status", {}).get("capacity", {}).get("memory", "0")
            memory_allocatable = node.get("status", {}).get("allocatable", {}).get("memory", "0")
            
            # Get region and hardware subcategory
            region = labels.get("topology.kubernetes.io/region", "unknown")
            subcategory = labels.get("hardware.carbon/subcategory", "unknown")
            
            # Get actual CPU utilization (by summing all container requests on the node)
            cmd = ["get", "pods", "--field-selector", f"spec.nodeName={node_name}", 
                   "-A", "-o", "json"]
            pods_json = self.run_kubectl(cmd)
            cpu_used = 0.0
            memory_used = 0.0
            
            if pods_json:
                pods_data = json.loads(pods_json)
                for pod in pods_data.get("items", []):
                    for container in pod.get("spec", {}).get("containers", []):
                        requests = container.get("resources", {}).get("requests", {})
                        cpu_req = requests.get("cpu", "0")
                        memory_req = requests.get("memory", "0")
                        
                        # Convert CPU request to numeric value
                        if isinstance(cpu_req, str):
                            if cpu_req.endswith("m"):
                                cpu_used += float(cpu_req[:-1]) / 1000
                            else:
                                try:
                                    cpu_used += float(cpu_req)
                                except ValueError:
                                    pass
                                    
                        # Simplified memory calculations
            
            # Calculate CPU utilization percentage
            cpu_capacity_num = self._parse_cpu_value(cpu_capacity)
            cpu_utilization = (cpu_used / cpu_capacity_num) * 100 if cpu_capacity_num > 0 else 0
            
            # Calculate power draw based on utilization (linear model)
            power_draw = idle_watts + (active_watts - idle_watts) * (cpu_utilization / 100)
            
            # Calculate embodied carbon per second
            lifetime_seconds = lifetime_years * 365 * 24 * 3600
            embodied_per_second = embodied_emissions / lifetime_seconds if lifetime_seconds > 0 else 0
            
            node_metric = {
                "timestamp": time.time(),
                "node_name": node_name,
                "region": region,
                "subcategory": subcategory,
                "embodied_emissions": embodied_emissions,
                "lifetime_years": lifetime_years,
                "idle_watts": idle_watts,
                "active_watts": active_watts,
                "max_watts": max_watts,
                "cpu_capacity": cpu_capacity,
                "cpu_used": cpu_used,
                "cpu_utilization": cpu_utilization,
                "power_draw": power_draw,
                "embodied_carbon_rate": embodied_per_second
            }
            
            node_metrics.append(node_metric)
            
        return node_metrics
    
    def collect_pod_metrics(self) -> List[Dict[str, Any]]:
        """Collect metrics about pod placements and performance."""
        self.log(f"Collecting pod metrics...")
        pod_metrics = []
        
        pods_json = self.run_kubectl(["get", "pods", "-n", self.namespace, "-o", "json"])
        if not pods_json:
            self.log("Failed to collect pod metrics")
            return pod_metrics
            
        pods_data = json.loads(pods_json)
        
        for pod in pods_data.get("items", []):
            pod_name = pod.get("metadata", {}).get("name", "unknown")
            node_name = pod.get("spec", {}).get("nodeName", "unscheduled")
            phase = pod.get("status", {}).get("phase", "Unknown")
            scheduler_name = pod.get("spec", {}).get("schedulerName", "default-scheduler")
            
            # Get carbon-aware annotations
            annotations = pod.get("metadata", {}).get("annotations", {})
            duration_hours = annotations.get("scheduling.carbon/duration_hours", "0")
            deadline_hours = annotations.get("scheduling.carbon/deadline_hours", "0")
            
            # Get timestamps
            creation_timestamp = pod.get("metadata", {}).get("creationTimestamp", "")
            start_time = pod.get("status", {}).get("startTime", "")
            
            # Calculate scheduling latency if both timestamps exist
            scheduling_latency = None
            if creation_timestamp and start_time:
                creation_dt = datetime.datetime.fromisoformat(creation_timestamp.replace("Z", "+00:00"))
                start_dt = datetime.datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                scheduling_latency = (start_dt - creation_dt).total_seconds()
            
            # Get container resource usage
            cpu_request = 0
            memory_request = 0
            for container in pod.get("spec", {}).get("containers", []):
                requests = container.get("resources", {}).get("requests", {})
                cpu_req = requests.get("cpu", "0")
                memory_req = requests.get("memory", "0")
                
                # Convert CPU request to numeric value
                if isinstance(cpu_req, str):
                    if cpu_req.endswith("m"):
                        cpu_request += float(cpu_req[:-1]) / 1000
                    else:
                        try:
                            cpu_request += float(cpu_req)
                        except ValueError:
                            pass
            
            pod_metric = {
                "timestamp": time.time(),
                "pod_name": pod_name,
                "node_name": node_name,
                "phase": phase,
                "scheduler_name": scheduler_name,
                "duration_hours": duration_hours,
                "deadline_hours": deadline_hours,
                "creation_timestamp": creation_timestamp,
                "start_time": start_time,
                "scheduling_latency": scheduling_latency,
                "cpu_request": cpu_request
            }
            
            pod_metrics.append(pod_metric)
            
        return pod_metrics
    
    def collect_placement_metrics(self) -> List[Dict[str, Any]]:
        """Collect metrics about FAPlacement resources if they exist."""
        self.log(f"Collecting FAPlacement metrics...")
        placement_metrics = []
        
        # Check if FAPlacement CRD exists
        crd_check = self.run_kubectl(["get", "crd", "faplacements.fogatlas.fbk.eu", "--ignore-not-found"])
        if not crd_check:
            self.log("FAPlacement CRD not found, skipping collection")
            return placement_metrics
            
        placements_json = self.run_kubectl(["get", "faplacements", "-n", self.namespace, "-o", "json"])
        if not placements_json:
            self.log("No FAPlacement resources found")
            return placement_metrics
            
        placements_data = json.loads(placements_json)
        
        for placement in placements_data.get("items", []):
            placement_name = placement.get("metadata", {}).get("name", "unknown")
            microservice = placement.get("spec", {}).get("microservice", "unknown")
            updated_at = placement.get("spec", {}).get("updatedAt", 0)
            
            # Extract node scores
            replica_scores = placement.get("spec", {}).get("replicaScoreList", [])
            for i, replica in enumerate(replica_scores):
                node_scores = replica.get("nodeScoreList", [])
                for node_score in node_scores:
                    node_name = node_score.get("node", "unknown")
                    score = node_score.get("score", 0)
                    
                    placement_metric = {
                        "timestamp": time.time(),
                        "placement_name": placement_name,
                        "microservice": microservice,
                        "updated_at": updated_at,
                        "replica_index": i,
                        "node_name": node_name,
                        "score": score
                    }
                    
                    placement_metrics.append(placement_metric)
                    
        return placement_metrics
    
    def collect_scheduling_events(self) -> List[Dict[str, Any]]:
        """Collect Kubernetes events related to scheduling."""
        self.log(f"Collecting scheduling events...")
        scheduling_metrics = []
        
        events_json = self.run_kubectl(["get", "events", "-n", self.namespace, "-o", "json"])
        if not events_json:
            self.log("Failed to collect events")
            return scheduling_metrics
            
        events_data = json.loads(events_json)
        
        for event in events_data.get("items", []):
            if event.get("reason") in ["Scheduled", "FailedScheduling"]:
                event_type = event.get("type", "Unknown")
                reason = event.get("reason", "Unknown")
                message = event.get("message", "")
                involved_object = event.get("involvedObject", {})
                object_kind = involved_object.get("kind", "Unknown")
                object_name = involved_object.get("name", "unknown")
                timestamp = event.get("firstTimestamp", "")
                
                scheduling_metric = {
                    "timestamp": time.time(),
                    "event_type": event_type,
                    "reason": reason,
                    "message": message,
                    "object_kind": object_kind,
                    "object_name": object_name,
                    "event_timestamp": timestamp
                }
                
                scheduling_metrics.append(scheduling_metric)
                
        return scheduling_metrics
    
    def calculate_performance_metrics(self) -> Dict[str, Any]:
        """Calculate aggregate performance metrics."""
        self.log(f"Calculating performance metrics...")
        
        # Metrics we'll calculate
        performance = {
            "timestamp": time.time(),
            "avg_scheduling_latency": None,
            "p95_scheduling_latency": None,
            "throughput": None,  # Pods scheduled per minute
            "running_pods": 0,
            "pending_pods": 0,
            "failed_pods": 0
        }
        
        # Get pod states
        pod_states = {"Running": 0, "Pending": 0, "Failed": 0}
        pods_json = self.run_kubectl(["get", "pods", "-n", self.namespace, "--no-headers"])
        for line in pods_json.strip().split("\n"):
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 3:
                state = parts[2]
                if state in pod_states:
                    pod_states[state] += 1
                    
        performance["running_pods"] = pod_states["Running"]
        performance["pending_pods"] = pod_states["Pending"]
        performance["failed_pods"] = pod_states["Failed"]
        
        # Calculate scheduling latency from pod metrics
        if len(self.metrics["pods"]) > 0:
            latencies = []
            for pod_metric in self.metrics["pods"]:
                if pod_metric.get("scheduling_latency") is not None:
                    latencies.append(pod_metric["scheduling_latency"])
                    
            if latencies:
                latencies.sort()
                performance["avg_scheduling_latency"] = sum(latencies) / len(latencies)
                p95_index = int(len(latencies) * 0.95)
                performance["p95_scheduling_latency"] = latencies[p95_index] if p95_index < len(latencies) else latencies[-1]
                
        # Calculate throughput (pods completed per minute)
        if self.start_time:
            elapsed_minutes = (time.time() - self.start_time) / 60.0
            if elapsed_minutes > 0:
                performance["throughput"] = pod_states["Running"] / elapsed_minutes
                
        return performance
    
    def calculate_carbon_metrics(self) -> Dict[str, Any]:
        """Calculate carbon-related metrics from node data."""
        self.log(f"Calculating carbon metrics...")
        
        # Initialize carbon metrics
        carbon_metrics = {
            "timestamp": time.time(),
            "total_power_watts": 0,
            "total_embodied_carbon_rate": 0,
            "total_operational_carbon_rate": 0,
            "total_carbon_rate": 0,
            "carbon_intensity": 0,
            "energy_consumption_kwh": 0
        }
        
        # If we have node metrics, calculate carbon metrics
        if len(self.metrics["nodes"]) > 0:
            latest_nodes = [n for n in self.metrics["nodes"] if n["timestamp"] == self.metrics["nodes"][-1]["timestamp"]]
            
            # Track weighted carbon intensity for later average calculation
            total_weighted_intensity = 0
            total_power = 0
            
            for node in latest_nodes:
                region = node.get("region", "unknown")
                power_draw = node.get("power_draw", 0)
                embodied_carbon_rate = node.get("embodied_carbon_rate", 0)
                
                # Get current carbon intensity for this region using real forecast data
                carbon_intensity = self.get_carbon_intensity(region, carbon_metrics["timestamp"])
                
                # Calculate operational carbon (watts * gCO2/kWh) - convert watts to kW
                operational_carbon_rate = (power_draw / 1000) * carbon_intensity / 3600  # gCO2/sec
                
                # Update totals
                carbon_metrics["total_power_watts"] += power_draw
                carbon_metrics["total_embodied_carbon_rate"] += embodied_carbon_rate
                carbon_metrics["total_operational_carbon_rate"] += operational_carbon_rate
                carbon_metrics["total_carbon_rate"] += (embodied_carbon_rate + operational_carbon_rate)
                
                # Track weighted intensity (weighted by power usage)
                total_weighted_intensity += carbon_intensity * power_draw
                total_power += power_draw
                
            # Calculate overall carbon intensity (weighted average)
            if total_power > 0:
                carbon_metrics["carbon_intensity"] = total_weighted_intensity / total_power
                
            # Calculate energy consumption since last collection (kWh)
            if len(self.metrics["carbon_metrics"]) > 0:
                last_ts = self.metrics["carbon_metrics"][-1]["timestamp"]
                elapsed_hours = (carbon_metrics["timestamp"] - last_ts) / 3600
                carbon_metrics["energy_consumption_kwh"] = (carbon_metrics["total_power_watts"] / 1000) * elapsed_hours
            
        return carbon_metrics
    
    def collect_metrics_once(self) -> None:
        """Collect all metrics once and store them."""
        try:
            # Collect raw metrics
            node_metrics = self.collect_node_metrics()
            pod_metrics = self.collect_pod_metrics()
            placement_metrics = self.collect_placement_metrics()
            scheduling_metrics = self.collect_scheduling_events()
            
            # Store raw metrics
            self.metrics["nodes"].extend(node_metrics)
            self.metrics["pods"].extend(pod_metrics)
            self.metrics["placements"].extend(placement_metrics)
            self.metrics["scheduling"].extend(scheduling_metrics)
            
            # Calculate derived metrics
            carbon_metrics = self.calculate_carbon_metrics()
            performance_metrics = self.calculate_performance_metrics()
            
            # Store derived metrics
            self.metrics["carbon_metrics"].append(carbon_metrics)
            self.metrics["performance"].append(performance_metrics)
            
            # Write metrics to CSV files for real-time analysis
            self._write_latest_metrics_to_csv(node_metrics, "nodes")
            self._write_latest_metrics_to_csv(pod_metrics, "pods")
            self._write_latest_metrics_to_csv([carbon_metrics], "carbon")
            self._write_latest_metrics_to_csv([performance_metrics], "performance")
            
        except Exception as e:
            self.log(f"Error collecting metrics: {e}")
    
    def collect_metrics(self) -> None:
        """Collect metrics at regular intervals until signaled to stop."""
        self.start_time = time.time()
        self.log(f"Starting metrics collection")
        self.log(f"Collection interval: {self.collection_interval} seconds")
        self.log(f"Output directory: {self.output_dir}")
        
        # Save experiment configuration
        config = {
            "experiment_name": self.experiment_name,
            "start_time": self.start_time,
            "collection_interval": self.collection_interval,
            "namespace": self.namespace,
            "shrink_factor": self.shrink_factor,
            "using_real_forecasts": bool(self.forecasts),
            "forecast_file": self.forecast_file
        }
        
        with open(self.config_file, 'w') as f:
            json.dump(config, f, indent=2)
            
        # Create a signal handler to allow graceful termination
        def signal_handler(sig, frame):
            self.log("Received termination signal, finalizing metrics collection...")
            self._finalize_collection(config)
            sys.exit(0)
            
        # Register signal handler for SIGINT (Ctrl+C) and SIGTERM
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        self.log("Metrics collection started. Press Ctrl+C to stop and save results.")
        self.log("Collection will continue until all workloads are processed.")
        
        try:
            # Keep collecting metrics until stopped by signal
            while True:
                self.collect_metrics_once()
                time.sleep(self.collection_interval)
                
                # Optional: Check for experiment completion condition
                # For example, we could stop if no pods are pending and all are running
                # or if all expected pods have been scheduled
                
        except Exception as e:
            self.log(f"Error during metrics collection: {e}")
            
        finally:
            self._finalize_collection(config)
            
    def _finalize_collection(self, config):
        """Finalize the collection and save results."""
        # Update configuration with actual end time
        config["end_time"] = time.time()
        with open(self.config_file, 'w') as f:
            json.dump(config, f, indent=2)
        
        self.log("Metrics collection completed")
        self.save_results()
        
    def save_results(self) -> None:
        """Save all collected metrics to files."""
        self.log("Saving metrics data...")
        
        # Save raw time series data
        for metric_name, metric_data in self.metrics.items():
            file_path = os.path.join(self.raw_data_dir, f"{metric_name}.json")
            with open(file_path, "w") as f:
                json.dump(metric_data, f, indent=2)
                
        self.log(f"Raw data saved to {self.raw_data_dir}")
        self.log("To analyze these metrics, run: python scripts/analyze_metrics.py --data-dir " + self.output_dir)
    
    def _write_latest_metrics_to_csv(self, metrics: List[Dict[str, Any]], name: str) -> None:
        """Write the latest metrics to a CSV file for real-time analysis."""
        if not metrics:
            return
            
        csv_file = os.path.join(self.raw_data_dir, f"{name}.csv")
        file_exists = os.path.isfile(csv_file)
        
        with open(csv_file, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=metrics[0].keys())
            if not file_exists:
                writer.writeheader()
            writer.writerows(metrics)
    
    def _parse_cpu_value(self, cpu_str: str) -> float:
        """Parse a CPU value string to a float."""
        try:
            if cpu_str.endswith("m"):
                return float(cpu_str[:-1]) / 1000
            return float(cpu_str)
        except (ValueError, AttributeError):
            return 0.0

    def _clean_and_parse_float(self, value: str) -> float:
        """Clean up a string value and parse it as a float."""
        try:
            # Remove any non-numeric characters (e.g., units or comments)
            cleaned_value = ''.join(c for c in value if c.isdigit() or c == '.')
            return float(cleaned_value)
        except (ValueError, TypeError):
            return 0.0

def main():
    """Main function to run the metrics collector."""
    parser = argparse.ArgumentParser(description="Carbon-Aware Scheduler Metrics Collection Tool")
    parser.add_argument("--output-dir", default="/root/carbon/benchmark_results",
                        help="Directory to save metrics data")
    parser.add_argument("--name", default=f"carbon_benchmark_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}",
                        help="Name of the experiment")
    parser.add_argument("--interval", type=int, default=60,
                        help="Metrics collection interval in seconds")
    parser.add_argument("--duration", type=int, default=3600,
                        help="Total duration of metrics collection in seconds")
    parser.add_argument("--namespace", default="default",
                        help="Kubernetes namespace to monitor")
    parser.add_argument("--shrink-factor", type=int, default=1,
                        help="Time shrink factor (simulation time = real time * shrink factor)")
    parser.add_argument("--forecast-file",
                        default="/root/carbon-aware-orchestrator/pkg/carbon-aware/server-python/all_forecasts.json",
                        help="Path to the carbon intensity forecasts file")
    
    args = parser.parse_args()
    
    collector = CarbonMetricsCollector(
        output_dir=args.output_dir,
        experiment_name=args.name,
        collection_interval=args.interval,
        duration=args.duration,
        namespace=args.namespace,
        shrink_factor=args.shrink_factor,
        forecast_file=args.forecast_file
    )
    
    collector.collect_metrics()
    
if __name__ == "__main__":
    main()