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
import math
import os
import subprocess
import sys
import time
from typing import Dict, List, Any, Tuple, Optional
import signal
import math
import requests
import re
import glob
from datetime import datetime

class CarbonMetricsCollector:
    """Collects metrics from a carbon-aware scheduled Kubernetes cluster."""
    
    def __init__(self, 
                 output_dir: str, 
                 experiment_name: str,
                 collection_interval: int = None,  # Changed to None as default
                 duration: int = 3600,
                 namespace: str = "default",
                 shrink_factor: int = 1,
                 forecast_file: str = "/root/carbon/scripts/all_forecasts.json"):
        """
        Initialize the metrics collector.
        
        Args:
            output_dir: Directory to save metrics data
            experiment_name: Name of the experiment
            collection_interval: Time between metrics collection in seconds (ignored - always calculated as 3600/shrink_factor)
            duration: Total duration of metrics collection in seconds
            namespace: Kubernetes namespace to monitor
            shrink_factor: The time shrink factor (simulation time = real time * shrink factor)
                           1 real second = shrink_factor simulation seconds
                           With default of 60, 1 real second = 1 simulation minute
            forecast_file: Path to the carbon intensity forecasts file
        """
        self.output_dir = os.path.join(output_dir, experiment_name)
        self.experiment_name = experiment_name
        # Always calculate collection interval based on shrink factor
        self.collection_interval = int(3600 / shrink_factor)
        self.duration = duration
        self.namespace = namespace
        self.shrink_factor = shrink_factor
        self.forecast_file = forecast_file
        self.start_time = None
        self.sim_start_time = None  # Simulation time reference point
        self.metrics = {
            "nodes": [],
            "pods": [],
            "placements": [],
            "carbon_metrics": [],
            "scheduling": [],
            "performance": []
        }
        
        # Create output directory if it doesn't exist
        os.makedirs(self.output_dir, exist_ok=True)
        
        # Setup logging
        self.log_file = os.path.join(self.output_dir, "collection.log")
        
        # Load carbon intensity forecasts first so we can log info about them
        self.forecasts = self._load_forecasts()
        self.log(f"Using forecast file: {self.forecast_file}")
        
        # Initialize results file paths
        self.config_file = os.path.join(self.output_dir, "experiment_config.json")
        self.raw_data_dir = os.path.join(self.output_dir, "raw_data")
        os.makedirs(self.raw_data_dir, exist_ok=True)
        
        # Create directory for region-specific metrics
        self.region_data_dir = os.path.join(self.raw_data_dir, "regions")
        os.makedirs(self.region_data_dir, exist_ok=True)
        
        # Track all pod placements for vanilla experiments
        self._all_vanilla_placements = []
        self._seen_pod_placements = set()  # Track which pods we've already recorded
        
    def _load_forecasts(self) -> Dict[str, List[Dict[str, Any]]]:
        """Load carbon intensity forecasts from file."""
        try:
            if not os.path.exists(self.forecast_file):
                self.log(f"ERROR: Forecast file not found: {self.forecast_file}")
                return {}
                
            self.log(f"Loading forecasts from: {self.forecast_file}")
            with open(self.forecast_file, 'r') as f:
                forecasts_data = json.load(f)
                
            # Log basic forecast information
            regions = list(forecasts_data.keys())
            self.log(f"Found forecast data for {len(regions)} regions: {', '.join(regions)}")
                
            # Convert to a more usable format
            parsed_forecasts = {}
            for region, data in forecasts_data.items():
                parsed_forecasts[region] = []
                
                # Check if we have forecast data in the expected format
                if not isinstance(data, dict) or 'forecast' not in data:
                    self.log(f"WARNING: Missing 'forecast' key for region {region}")
                    continue
                    
                forecast_entries = data.get('forecast', [])
                self.log(f"Region {region}: Found {len(forecast_entries)} forecast entries")
                
                for entry in forecast_entries:
                    try:
                        # Convert datetime string to timestamp
                        dt_str = entry.get('datetime')
                        if not dt_str:
                            continue
                            
                        # Handle different datetime formats
                        if 'Z' in dt_str:
                            dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
                        elif 'T' in dt_str and '+' not in dt_str and '-' in dt_str:
                            # Add UTC timezone if missing
                            dt = datetime.fromisoformat(dt_str + '+00:00')
                        else:
                            dt = datetime.fromisoformat(dt_str)
                            
                        timestamp = dt.timestamp()
                        
                        carbon_intensity = entry.get('carbonIntensity')
                        if carbon_intensity is None:
                            continue
                            
                        parsed_forecasts[region].append({
                            'timestamp': timestamp,
                            'carbon_intensity': carbon_intensity
                        })
                    except (ValueError, KeyError) as e:
                        self.log(f"WARNING: Invalid forecast entry for region {region}: {e}")
                        continue
                
                # Sort entries by timestamp
                parsed_forecasts[region].sort(key=lambda x: x['timestamp'])
                
                # Log the time range of forecasts
                if parsed_forecasts[region]:
                    first_dt = datetime.fromtimestamp(parsed_forecasts[region][0]['timestamp'])
                    last_dt = datetime.fromtimestamp(parsed_forecasts[region][-1]['timestamp'])
                    self.log(f"Region {region}: Forecasts from {first_dt} to {last_dt}")
            
            # Final validation
            if not any(entries for entries in parsed_forecasts.values()):
                self.log("WARNING: No valid forecast entries were found")
            else:
                self.log(f"Successfully loaded carbon intensity forecasts for {len(parsed_forecasts)} regions")
                
            return parsed_forecasts
        except json.JSONDecodeError as e:
            self.log(f"ERROR: Failed to parse forecast file - invalid JSON: {e}")
            return {}
        except Exception as e:
            self.log(f"ERROR: Failed to load carbon intensity forecasts: {e}")
            self.log("Falling back to default carbon intensity values")
            return {}
        
    def get_carbon_intensity(self, region: str, timestamp: float) -> float:
        """
        Get carbon intensity for a region at a specific time.
        
        Uses real forecast data if available, otherwise falls back to defaults.
        Each call returns the next forecast point in sequence, regardless of timestamp.
        """
        # Default values as fallback
        default_intensities = {
            "DE": 350,
            "FR": 60,
            "ES": 200,
            "IT-NO": 300,
            "unknown": 400
        }
        
        # First check if we have forecast data for this region
        if region in self.forecasts and self.forecasts[region]:
            # If this is our first lookup, initialize counters
            if not hasattr(self, '_forecast_index'):
                self._forecast_index = {}
                
            # Initialize index for this region if not done yet
            if region not in self._forecast_index:
                self._forecast_index[region] = 0
                
            # Get forecast entries for this region
            forecast_entries = self.forecasts[region]
            if not forecast_entries:
                return default_intensities.get(region, default_intensities["unknown"])
                
            # Get current index and increment it
            current_index = self._forecast_index[region]
            self._forecast_index[region] = (current_index + 1) % len(forecast_entries)
            
            # Get carbon intensity from current index
            carbon_value = forecast_entries[current_index]['carbon_intensity']
            
            # Log occasionally for debugging
            if not hasattr(self, '_carbon_intensity_call_count'):
                self._carbon_intensity_call_count = {}
            if region not in self._carbon_intensity_call_count:
                self._carbon_intensity_call_count[region] = 0
            
            self._carbon_intensity_call_count[region] += 1
                
            if self._carbon_intensity_call_count[region] % 10 == 1:  # Log every 10th call
                self.log(f"Using forecast for {region}: {carbon_value} gCO₂/kWh " +
                         f"(forecast index: {current_index}/{len(forecast_entries)})")
            
            return carbon_value
        
        # If we reached here, we're falling back to default values
        if not hasattr(self, '_carbon_intensity_fallback_logged'):
            self._carbon_intensity_fallback_logged = {}
            
        if region not in self._carbon_intensity_fallback_logged:
            # Log the fallback once per region
            self._carbon_intensity_fallback_logged[region] = True
            self.log(f"WARNING: Using default carbon intensity for {region}: {default_intensities.get(region, default_intensities['unknown'])} gCO₂/kWh")
            
        return default_intensities.get(region, default_intensities["unknown"])
        
    def log(self, message: str) -> None:
        """Log a message to the log file and stdout."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
            
            # For KWOK nodes, use CPU requests directly as utilization without random variance
            is_kwok_node = "kwok.x-k8s.io/node" in annotations and annotations["kwok.x-k8s.io/node"] == "fake"
            if is_kwok_node:
                # Use CPU requests directly as the utilization value with a realistic baseline
                # Add a minimum baseline utilization for realism (servers are never truly at 0%)
                baseline_utilization = 5.0  # 5% minimum utilization for system processes
                
                # Calculate utilization based on pod requests with a consistent multiplier
                # In real systems, actual usage is often 60-80% of the requested resources
                resource_multiplier = 0.7  # 70% of requested resources typically used
                request_based_utilization = (cpu_used / cpu_capacity_num) * 100 if cpu_capacity_num > 0 else 0
                request_based_utilization *= resource_multiplier
                
                # Combine baseline with request-based utilization - no random variation
                cpu_utilization = baseline_utilization + request_based_utilization
                
                # Ensure utilization doesn't exceed 100%
                cpu_utilization = min(cpu_utilization, 100.0)
                
                # Calculate power draw based on the utilization
                power_draw = idle_watts + (active_watts - idle_watts) * (cpu_utilization / 100)
                
                if not hasattr(self, '_kwok_utilization_logged'):
                    self._kwok_utilization_logged = set()
                    
                # Log the first time we see each node for debugging
                if node_name not in self._kwok_utilization_logged:
                    self._kwok_utilization_logged.add(node_name)
                    self.log(f"Using realistic CPU utilization for KWOK node {node_name}: {cpu_utilization:.1f}% (based on {request_based_utilization/resource_multiplier:.1f}% requested)")
            else:
                # For real nodes, use the actual utilization
                cpu_utilization = (cpu_used / cpu_capacity_num) * 100 if cpu_capacity_num > 0 else 0
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
        
        # Log utilization stats for debugging
        if node_metrics:
            utilization_values = [n['cpu_utilization'] for n in node_metrics if n['cpu_utilization'] is not None]
            if utilization_values:
                avg_util = sum(utilization_values) / len(utilization_values)
                min_util = min(utilization_values)
                max_util = max(utilization_values)
                self.log(f"Current CPU utilization stats - Avg: {avg_util:.1f}%, Min: {min_util:.1f}%, Max: {max_util:.1f}%")
            
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
                creation_dt = datetime.fromisoformat(creation_timestamp.replace("Z", "+00:00"))
                start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
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
            self._write_latest_metrics_to_csv([carbon_metrics], "carbon_metrics")
            self._write_latest_metrics_to_csv([performance_metrics], "performance")
            
            # Write vanilla session CSVs if running vanilla algorithm
            if self._is_vanilla_algorithm():
                # Create a shared timestamp for both CSV files
                if not hasattr(self, '_vanilla_timestamp'):
                    self._vanilla_timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                    # Use the specified vanilla experiments directory
                    self._vanilla_dir = "/root/carbon-aware-orchestrator/pkg/carbon-aware/server-python/experiments"
                    os.makedirs(self._vanilla_dir, exist_ok=True)
                    self._tracked_pods = set()  # Track pods we've already recorded
                
                vanilla_metrics = self.generate_vanilla_session_metrics()
                self._write_vanilla_session_csv(vanilla_metrics)
                self._write_vanilla_perf_session_csv(vanilla_metrics)
                self.generate_vanilla_placement_session_metrics()
            
        except Exception as e:
            self.log(f"Error collecting metrics: {e}")
    
    def collect_metrics(self) -> None:
        """Collect metrics at regular intervals until signaled to stop."""
        self.start_time = time.time()
        self.sim_start_time = time.time()  # Initialize simulation time reference
        self.log(f"Starting metrics collection")
        self.log(f"Collection interval: {self.collection_interval} seconds")
        self.log(f"Shrink factor: {self.shrink_factor} (1 real second = {self.shrink_factor} simulation seconds)")
        self.log(f"Output directory: {self.output_dir}")
        
        # Save experiment configuration
        config = {
            "experiment_name": self.experiment_name,
            "start_time": self.start_time,
            "sim_start_time": self.sim_start_time,
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
        
        # Generate vanilla placement session CSV for vanilla experiments
        if self._is_vanilla_algorithm():
            self.log("Checking vanilla placement session CSV generation...")
            
            # Check if placement CSV was already generated during real-time collection
            placement_generated = False
            if hasattr(self, '_vanilla_timestamped_folder') and self._vanilla_timestamped_folder:
                placement_csv_path = os.path.join(self._vanilla_timestamped_folder, "vanilla_placement_session.csv")
                if os.path.exists(placement_csv_path):
                    self.log(f"✓ VANILLA PLACEMENT CSV already exists: {placement_csv_path}")
                    placement_generated = True
            
            # Only try JSON-based generation if real-time generation failed
            if not placement_generated:
                self.log("Attempting vanilla placement CSV generation from JSON data...")
                if self.generate_vanilla_placement_from_json_data():
                    placement_csv_path = "/root/carbon-aware-orchestrator/pkg/carbon-aware/server-python/experiments/vanilla_placement_session.csv"
                    self.log(f"✓ VANILLA PLACEMENT CSV SAVED TO: {placement_csv_path}")
                else:
                    self.log("⚠ Failed to generate vanilla placement CSV from JSON data")
                    # Try one more time with direct pod collection
                    self.log("Attempting direct placement collection as fallback...")
                    if self.generate_vanilla_placement_session_metrics():
                        self.log("✓ Direct placement collection succeeded")
                    else:
                        self.log("⚠ All vanilla placement generation methods failed")
            
            # Generate vanilla performance session CSV as well (always try this as it doesn't require placement data)
            self.log("Generating vanilla performance session CSV for post-experiment analysis...")
            if self.generate_vanilla_performance_from_json_data():
                perf_csv_path = "/root/carbon-aware-orchestrator/pkg/carbon-aware/server-python/experiments/vanilla_perf_session.csv"
                self.log(f"✓ VANILLA PERFORMANCE CSV SAVED TO: {perf_csv_path}")
            else:
                self.log("⚠ Failed to generate vanilla performance CSV")
            
            # Generate final experiment-wide placement summary
            self.log("Generating final placement summary for vanilla experiment...")
            self._generate_final_placement_summary_log()
        
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
    
    def _get_pod_count_from_workload(self) -> int:
        """
        Get the total number of pods from the workloads-vanilla/timeslot_11.yaml file.
        
        Returns:
            int: Total number of pods (adds 1 to the highest pod number since they start at m000)
            
        Raises:
            FileNotFoundError: If the workload file doesn't exist
            ValueError: If no pod numbers found in the file
            Exception: For other file reading errors
        """
        workload_file = "/root/carbon-aware-orchestrator/pkg/carbon-aware/workloads-vanilla/timeslot_11.yaml"
        
        if not os.path.exists(workload_file):
            raise FileNotFoundError(f"Workload file not found: {workload_file}")
        
        try:
            with open(workload_file, 'r') as f:
                content = f.read()
        except Exception as e:
            raise Exception(f"Error reading workload file {workload_file}: {e}")
        
        # Find all pod numbers (e.g., m000, m001, m046)
        pod_numbers = re.findall(r'm(\d{3})', content)
        if not pod_numbers:
            raise ValueError(f"No pod numbers found in {workload_file}")
        
        # Get the highest pod number and add 1 (since they start at m000)
        max_pod_num = max(int(num) for num in pod_numbers)
        total_pods = max_pod_num + 1
        
        self.log(f"Found {total_pods} pods in workload (highest pod: m{max_pod_num:03d})")
        return total_pods

    def _generate_final_placement_summary_log(self) -> None:
        """
        Generate a final placement summary log for the entire experiment.
        Uses total pod count from timeslot files and analyzes all placement data from the experiment.
        """
        try:
            if not hasattr(self, '_vanilla_timestamped_folder') or not self._vanilla_timestamped_folder:
                self.log("No vanilla timestamped folder found, skipping placement summary")
                return
                
            # Get total pods from timeslot files
            try:
                total_pods_from_timeslot = self._get_pod_count_from_workload()
            except (FileNotFoundError, ValueError, Exception) as e:
                self.log(f"Error getting pod count from workload: {e}")
                self.log("Cannot generate placement summary without valid pod count")
                return
            
            # Read all placement data from the CSV file
            csv_file = os.path.join(self._vanilla_timestamped_folder, "vanilla_placement_session.csv")
            if not os.path.exists(csv_file):
                self.log("No placement CSV found, skipping placement summary")
                return
                
            placement_data = []
            with open(csv_file, 'r') as f:
                reader = csv.DictReader(f)
                placement_data = list(reader)
            
            # Count unique successfully placed pods by analyzing unique pod names
            unique_placed_pods = set()
            unique_unplaced_pods = set() 
            node_counts = {}
            
            for record in placement_data:
                pod_id = record.get('pod_id', '').strip()
                node_id = record.get('node_id', 'unscheduled').strip()
                
                if node_id and node_id != 'unscheduled' and node_id != '':
                    # Pod was successfully placed on a node
                    unique_placed_pods.add(pod_id)
                else:
                    # Pod was not placed (unscheduled or empty node_id)
                    unique_unplaced_pods.add(pod_id)
                
                # Count placement attempts per node (including duplicates for analysis)
                node_counts[node_id] = node_counts.get(node_id, 0) + 1
            
            # Calculate final counts based on unique pod names
            successful_count = len(unique_placed_pods)
            attempted_placement_count = len(unique_placed_pods.union(unique_unplaced_pods))
            failed_count = total_pods_from_timeslot - successful_count
            success_rate = (successful_count / total_pods_from_timeslot * 100) if total_pods_from_timeslot > 0 else 0
            
            # Log detailed placement analysis
            self.log(f"Placement analysis: Found {attempted_placement_count} pods with placement attempts out of {total_pods_from_timeslot} total pods in timeslot")
            self.log(f"Unique successfully placed pods: {sorted(list(unique_placed_pods))}")
            if unique_unplaced_pods:
                self.log(f"Unique unplaced pods: {sorted(list(unique_unplaced_pods))}")
            
            log_content = f"""Vanilla Experiment Placement Summary
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Experiment-Wide Pod Placement Statistics:
- Total pods in timeslot_11.yaml: {total_pods_from_timeslot}
- Unique pods successfully placed: {successful_count}
- Pods not placed: {failed_count}
- Success rate: {successful_count}/{total_pods_from_timeslot} = {success_rate:.1f}%

Unique Successfully Placed Pods:
{', '.join(sorted(list(unique_placed_pods))) if unique_placed_pods else 'None'}

Node Placement Distribution (including duplicates):
"""
            
            # Add per-node placement counts
            for node_id, count in sorted(node_counts.items()):
                log_content += f"- {node_id}: {count} pods\n"
            
            log_file = os.path.join(self._vanilla_timestamped_folder, "placement_summary.log")
            with open(log_file, 'w') as f:
                f.write(log_content)
            
            self.log(f"Final placement summary saved to: {log_file}")
            self.log(f"Experiment placement summary: {successful_count}/{total_pods_from_timeslot} pods placed successfully ({success_rate:.1f}%)")
            
        except Exception as e:
            self.log(f"Error generating final placement summary: {e}")

    def _write_vanilla_session_csv(self, session_data: Dict[str, Any]) -> None:
        """Write vanilla session performance data to CSV file matching heuristic format."""
        # Use the shared timestamped folder
        csv_file = os.path.join(self._vanilla_dir, "vanilla_performance_session.csv")
        file_exists = os.path.isfile(csv_file)
        
        # Define the 21 columns that match the heuristic performance session CSV format
        fieldnames = [
            'timestamp', 'call_id', 'execution_time_ms', 'algorithm', 'pods_total', 
            'pods_processed', 'pods_placed', 'pods_failed', 'pods_skipped', 
            'total_emissions_kg', 'per_pod_emissions_kg', 'avg_placement_time_ms', 
            'total_flavours', 'total_timeslots', 'scheduling_options', 
            'cpu_utilization_pct', 'memory_utilization_pct', 'regions', 
            'algorithm_iterations', 'algorithm_steps', 'microservices'
        ]
        
        with open(csv_file, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerow(session_data)
            
        self.log(f"Vanilla performance session CSV written to: {csv_file}")
    
    def _write_vanilla_perf_session_csv(self, session_data: Dict[str, Any]) -> None:
        """Write vanilla performance session data to CSV file with timing in milliseconds.
        
        Creates vanilla_perf_session.csv in the same folder as vanilla_placement_session.csv
        with structure matching global-optimal format but only up to 'pods_skipped' column.
        
        Args:
            session_data: Dictionary containing session performance data
        """
        try:
            # Use the same timestamped folder as placement CSV
            if not hasattr(self, '_vanilla_timestamped_folder') or not self._vanilla_timestamped_folder:
                import datetime
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                try:
                    pod_count = self._get_pod_count_from_workload()
                except (FileNotFoundError, ValueError, Exception) as e:
                    self.log(f"Error getting pod count for folder naming: {e}")
                    pod_count = "unknown"
                self._vanilla_timestamped_folder = os.path.join(self._vanilla_dir, f"vanilla_{pod_count}pods_{timestamp}")
                os.makedirs(self._vanilla_timestamped_folder, exist_ok=True)
            
            csv_file = os.path.join(self._vanilla_timestamped_folder, "vanilla_perf_session.csv")
            file_exists = os.path.isfile(csv_file)
            
            # Define columns up to 'pods_skipped' only (matching global-optimal format)
            fieldnames = [
                'timestamp', 'call_id', 'execution_time_ms', 'algorithm', 'pods_total', 
                'pods_processed', 'pods_placed', 'pods_failed', 'pods_skipped'
            ]
            
            # Extract only the relevant data for the CSV
            perf_data = {
                'timestamp': session_data.get('timestamp'),
                'call_id': session_data.get('call_id'),
                'execution_time_ms': session_data.get('execution_time_ms'),
                'algorithm': session_data.get('algorithm'),
                'pods_total': session_data.get('pods_total'),
                'pods_processed': session_data.get('pods_processed'),
                'pods_placed': session_data.get('pods_placed'),
                'pods_failed': session_data.get('pods_failed'),
                'pods_skipped': session_data.get('pods_skipped')
            }
            
            with open(csv_file, "a", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                if not file_exists:
                    writer.writeheader()
                writer.writerow(perf_data)
                
            self.log(f"✓ Vanilla performance session CSV written to: {csv_file}")
            
        except Exception as e:
            self.log(f"Error writing vanilla performance session CSV: {e}")

    def generate_vanilla_session_metrics(self) -> Dict[str, Any]:
        """Generate vanilla algorithm session metrics in the same format as heuristic performance session."""
        # Get current timestamp in the same format as heuristic CSV
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # Calculate call_id (incremental counter)
        if not hasattr(self, '_vanilla_call_id'):
            self._vanilla_call_id = 0
        self._vanilla_call_id += 1
        
        # Get pod metrics for calculations
        current_pod_metrics = self.collect_pod_metrics()
        
        # Count pods by status
        pods_total = len(current_pod_metrics)
        pods_running = sum(1 for pod in current_pod_metrics if pod.get('phase') == 'Running')
        pods_pending = sum(1 for pod in current_pod_metrics if pod.get('phase') == 'Pending')
        pods_failed = sum(1 for pod in current_pod_metrics if pod.get('phase') == 'Failed')
        pods_processed = pods_running + pods_failed  # Pods that have been processed by scheduler
        pods_placed = pods_running  # Successfully placed pods
        pods_skipped = pods_pending  # Pods not yet scheduled
        
        # Get real scheduler execution time using actual Kubernetes scheduler metrics
        execution_time_ms, scheduler_details = _get_real_scheduler_execution_time(current_pod_metrics, node_metrics)
        
        # Log detailed information about timing source
        if scheduler_details:
            if scheduler_details.get('method') == 'estimation':
                self.log(f"Using estimated execution time: {execution_time_ms:.2f}ms "
                        f"({scheduler_details['pods_processed']} pods, {scheduler_details['num_nodes']} nodes)")
            else:
                self.log(f"Using real scheduler metrics: {execution_time_ms:.2f}ms")
                if 'plugin_timings' in scheduler_details:
                    total_plugin_time = sum(scheduler_details['plugin_timings'].values())
                    self.log(f"Total plugin execution time: {total_plugin_time:.2f}ms")
        else:
            self.log(f"Using fallback execution time: {execution_time_ms:.2f}ms")
        
        # Get carbon metrics
        carbon_metrics = self.calculate_carbon_metrics()
        total_emissions_kg = carbon_metrics.get('total_carbon_rate', 0) / 1000  # Convert g to kg
        per_pod_emissions_kg = total_emissions_kg / max(pods_processed, 1)
        
        # Calculate average placement time (same as execution time for vanilla)
        avg_placement_time_ms = execution_time_ms
        
        # Get node metrics for resource utilization
        node_metrics = self.collect_node_metrics()
        cpu_utilization_pct = 0
        memory_utilization_pct = 0
        if node_metrics:
            cpu_utils = [node.get('cpu_utilization', 0) for node in node_metrics]
            memory_utils = [node.get('memory_utilization', 0) for node in node_metrics]
            cpu_utilization_pct = sum(cpu_utils) / len(cpu_utils) if cpu_utils else 0
            memory_utilization_pct = sum(memory_utils) / len(memory_utils) if memory_utils else 0
        
        # Get unique regions from node metrics
        regions = set()
        total_flavours = 0
        if node_metrics:
            for node in node_metrics:
                region = node.get('region', '')
                if region:
                    regions.add(region)
            total_flavours = len(node_metrics)  # Number of node types/flavors
        
        # For vanilla algorithm, these are typically fixed or calculated values
        total_timeslots = 48  # Standard 48 timeslots (24 hours * 2 timeslots per hour)
        scheduling_options = len(node_metrics) * total_timeslots if node_metrics else 0
        algorithm_iterations = 0  # Vanilla doesn't use iterations
        algorithm_steps = 0  # Vanilla doesn't use steps
        
        # Get microservices info from pod annotations
        microservices = []
        for pod in current_pod_metrics:
            duration = pod.get('duration_hours', '1')
            deadline = pod.get('deadline_hours', '2') 
            microservice_info = f"m{len(microservices):03d}-duration-{duration}h-deadline-{deadline}h"
            microservices.append(microservice_info)
        
        # If no specific microservices, use pod count as fallback
        if not microservices and pods_total > 0:
            microservices = [f"{pods_total}_pods"]
        
        microservices_str = "|".join(microservices[:5])  # Limit to first 5 for readability
        
        session_data = {
            'timestamp': timestamp,
            'call_id': self._vanilla_call_id,
            'execution_time_ms': round(execution_time_ms, 2),
            'algorithm': 'vanilla',
            'pods_total': pods_total,
            'pods_processed': pods_processed,
            'pods_placed': pods_placed,
            'pods_failed': pods_failed,
            'pods_skipped': pods_skipped,
            'total_emissions_kg': round(total_emissions_kg, 6),
            'per_pod_emissions_kg': round(per_pod_emissions_kg, 6),
            'avg_placement_time_ms': round(avg_placement_time_ms, 2),
            'total_flavours': total_flavours,
            'total_timeslots': total_timeslots,
            'scheduling_options': scheduling_options,
            'cpu_utilization_pct': round(cpu_utilization_pct, 2),
            'memory_utilization_pct': round(memory_utilization_pct, 2),
            'regions': ','.join(sorted(regions)) if regions else '',
            'algorithm_iterations': algorithm_iterations,
            'algorithm_steps': algorithm_steps,
            'microservices': microservices_str
        }
        
        return session_data

    def generate_vanilla_placement_session_metrics(self) -> bool:
        """Generate vanilla placement session metrics matching the heuristic placement session format.
        
        This method accumulates all pods that get scheduled throughout the experiment duration,
        including pods that may have completed and been terminated. It uses both current pod status
        and scheduling events to capture the complete picture.
        
        Returns:
            bool: True if successfully generated and written, False otherwise
        """
        self.log("Generating vanilla placement session metrics...")
        
        # Ensure vanilla tracking is initialized
        if not hasattr(self, '_vanilla_timestamp'):
            self._vanilla_timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            # Use the specified vanilla experiments directory
            self._vanilla_dir = "/root/carbon-aware-orchestrator/pkg/carbon-aware/server-python/experiments"
            os.makedirs(self._vanilla_dir, exist_ok=True)
            self._tracked_pods = set()  # Track pods we've already recorded
        
        # Ensure simulation start time is set for timeslot calculations
        if not hasattr(self, 'sim_start_time') or self.sim_start_time is None:
            self.sim_start_time = time.time()
            self.log(f"Initialized simulation start time for vanilla tracking: {self.sim_start_time}")
        
        try:
            all_placement_data = []
            
            # First, get current pods (prefer this as it has complete information)
            pods_json = self.run_kubectl(["get", "pods", "-n", self.namespace, "-o", "json"])
            if pods_json:
                pods_data = json.loads(pods_json)
                all_placement_data.extend(self._extract_placement_from_pods(pods_data.get("items", [])))
            
            # Only check events for pods that are NOT in current pods (to avoid duplicates)
            # This catches pods that have been garbage collected
            events_json = self.run_kubectl(["get", "events", "-n", self.namespace, "-o", "json"])
            if events_json:
                events_data = json.loads(events_json)
                event_placements = self._extract_placement_from_events(events_data.get("items", []))
                # Filter out any event-based placements that we already got from current pods
                current_pod_names = {data["pod_id"] for data in all_placement_data}
                unique_event_placements = [ep for ep in event_placements if ep["pod_id"] not in current_pod_names]
                all_placement_data.extend(unique_event_placements)
                
            # Append new placement session data to CSV (accumulative)
            if all_placement_data:
                self._append_vanilla_placement_session_csv(all_placement_data)
                self.log(f"Added {len(all_placement_data)} new pod placements to vanilla placement session")
                return True
            else:
                # Debug: Check why no placement data was found
                self.log("No new placement data found in this cycle")
                if pods_json:
                    pods_data = json.loads(pods_json)
                    total_pods = len(pods_data.get("items", []))
                    scheduled_pods = sum(1 for pod in pods_data.get("items", []) 
                                       if pod.get("spec", {}).get("nodeName"))
                    self.log(f"Debug: Total pods: {total_pods}, Scheduled pods: {scheduled_pods}")
                else:
                    self.log("Debug: No pod data retrieved from kubectl")
                return True
                
        except Exception as e:
            self.log(f"Error generating vanilla placement session metrics: {e}")
            return False

    def generate_vanilla_placement_from_json_data(self, raw_data_dir: str = None) -> bool:
        """Generate vanilla placement session CSV from existing JSON data files.
        
        This method processes the scheduling.json and pods.json files to create accurate
        vanilla placement data with correct timestamps, durations, and resource requests.
        
        Args:
            raw_data_dir: Directory containing raw data JSON files. If None, uses current output_dir/raw_data
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            if raw_data_dir is None:
                raw_data_dir = os.path.join(self.output_dir, "raw_data")
            
            if not os.path.exists(raw_data_dir):
                self.log(f"Raw data directory not found: {raw_data_dir}")
                return False
            
            # Load experiment config to get simulation parameters
            config_file = os.path.join(os.path.dirname(raw_data_dir), "experiment_config.json")
            sim_start_time = None
            shrink_factor = 1
            
            if os.path.exists(config_file):
                with open(config_file, 'r') as f:
                    config = json.load(f)
                    sim_start_time = config.get("sim_start_time", config.get("start_time"))
                    shrink_factor = config.get("shrink_factor", 1)
                    self.log(f"Loaded experiment config: sim_start_time={sim_start_time}, shrink_factor={shrink_factor}")
            
            # Load scheduling events
            scheduling_file = os.path.join(raw_data_dir, "scheduling.json")
            if not os.path.exists(scheduling_file):
                self.log(f"Scheduling data file not found: {scheduling_file}")
                return False
            
            with open(scheduling_file, 'r') as f:
                scheduling_data = json.load(f)
            
            # Load pods data for resource information
            pods_file = os.path.join(raw_data_dir, "pods.json")
            pods_data = []
            if os.path.exists(pods_file):
                with open(pods_file, 'r') as f:
                    pods_data = json.load(f)
                    
            # Create a mapping of pod names to their resource requests from pods.json
            pod_resources = {}
            for pod in pods_data:
                pod_name = pod.get("pod_name", "")
                if pod_name:
                    pod_resources[pod_name] = {
                        "cpu_request": pod.get("cpu_request", 0.0),
                        "ram_request": pod.get("memory_request", 0.0)  # Note: check if it's "memory_request" or "ram_request"
                    }
            
            # Process scheduling events to extract placements
            # Use a dictionary to track first placement per microservice (not per pod)
            microservice_placements = {}
            
            for event in scheduling_data:
                if event.get("reason") != "Scheduled":
                    continue
                
                # Extract pod name from the message
                message = event.get("message", "")
                pod_name = event.get("object_name", "")
                
                if not pod_name:
                    continue
                
                # Extract microservice base name from pod name
                # Pod names are like: m004-duration-3h-deadline-4h-67958f87f-fmbvc
                # OR word-based names like: four-duration-1h-deadline-2h-77c57c9559-kxwk2
                # We want the microservice name: m004-duration-3h-deadline-4h or four-duration-1h-deadline-2h
                import re
                microservice_match = re.match(r'^((?:m\d+|one|two|three|four|five|six|seven|eight|nine|ten)-duration-\d+h-deadline-\d+h)', pod_name)
                if not microservice_match:
                    # Skip pods that don't match expected microservice naming pattern
                    self.log(f"Warning: Pod {pod_name} doesn't match expected microservice naming pattern")
                    continue
                
                microservice_name = microservice_match.group(1)
                
                # Skip if we already have a placement for this microservice
                if microservice_name in microservice_placements:
                    continue
                
                # Parse node name from message: "Successfully assigned namespace/pod-name to node-name"
                node_name = None
                if "assigned" in message and " to " in message:
                    parts = message.split(" to ")
                    if len(parts) > 1:
                        node_name = parts[1].strip()
                
                if not node_name:
                    continue
                
                # Extract duration from microservice name
                duration = 1.0
                duration_match = re.search(r'duration-(\d+)h', microservice_name)
                if duration_match:
                    try:
                        duration = float(duration_match.group(1))
                    except (ValueError, TypeError):
                        duration = 1.0
                
                # Calculate start slot based on actual event timestamp
                start_slot = self._calculate_timeslot_from_event_timestamp(event, sim_start_time, shrink_factor)
                
                # Get resource information from pod_resources mapping
                cpu_request = 0.0
                ram_request = 0.0
                if pod_name in pod_resources:
                    cpu_request = pod_resources[pod_name].get("cpu_request", 0.0)
                    ram_request = pod_resources[pod_name].get("ram_request", 0.0)
                
                # Create placement record for this microservice (use microservice name as ID)
                placement_record = {
                    "pod_id": microservice_name,  # Use microservice name instead of full pod name
                    "node_id": node_name,
                    "start_slot": start_slot,
                    "duration": duration,
                    "cpu_request": cpu_request,
                    "ram_request": ram_request
                }
                
                # Store this microservice placement
                microservice_placements[microservice_name] = placement_record
            
            # Convert dictionary to list for CSV writing
            placement_data = list(microservice_placements.values())
                
            # Write the placement data to CSV
            if placement_data:
                # Use the timestamped folder approach
                self._vanilla_dir = "/root/carbon-aware-orchestrator/pkg/carbon-aware/server-python/experiments"
                os.makedirs(self._vanilla_dir, exist_ok=True)
                self._write_vanilla_placement_session_csv(placement_data)
                return True
            else:
                self.log("No placement data found to generate CSV")
                return False
                
        except Exception as e:
            self.log(f"Error generating vanilla placement from JSON data: {e}")
            return False

    def generate_vanilla_performance_from_json_data(self, raw_data_dir: str = None) -> bool:
        """Generate vanilla performance session CSV from existing JSON data files.
        
        This method processes the performance.json and pods.json files to create accurate
        vanilla performance data with timing metrics in milliseconds.
        
        Args:
            raw_data_dir: Directory containing raw data JSON files. If None, uses current output_dir/raw_data
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            if raw_data_dir is None:
                raw_data_dir = os.path.join(self.output_dir, "raw_data")
            
            if not os.path.exists(raw_data_dir):
                self.log(f"Raw data directory not found: {raw_data_dir}")
                return False
            
            # Load experiment config to get simulation parameters
            config_file = os.path.join(os.path.dirname(raw_data_dir), "experiment_config.json")
            experiment_name = "vanilla_analysis"
            
            if os.path.exists(config_file):
                with open(config_file, 'r') as f:
                    config = json.load(f)
                    experiment_name = config.get("experiment_name", "vanilla_analysis")
            
            # Create timestamped folder for results
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            vanilla_dir = "/root/carbon-aware-orchestrator/pkg/carbon-aware/server-python/experiments"
            try:
                pod_count = self._get_pod_count_from_workload()
            except (FileNotFoundError, ValueError, Exception) as e:
                self.log(f"Error getting pod count for folder naming: {e}")
                pod_count = "unknown"
            vanilla_folder = os.path.join(vanilla_dir, f"vanilla_{pod_count}pods_{timestamp}")
            os.makedirs(vanilla_folder, exist_ok=True)
            
            # Load performance data
            performance_file = os.path.join(raw_data_dir, "performance.json")
            if not os.path.exists(performance_file):
                self.log(f"Performance data file not found: {performance_file}")
                return False
            
            with open(performance_file, 'r') as f:
                performance_data = json.load(f)
            
            # Load pods data for additional metrics
            pods_file = os.path.join(raw_data_dir, "pods.json")
            pods_data = []
            if os.path.exists(pods_file):
                with open(pods_file, 'r') as f:
                    pods_data = json.load(f)
            
            # Create performance CSV entries
            csv_file = os.path.join(vanilla_folder, "vanilla_perf_session.csv")
            fieldnames = [
                'timestamp', 'call_id', 'execution_time_ms', 'algorithm', 'pods_total', 
                'pods_processed', 'pods_placed', 'pods_failed', 'pods_skipped'
            ]
            
            with open(csv_file, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                
                for idx, perf_entry in enumerate(performance_data, 1):
                    # Calculate realistic execution time for vanilla algorithm
                    # Don't use scheduling_latency as it measures pod wait time, not algorithm execution time
                    execution_time_ms = 0
                    
                    # Get pod counts
                    pods_running = perf_entry.get('running_pods', 0)
                    pods_pending = perf_entry.get('pending_pods', 0)
                    pods_failed = perf_entry.get('failed_pods', 0)
                    pods_total = pods_running + pods_pending + pods_failed
                    pods_processed = pods_running + pods_failed
                    pods_placed = pods_running
                    pods_skipped = pods_pending
                    
                    # Calculate execution time using real scheduler metrics or estimation  
                    if pods_processed > 0:
                        # Create mock metrics for the timing function
                        current_pod_metrics = [{'phase': 'Running'}] * pods_running + \
                                            [{'phase': 'Failed'}] * pods_failed + \
                                            [{'phase': 'Pending'}] * pods_pending
                        
                        # Estimate number of nodes (use available data or reasonable default)
                        nodes_available = perf_entry.get('total_nodes', 10)  # Default to 10 nodes
                        node_metrics = [{'name': f'node-{i}'} for i in range(nodes_available)]
                        
                        # Use the same timing approach as real-time collection
                        execution_time_ms, scheduler_details = _get_real_scheduler_execution_time(current_pod_metrics, node_metrics)
                        
                        print(f"Historical data processing - using {'real' if scheduler_details and scheduler_details.get('method') != 'estimation' else 'estimated'} "
                              f"scheduler timing: {execution_time_ms:.2f}ms for {pods_processed} pods")
                    
                    # Create timestamp
                    timestamp_str = datetime.fromtimestamp(
                        perf_entry.get('timestamp', time.time())
                    ).strftime('%Y-%m-%d %H:%M:%S')
                    
                    row = {
                        'timestamp': timestamp_str,
                        'call_id': idx,
                        'execution_time_ms': round(execution_time_ms, 2),
                        'algorithm': 'vanilla',
                        'pods_total': pods_total,
                        'pods_processed': pods_processed,
                        'pods_placed': pods_placed,
                        'pods_failed': pods_failed,
                        'pods_skipped': pods_skipped
                    }
                    
                    writer.writerow(row)
            
            self.log(f"✓ Vanilla performance session CSV written to: {csv_file}")
            return True
            
        except Exception as e:
            self.log(f"Error generating vanilla performance CSV from JSON data: {e}")
            return False

    def _extract_placement_from_pods(self, pods: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Extract placement data from current pod objects."""
        placement_data = []
        total_pods = len(pods)
        scheduled_pods = 0
        already_tracked = 0
        
        self.log(f"Extracting placement data from {total_pods} pods")
        
        for pod in pods:
            pod_name = pod.get("metadata", {}).get("name", "")
            node_name = pod.get("spec", {}).get("nodeName", "")
            
            # Skip pods that aren't scheduled
            if not node_name or node_name == "unscheduled":
                continue
                
            scheduled_pods += 1
                
            # Check if we've already tracked this pod
            pod_id = f"{pod_name}@{node_name}"
            if pod_id in self._tracked_pods:
                already_tracked += 1
                continue
                
            # Add to tracking
            self._tracked_pods.add(pod_id)
            
            # Extract duration from pod name
            import re
            duration = 1.0
            duration_match = re.search(r'duration-(\d+)h', pod_name)
            if duration_match:
                try:
                    duration = float(duration_match.group(1))
                except (ValueError, TypeError):
                    duration = 1.0
            
            # Try to calculate start slot from pod creation/start time
            start_time = pod.get("status", {}).get("startTime")
            start_slot = self._calculate_pod_start_slot_from_time(start_time) if start_time else 1
            
            # Get container resource requests
            cpu_request = 0.0
            ram_request = 0.0
            containers = pod.get("spec", {}).get("containers", [])
            for container in containers:
                requests = container.get("resources", {}).get("requests", {})
                cpu_req = requests.get("cpu", "0")
                memory_req = requests.get("memory", "0")
                
                # Convert CPU request to numeric value
                cpu_request += self._parse_cpu_value(cpu_req)
                ram_request += self._parse_memory_value(memory_req)
            
            placement_record = {
                "pod_id": pod_name,
                "node_id": node_name,
                "start_slot": start_slot,
                "duration": duration,
                "cpu_request": cpu_request,
                "ram_request": ram_request
            }
            
            placement_data.append(placement_record)
            
        self.log(f"Placement extraction summary: {total_pods} total pods, {scheduled_pods} scheduled, "
                f"{already_tracked} already tracked, {len(placement_data)} new placements extracted")
        return placement_data

    def _extract_placement_from_events(self, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Extract placement data from Kubernetes scheduling events.
        
        This method captures pods that may have been scheduled and then garbage collected,
        by looking for 'Scheduled' events in the event log.
        """
        placement_data = []
        
        for event in events:
            if event.get("reason") != "Scheduled":
                continue
                
            involved_object = event.get("involvedObject", {})
            if involved_object.get("kind") != "Pod":
                continue
                
            pod_name = involved_object.get("name", "unknown")
            message = event.get("message", "")
            
            # Parse the scheduled message to extract node name
            # Message format is typically: "Successfully assigned namespace/pod-name to node-name"
            node_name = None
            if "assigned" in message and " to " in message:
                parts = message.split(" to ")
                if len(parts) > 1:
                    node_name = parts[1].strip()
            
            if not node_name:
                continue
                
            # Check if we've already tracked this pod
            pod_id = f"{pod_name}@{node_name}"
            if pod_id in self._tracked_pods:
                continue
                
            # Add to tracking
            self._tracked_pods.add(pod_id)
            
            # Extract duration from pod name (format: m000-duration-Xh-deadline-Yh-...)
            import re
            duration = 1.0  # Default
            duration_match = re.search(r'duration-(\d+)h', pod_name)
            if duration_match:
                try:
                    duration = float(duration_match.group(1))
                except (ValueError, TypeError):
                    duration = 1.0
            
            # Calculate start slot from microservice name (more reliable than timestamp for vanilla)
            start_slot = self._calculate_timeslot_from_microservice_name_dynamic(pod_name)
            
            # Extract default resource requests from microservice patterns
            # Default resource requests based on typical microservice patterns
            cpu_request = 0.1  # Default 100m CPU
            ram_request = 128.0  # Default 128Mi RAM
            
            # Try to extract resource hints from pod name if available
            # Look for patterns like 'cpu-XXXm' or 'mem-XXXmi' in pod name
            cpu_match = re.search(r'cpu-(\d+)m', pod_name)
            if cpu_match:
                try:
                    cpu_request = float(cpu_match.group(1)) / 1000  # Convert milliCPU to CPU
                except (ValueError, TypeError):
                    pass
                    
            mem_match = re.search(r'mem-(\d+)mi', pod_name)
            if mem_match:
                try:
                    ram_request = float(mem_match.group(1))
                except (ValueError, TypeError):
                    pass
            
            # Create placement record with extracted/default values
            # Don't try to fetch pod details since pods are likely garbage collected
            placement_record = {
                "pod_id": pod_name,
                "node_id": node_name,
                "start_slot": start_slot,
                "duration": duration,
                "cpu_request": cpu_request,
                "ram_request": ram_request
            }
            
            placement_data.append(placement_record)
            
        return placement_data

    def _get_pod_details(self, pod_name: str) -> Optional[Dict[str, Any]]:
        """Get detailed information about a specific pod if it still exists."""
        try:
            pod_json = self.run_kubectl(["get", "pod", pod_name, "-n", self.namespace, "-o", "json"])
            if not pod_json:
                return None
                
            pod = json.loads(pod_json)
            
            # Extract resource requests
            total_cpu_request = 0.0
            total_memory_request = 0.0
            containers = pod.get("spec", {}).get("containers", [])
            for container in containers:
                requests = container.get("resources", {}).get("requests", {})
                
                # Parse CPU request
                cpu_request = requests.get("cpu", "0")
                total_cpu_request += self._parse_cpu_value(cpu_request)
                
                # Parse memory request (convert to MB)
                memory_request = requests.get("memory", "0")
                memory_mb = self._parse_memory_value(memory_request)
                total_memory_request += memory_mb
            
            # Calculate start slot based on start time
            start_time = pod.get("status", {}).get("startTime")
            start_slot = self._calculate_pod_start_slot_from_time(start_time) if start_time else 1
            
            # Extract duration from pod name
            import re
            duration = 1.0
            pod_name_str = pod.get("metadata", {}).get("name", "")
            duration_match = re.search(r'duration-(\d+)h', pod_name_str)
            if duration_match:
                try:
                    duration = float(duration_match.group(1))
                except (ValueError, TypeError):
                    pass
            
            return {
                "start_slot": start_slot,
                "duration": duration,
                "cpu_request": total_cpu_request,
                "ram_request": total_memory_request
            }
            
        except Exception as e:
            # Pod might have been deleted, that's okay
            return None

    def _calculate_pod_start_slot_from_time(self, start_time_str: str) -> int:
        """Calculate the simulation timeslot when a pod was scheduled based on ISO time string."""
        try:
            if not start_time_str:
                return 1
                
            # Parse the pod's actual start time
            start_timestamp = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
            
            # Ensure we have a simulation start time
            if not hasattr(self, 'sim_start_time') or self.sim_start_time is None:
                self.log("Warning: sim_start_time not set for timeslot calculation")
                return 1
            
            experiment_start = datetime.fromtimestamp(self.sim_start_time, datetime.timezone.utc)
            
            # Calculate elapsed real time since experiment start
            elapsed_real_seconds = (start_timestamp - experiment_start).total_seconds()
            
            # If the pod started before our tracking began, use a small positive value
            if elapsed_real_seconds < 0:
                elapsed_real_seconds = 0
            
            # Convert to simulation time using shrink factor
            shrink_factor = getattr(self, 'shrink_factor', 1)
            elapsed_sim_seconds = elapsed_real_seconds / shrink_factor if shrink_factor > 1 else elapsed_real_seconds
            
            # Convert simulation seconds to simulation hours
            elapsed_sim_hours = elapsed_sim_seconds / 3600
            
            # Calculate timeslot (using 60-minute timeslots = 1.0 hour slots)
            timeslot = max(1, int(elapsed_sim_hours / 1.0) + 1)
            
            return timeslot
            
        except Exception as e:
            self.log(f"Error calculating pod start slot from time: {e}")
            return 1

    def _calculate_timeslot_from_event_timestamp(self, event, sim_start_time, shrink_factor):
        """Calculate the intended timeslot for a pod based on its microservice name and workload file mapping.
        
        Since vanilla scheduler doesn't respect timeslot scheduling times, we use the intended
        timeslot based on which workload file the microservice belongs to.
        """
        try:
            if not event:
                return 1
            
            # Extract microservice name from the pod name in the event message
            message = event.get("message", "")
            object_name = event.get("object_name", "")
            
            # Try to extract microservice name from either message or object_name
            microservice_name = None
            if "assigned" in message and "/" in message:
                # Message format: "Successfully assigned default/m000-duration-1h-deadline-7h-xxxxx to node"
                parts = message.split("/")
                if len(parts) > 1:
                    pod_full_name = parts[1].split(" ")[0]
                    # Extract microservice name (e.g., "m000" from "m000-duration-1h-deadline-7h-xxxxx")
                    import re
                    match = re.match(r"(m[0-9]{3})", pod_full_name)
                    if match:
                        microservice_name = match.group(1)
            
            if not microservice_name and object_name:
                # Try to extract from object_name
                import re
                match = re.match(r"(m[0-9]{3})", object_name)
                if match:
                    microservice_name = match.group(1)
            
            if not microservice_name:
                return 1
            
            return self._calculate_timeslot_from_microservice_name_dynamic(microservice_name)
            
        except Exception as e:
            self.log(f"Error calculating timeslot from event: {e}")
            return 1

    def _calculate_timeslot_from_microservice_name_dynamic(self, microservice_name: str) -> int:
        """Calculate the intended timeslot for a microservice by looking up actual workload files.
        
        This function dynamically reads the vanilla workload files to determine which
        timeslot a microservice belongs to, avoiding any hardcoded mappings.
        
        Args:
            microservice_name: Name like "m000", "m001", or full pod name like "m000-duration-1h-deadline-7h-66b9f89d6-dc7c9"
            
        Returns:
            int: Intended timeslot (1-based indexing)
        """
        try:
            # Get or build the microservice-to-timeslot mapping
            microservice_mapping = self._get_microservice_timeslot_mapping()
            
            # Extract just the microservice number part (e.g., "m000") from the full name
            import re
            match = re.match(r'^(m\d{3})', microservice_name)
            if match:
                base_microservice = match.group(1)
            else:
                self.log(f"Warning: Could not extract microservice number from {microservice_name}, defaulting to slot 1")
                return 1
            
            # Look up the microservice in the mapping
            if base_microservice in microservice_mapping:
                timeslot = microservice_mapping[base_microservice]
                return timeslot
            else:
                self.log(f"Warning: Microservice {base_microservice} (from {microservice_name}) not found in workload files, defaulting to slot 1")
                return 1
                
        except Exception as e:
            self.log(f"Error calculating timeslot for {microservice_name}: {e}")
            return 1

    def _get_microservice_timeslot_mapping(self) -> dict:
        """Build and cache a mapping of microservice names to their intended timeslots by reading workload files.
        
        Returns:
            dict: Mapping of microservice_name -> timeslot_number (1-based)
        """
        # Use cached mapping if available and not too old
        cache_duration = 300  # 5 minutes
        current_time = time.time()
        
        if (hasattr(self, '_microservice_mapping_cache') and 
            hasattr(self, '_microservice_mapping_timestamp') and
            (current_time - self._microservice_mapping_timestamp) < cache_duration):
            return self._microservice_mapping_cache
        
        # Build new mapping by scanning workload files
        try:
            import os
            import glob
            import re
            
            workload_dir = "/root/carbon-aware-orchestrator/pkg/carbon-aware/workloads-vanilla/"
            microservice_mapping = {}
            
            if not os.path.exists(workload_dir):
                self.log(f"Warning: Vanilla workload directory not found: {workload_dir}")
                return {}
            
            # Find all timeslot YAML files
            timeslot_files = sorted(glob.glob(os.path.join(workload_dir, "timeslot_*.yaml")))
            
            if not timeslot_files:
                self.log(f"Warning: No timeslot files found in {workload_dir}")
                return {}
            
            # Process each timeslot file
            for file_path in timeslot_files:
                try:
                    # Extract timeslot number from filename (e.g., "timeslot_0.yaml" -> 0)
                    filename = os.path.basename(file_path)
                    # Use simple string operations instead of regex for filename parsing
                    if 'timeslot_' in filename and '.yaml' in filename:
                        number_part = filename.replace('timeslot_', '').replace('.yaml', '')
                        try:
                            timeslot_file_number = int(number_part)
                            timeslot_number = timeslot_file_number + 1  # Convert to 1-based indexing
                        except ValueError:
                            continue
                    else:
                        continue
                    
                    # Read the file and extract microservice names
                    with open(file_path, 'r') as f:
                        file_content = f.read()
                    
                    # Find all microservice names using a simple regex pattern
                    # Look for patterns like "m000-duration", "m001-duration", etc.
                    microservice_matches = re.findall(r'm\d{3}(?=-duration)', file_content)
                    
                    # Use set to remove duplicates (same microservice might appear multiple times)
                    unique_microservices = list(set(microservice_matches))
                    
                    # Add to mapping
                    for microservice in unique_microservices:
                        microservice_mapping[microservice] = timeslot_number
                    
                    if unique_microservices:
                        self.log(f"Mapped {len(unique_microservices)} unique microservices from {filename} to timeslot {timeslot_number}")
                
                except Exception as e:
                    self.log(f"Error processing workload file {file_path}: {e}")
                    continue
            
            # Cache the mapping
            self._microservice_mapping_cache = microservice_mapping
            self._microservice_mapping_timestamp = current_time
            
            total_microservices = len(microservice_mapping)
            total_timeslots = len(set(microservice_mapping.values()))
            self.log(f"Built dynamic microservice mapping: {total_microservices} microservices across {total_timeslots} timeslots")
            
            return microservice_mapping
            
        except Exception as e:
            self.log(f"Error building microservice timeslot mapping: {e}")
            return {}
    def _write_vanilla_placement_session_csv(self, placement_data: List[Dict[str, Any]]) -> None:
        """Write vanilla placement session data to CSV file.
        
        Args:
            placement_data: List of placement records with pod placement information
        """
        try:
            # Create or use existing timestamped folder for vanilla placement session
            if not hasattr(self, '_vanilla_timestamped_folder') or not self._vanilla_timestamped_folder:
                from datetime import datetime
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                try:
                    pod_count = self._get_pod_count_from_workload()
                except (FileNotFoundError, ValueError, Exception) as e:
                    self.log(f"Error getting pod count for folder naming: {e}")
                    pod_count = "unknown"
                self._vanilla_timestamped_folder = os.path.join(self._vanilla_dir, f"vanilla_{pod_count}pods_{timestamp}")
                os.makedirs(self._vanilla_timestamped_folder, exist_ok=True)
            
            csv_file = os.path.join(self._vanilla_timestamped_folder, "vanilla_placement_session.csv")
            
            # Define CSV headers matching heuristic placement session format exactly
            headers = ["pod_id", "node_id", "start_slot", "duration", "cpu_request", "ram_request"]
            
            # Write CSV file (overwrite)
            with open(csv_file, 'w', newline='') as file:
                writer = csv.DictWriter(file, fieldnames=headers)
                writer.writeheader()
                writer.writerows(placement_data)
                
            self.log(f"✓ Vanilla placement session CSV written to: {csv_file}")
            self.log(f"✓ PLACEMENT FILE SAVED: {csv_file}")
            
        except Exception as e:
            self.log(f"Error writing vanilla placement session CSV: {e}")

    def _append_vanilla_placement_session_csv(self, placement_data: List[Dict[str, Any]]) -> None:
        """Append new vanilla placement session data to existing CSV file.
        
        Args:
            placement_data: List of new placement records to append
        """
        try:
            # Create or use existing timestamped folder for vanilla placement session
            if not hasattr(self, '_vanilla_timestamped_folder') or not self._vanilla_timestamped_folder:
                from datetime import datetime
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                try:
                    pod_count = self._get_pod_count_from_workload()
                except (FileNotFoundError, ValueError, Exception) as e:
                    self.log(f"Error getting pod count for folder naming: {e}")
                    pod_count = "unknown"
                self._vanilla_timestamped_folder = os.path.join(self._vanilla_dir, f"vanilla_{pod_count}pods_{timestamp}")
                os.makedirs(self._vanilla_timestamped_folder, exist_ok=True)
            
            csv_file = os.path.join(self._vanilla_timestamped_folder, "vanilla_placement_session.csv")
            
            # Define CSV headers matching heuristic placement session format exactly
            headers = ["pod_id", "node_id", "start_slot", "duration", "cpu_request", "ram_request"]
            
            # Check if file exists to determine if we need to write headers
            file_exists = os.path.isfile(csv_file)
            
            # Append to CSV file
            with open(csv_file, 'a', newline='') as file:
                writer = csv.DictWriter(file, fieldnames=headers)
                if not file_exists:
                    writer.writeheader()
                writer.writerows(placement_data)
            
            self.log(f"Appended {len(placement_data)} placement records to vanilla placement CSV: {csv_file}")
            
        except Exception as e:
            self.log(f"Error appending to vanilla placement session CSV: {e}")

    def _parse_cpu_value(self, cpu_str: str) -> float:
        """Parse CPU value from Kubernetes format to float."""
        if not cpu_str or cpu_str == "0":
            return 0.0
            
        cpu_str = str(cpu_str).strip()
        try:
            if cpu_str.endswith("m"):
                return float(cpu_str[:-1]) / 1000
            else:
                return float(cpu_str)
        except (ValueError, TypeError):
            return 0.0

    def _parse_memory_value(self, memory_str: str) -> float:
        """Parse memory value from Kubernetes format to MB."""
        if not memory_str or memory_str == "0":
            return 0.0
            
        memory_str = str(memory_str).strip()
        try:
            # Convert different units to MB
            if memory_str.endswith("Ki"):
                return float(memory_str[:-2]) / 1024  # KiB to MB
            elif memory_str.endswith("Mi"):
                return float(memory_str[:-2])  # MiB is approximately MB
            elif memory_str.endswith("Gi"):
                return float(memory_str[:-2]) * 1024  # GiB to MB
            elif memory_str.endswith("K"):
                return float(memory_str[:-1]) / 1000  # KB to MB
            elif memory_str.endswith("M"):
                return float(memory_str[:-1])  # MB
            elif memory_str.endswith("G"):
                return float(memory_str[:-1]) * 1000  # GB to MB
            else:
                # Assume bytes if no unit
                return float(memory_str) / (1024 * 1024)  # Bytes to MB
        except (ValueError, TypeError):
            return 0.0

    def _clean_and_parse_float(self, value_str: str) -> float:
        """Clean and parse a string value to float."""
        if not value_str:
            return 0.0
        try:
            # Remove any non-numeric characters except decimal point and minus
            cleaned = ''.join(c for c in str(value_str) if c.isdigit() or c in '.-')
            return float(cleaned) if cleaned else 0.0
        except (ValueError, TypeError):
            return 0.0

    def _is_vanilla_algorithm(self) -> bool:
        """Check if this is a vanilla algorithm experiment."""
        # Check experiment name or directory structure to determine if this is vanilla
        return "vanilla" in self.experiment_name.lower() or "vanilla" in self.output_dir.lower()

def _get_scheduler_timing_metrics():
    """
    Get real scheduler timing metrics from the Kubernetes scheduler metrics endpoint.
    
    This replaces the estimated algorithm execution time with actual metrics from the scheduler.
    Returns timing data in milliseconds.
    """
    try:
        # In a real cluster, scheduler metrics are available at:
        # - kube-scheduler pod: kubectl port-forward -n kube-system kube-scheduler-xxx 10259:10259
        # - Direct endpoint: https://scheduler-host:10259/metrics
        # - Via kubectl proxy: kubectl proxy -> http://localhost:8001/api/v1/namespaces/kube-system/services/kube-scheduler:http-metrics/proxy/metrics
        
        import requests
        import re
        from datetime import datetime
        
        # Try multiple methods to access scheduler metrics
        scheduler_metrics_urls = [
            "http://localhost:10259/metrics",  # Direct access if port-forwarded
            "http://127.0.0.1:8001/api/v1/namespaces/kube-system/services/kube-scheduler:http-metrics/proxy/metrics",  # Via kubectl proxy
        ]
        
        metrics_data = None
        for url in scheduler_metrics_urls:
            try:
                response = requests.get(url, timeout=5)
                if response.status_code == 200:
                    metrics_data = response.text
                    print(f"Successfully retrieved scheduler metrics from: {url}")
                    break
            except requests.exceptions.RequestException:
                continue
        
        if not metrics_data:
            print("Warning: Could not access scheduler metrics endpoints. Using fallback approach.")
            return None
            
        # Parse key scheduler timing metrics
        scheduling_metrics = {}
        
        # scheduler_scheduling_attempt_duration_seconds - actual scheduling algorithm time
        scheduling_duration_pattern = r'scheduler_scheduling_attempt_duration_seconds_sum{.*?} ([\d.]+)'
        scheduling_count_pattern = r'scheduler_scheduling_attempt_duration_seconds_count{.*?} ([\d.]+)'
        
        duration_matches = re.findall(scheduling_duration_pattern, metrics_data)
        count_matches = re.findall(scheduling_count_pattern, metrics_data)
        
        if duration_matches and count_matches:
            total_duration = sum(float(d) for d in duration_matches)
            total_count = sum(float(c) for c in count_matches)
            
            if total_count > 0:
                avg_scheduling_time_ms = (total_duration / total_count) * 1000
                scheduling_metrics['avg_scheduling_time_ms'] = avg_scheduling_time_ms
                print(f"Real scheduler average execution time: {avg_scheduling_time_ms:.2f}ms")
        
        # scheduler_framework_extension_point_duration_seconds - detailed plugin timing
        plugin_duration_pattern = r'scheduler_framework_extension_point_duration_seconds_sum{extension_point="([^"]+)".*?} ([\d.]+)'
        plugin_matches = re.findall(plugin_duration_pattern, metrics_data)
        
        plugin_timings = {}
        for plugin_name, duration in plugin_matches:
            plugin_timings[plugin_name] = float(duration) * 1000  # Convert to ms
            
        if plugin_timings:
            scheduling_metrics['plugin_timings'] = plugin_timings
            print(f"Plugin execution times: {plugin_timings}")
        
        # scheduler_pod_scheduling_attempts - scheduling attempts histogram
        attempts_pattern = r'scheduler_pod_scheduling_attempts_bucket{.*?le="([^"]+)".*?} ([\d.]+)'
        attempts_matches = re.findall(attempts_pattern, metrics_data)
        
        if attempts_matches:
            attempts_histogram = {float(le): float(count) for le, count in attempts_matches}
            scheduling_metrics['scheduling_attempts_histogram'] = attempts_histogram
        
        return scheduling_metrics
        
    except Exception as e:
        print(f"Error collecting scheduler metrics: {e}")
        return None

def _get_real_scheduler_execution_time(current_pod_metrics, node_metrics):
    """
    Get real scheduler execution time using actual Kubernetes scheduler metrics.
    Falls back to estimation if scheduler metrics are unavailable.
    """
    # Try to get real scheduler metrics first
    scheduler_metrics = _get_scheduler_timing_metrics()
    
    if scheduler_metrics and 'avg_scheduling_time_ms' in scheduler_metrics:
        print(f"Using real scheduler metrics: {scheduler_metrics['avg_scheduling_time_ms']:.2f}ms")
        return scheduler_metrics['avg_scheduling_time_ms'], scheduler_metrics
    
    # Fallback to estimation if real metrics unavailable
    print("Scheduler metrics unavailable, using estimation method")
    
    if not current_pod_metrics or not node_metrics:
        return 0.0, None
    
    # Estimate based on pods processed and cluster complexity
    pods_processed = len(current_pod_metrics)
    num_nodes = len(node_metrics)
    
    # Vanilla scheduler uses simple bin-packing algorithm
    # Typical execution time: 1-10ms per pod depending on cluster size
    base_time_per_pod = 2.0  # Base 2ms per pod
    complexity_factor = 1 + (num_nodes / 100)  # Slight increase with cluster size
    
    estimated_time_ms = pods_processed * base_time_per_pod * complexity_factor
    
    estimation_details = {
        'method': 'estimation',
        'pods_processed': pods_processed,
        'num_nodes': num_nodes,
        'base_time_per_pod_ms': base_time_per_pod,
        'complexity_factor': complexity_factor
    }
    
    print(f"Estimated scheduler execution time: {estimated_time_ms:.2f}ms")
    return estimated_time_ms, estimation_details

def main():
    """Main function to run the metrics collector."""
    parser = argparse.ArgumentParser(description='Collect metrics from a carbon-aware scheduled Kubernetes cluster')
    parser.add_argument('--output-dir', required=True, help='Base directory to save metrics data')
    parser.add_argument('--experiment-name', required=True, help='Name of the experiment')
    parser.add_argument('--interval', type=int, default=60, help='Metrics collection interval in seconds')
    parser.add_argument('--duration', type=int, default=3600, help='Total duration of metrics collection in seconds')
    parser.add_argument('--namespace', default='default', help='Kubernetes namespace to monitor')
    parser.add_argument('--shrink-factor', type=int, default=1, help='Time shrink factor for simulation')
    parser.add_argument('--forecast-file', default='/root/carbon/scripts/all_forecasts.json', help='Path to carbon intensity forecasts file')
    parser.add_argument('--generate-csv-only', action='store_true', help='Only generate vanilla placement CSV from existing data, do not collect metrics')
    parser.add_argument('--raw-data-dir', help='Directory containing raw data files (for --generate-csv-only mode)')
    
    args = parser.parse_args()
    
    collector = CarbonMetricsCollector(
        output_dir=args.output_dir,
        experiment_name=args.experiment_name,
        collection_interval=args.interval,
        duration=args.duration,
        namespace=args.namespace,
        shrink_factor=args.shrink_factor,
        forecast_file=args.forecast_file
    )
    
    if args.generate_csv_only:
        # Only generate CSV from existing data
        placement_success = collector.generate_vanilla_placement_from_json_data(args.raw_data_dir)
        performance_success = collector.generate_vanilla_performance_from_json_data(args.raw_data_dir)
        sys.exit(0 if (placement_success and performance_success) else 1)
    else:
        # Normal metrics collection
        collector.collect_metrics()


if __name__ == "__main__":
    main()