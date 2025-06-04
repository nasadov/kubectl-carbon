#!/usr/bin/env python3
"""
Algorithm Comparison Script

Compares the performance and carbon metrics between vanilla, heuristic, and global-optimal algorithms.
Generates comparative plots and analysis.
"""

import argparse
import json
import os
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime
import numpy as np
from typing import Dict, List, Any, Tuple

# Handle numpy compatibility
try:
    np.Inf  # Check if np.Inf exists
except AttributeError:
    np.Inf = np.inf  # For numpy 2.0+ compatibility

class AlgorithmComparator:
    """Compare metrics between different scheduling algorithms."""
    
    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        self.comparison_dir = os.path.join(output_dir, "algorithm_comparison")
        os.makedirs(self.comparison_dir, exist_ok=True)
        
        # Set up plotting style
        try:
            plt.style.use('seaborn')
        except:
            plt.style.use('default')
        sns.set_palette("husl")
        
    def load_experiment_data(self, experiment_dir: str) -> Dict[str, Any]:
        """Load experiment data from directory."""
        data = {
            'algorithm': self._extract_algorithm_from_path(experiment_dir),
            'experiment_name': os.path.basename(experiment_dir),
            'config': {},
            'raw_data': {}
        }
        
        # Load configuration
        config_file = os.path.join(experiment_dir, "experiment_config.json")
        if os.path.exists(config_file):
            with open(config_file, 'r') as f:
                data['config'] = json.load(f)
        
        # Load raw data
        raw_data_dir = os.path.join(experiment_dir, "raw_data")
        if os.path.exists(raw_data_dir):
            for file_name in os.listdir(raw_data_dir):
                if file_name.endswith('.json'):
                    metric_name = file_name[:-5]  # Remove .json extension
                    file_path = os.path.join(raw_data_dir, file_name)
                    try:
                        with open(file_path, 'r') as f:
                            data['raw_data'][metric_name] = json.load(f)
                    except Exception as e:
                        print(f"Warning: Failed to load {file_path}: {e}")
                        
                elif file_name.endswith('.csv'):
                    metric_name = file_name[:-4]  # Remove .csv extension
                    file_path = os.path.join(raw_data_dir, file_name)
                    try:
                        data['raw_data'][metric_name + '_csv'] = pd.read_csv(file_path)
                    except Exception as e:
                        print(f"Warning: Failed to load {file_path}: {e}")
        
        return data
    
    def _extract_algorithm_from_path(self, path: str) -> str:
        """Extract algorithm name from experiment path."""
        basename = os.path.basename(path)
        if 'vanilla' in basename.lower():
            return 'vanilla'
        elif 'heuristic' in basename.lower():
            return 'heuristic'
        elif 'global-optimal' in basename.lower():
            return 'global-optimal'
        else:
            return 'unknown'
    
    def compare_carbon_metrics(self, experiments: List[Dict[str, Any]]) -> None:
        """Compare carbon metrics across algorithms."""
        print("Generating carbon metrics comparison...")
        
        fig, axes = plt.subplots(2, 2, figsize=(15, 12))
        fig.suptitle('Carbon Metrics Comparison Across Algorithms', fontsize=16, fontweight='bold')
        
        # Prepare data for comparison
        carbon_data = []
        for exp in experiments:
            if 'carbon_metrics' in exp['raw_data']:
                metrics = exp['raw_data']['carbon_metrics']
                for metric in metrics:
                    carbon_data.append({
                        'algorithm': exp['algorithm'],
                        'experiment': exp['experiment_name'],
                        'timestamp': metric.get('timestamp', 0),
                        'total_carbon_rate': metric.get('total_carbon_rate', 0),
                        'total_power_watts': metric.get('total_power_watts', 0),
                        'carbon_intensity': metric.get('carbon_intensity', 0),
                        'operational_carbon_rate': metric.get('total_operational_carbon_rate', 0),
                        'embodied_carbon_rate': metric.get('total_embodied_carbon_rate', 0)
                    })
        
        if not carbon_data:
            print("No carbon metrics data found")
            return
            
        df = pd.DataFrame(carbon_data)
        
        # Plot 1: Total Carbon Rate Over Time
        ax = axes[0, 0]
        for alg in df['algorithm'].unique():
            alg_data = df[df['algorithm'] == alg]
            if len(alg_data) > 0:
                # Convert timestamp to relative time (minutes)
                start_time = alg_data['timestamp'].min()
                rel_time = ((alg_data['timestamp'] - start_time) / 60).values
                carbon_rate = alg_data['total_carbon_rate'].values
                ax.plot(rel_time, carbon_rate, label=alg, marker='o', markersize=4)
        
        ax.set_title('Total Carbon Rate Over Time')
        ax.set_xlabel('Time (minutes)')
        ax.set_ylabel('Carbon Rate (gCO₂/sec)')
        ax.legend()
        ax.grid(True, alpha=0.3)
        
        # Plot 2: Average Carbon Rate by Algorithm
        ax = axes[0, 1]
        avg_carbon = df.groupby('algorithm')['total_carbon_rate'].mean()
        bars = ax.bar(avg_carbon.index, avg_carbon.values)
        ax.set_title('Average Total Carbon Rate')
        ax.set_ylabel('Carbon Rate (gCO₂/sec)')
        ax.set_xlabel('Algorithm')
        
        # Add value labels on bars
        for bar in bars:
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height,
                   f'{height:.2f}', ha='center', va='bottom')
        
        # Plot 3: Power Consumption Comparison
        ax = axes[1, 0]
        avg_power = df.groupby('algorithm')['total_power_watts'].mean()
        bars = ax.bar(avg_power.index, avg_power.values, color='orange')
        ax.set_title('Average Power Consumption')
        ax.set_ylabel('Power (Watts)')
        ax.set_xlabel('Algorithm')
        
        # Add value labels on bars
        for bar in bars:
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height,
                   f'{height:.1f}W', ha='center', va='bottom')
        
        # Plot 4: Carbon Intensity by Algorithm
        ax = axes[1, 1]
        avg_intensity = df.groupby('algorithm')['carbon_intensity'].mean()
        bars = ax.bar(avg_intensity.index, avg_intensity.values, color='green')
        ax.set_title('Average Carbon Intensity')
        ax.set_ylabel('Carbon Intensity (gCO₂/kWh)')
        ax.set_xlabel('Algorithm')
        
        # Add value labels on bars
        for bar in bars:
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height,
                   f'{height:.0f}', ha='center', va='bottom')
        
        plt.tight_layout()
        output_file = os.path.join(self.comparison_dir, "carbon_metrics_comparison.png")
        plt.savefig(output_file, dpi=300, bbox_inches='tight')
        plt.close()
        print(f"Carbon metrics comparison saved to: {output_file}")
    
    def compare_performance_metrics(self, experiments: List[Dict[str, Any]]) -> None:
        """Compare performance metrics across algorithms."""
        print("Generating performance metrics comparison...")
        
        fig, axes = plt.subplots(2, 2, figsize=(15, 12))
        fig.suptitle('Performance Metrics Comparison Across Algorithms', fontsize=16, fontweight='bold')
        
        # Prepare data for comparison
        perf_data = []
        for exp in experiments:
            if 'performance' in exp['raw_data']:
                metrics = exp['raw_data']['performance']
                for metric in metrics:
                    perf_data.append({
                        'algorithm': exp['algorithm'],
                        'experiment': exp['experiment_name'],
                        'timestamp': metric.get('timestamp', 0),
                        'running_pods': metric.get('running_pods', 0),
                        'pending_pods': metric.get('pending_pods', 0),
                        'failed_pods': metric.get('failed_pods', 0),
                        'avg_scheduling_latency': metric.get('avg_scheduling_latency'),
                        'throughput': metric.get('throughput', 0)
                    })
        
        if not perf_data:
            print("No performance metrics data found")
            return
            
        df = pd.DataFrame(perf_data)
        
        # Plot 1: Pod Status Over Time
        ax = axes[0, 0]
        for alg in df['algorithm'].unique():
            alg_data = df[df['algorithm'] == alg]
            if len(alg_data) > 0:
                start_time = alg_data['timestamp'].min()
                rel_time = ((alg_data['timestamp'] - start_time) / 60).values
                running_pods = alg_data['running_pods'].values
                ax.plot(rel_time, running_pods, label=f'{alg} (running)', marker='o', markersize=4)
        
        ax.set_title('Running Pods Over Time')
        ax.set_xlabel('Time (minutes)')
        ax.set_ylabel('Number of Running Pods')
        ax.legend()
        ax.grid(True, alpha=0.3)
        
        # Plot 2: Final Pod Counts
        ax = axes[0, 1]
        final_counts = df.groupby('algorithm').agg({
            'running_pods': 'max',
            'failed_pods': 'max'
        })
        
        x = np.arange(len(final_counts.index))
        width = 0.35
        
        bars1 = ax.bar(x - width/2, final_counts['running_pods'], width, label='Running', color='green')
        bars2 = ax.bar(x + width/2, final_counts['failed_pods'], width, label='Failed', color='red')
        
        ax.set_title('Final Pod Status by Algorithm')
        ax.set_ylabel('Number of Pods')
        ax.set_xlabel('Algorithm')
        ax.set_xticks(x)
        ax.set_xticklabels(final_counts.index)
        ax.legend()
        
        # Add value labels on bars
        for bars in [bars1, bars2]:
            for bar in bars:
                height = bar.get_height()
                ax.text(bar.get_x() + bar.get_width()/2., height,
                       f'{int(height)}', ha='center', va='bottom')
        
        # Plot 3: Scheduling Latency
        ax = axes[1, 0]
        latency_data = df[df['avg_scheduling_latency'].notna()]
        if len(latency_data) > 0:
            avg_latency = latency_data.groupby('algorithm')['avg_scheduling_latency'].mean()
            bars = ax.bar(avg_latency.index, avg_latency.values, color='purple')
            ax.set_title('Average Scheduling Latency')
            ax.set_ylabel('Latency (seconds)')
            ax.set_xlabel('Algorithm')
            
            # Add value labels on bars
            for bar in bars:
                height = bar.get_height()
                ax.text(bar.get_x() + bar.get_width()/2., height,
                       f'{height:.2f}s', ha='center', va='bottom')
        else:
            ax.text(0.5, 0.5, 'No latency data available', ha='center', va='center', transform=ax.transAxes)
            ax.set_title('Average Scheduling Latency')
        
        # Plot 4: Throughput
        ax = axes[1, 1]
        throughput_data = df[df['throughput'] > 0]
        if len(throughput_data) > 0:
            avg_throughput = throughput_data.groupby('algorithm')['throughput'].mean()
            bars = ax.bar(avg_throughput.index, avg_throughput.values, color='cyan')
            ax.set_title('Average Throughput')
            ax.set_ylabel('Pods/minute')
            ax.set_xlabel('Algorithm')
            
            # Add value labels on bars
            for bar in bars:
                height = bar.get_height()
                ax.text(bar.get_x() + bar.get_width()/2., height,
                       f'{height:.2f}', ha='center', va='bottom')
        else:
            ax.text(0.5, 0.5, 'No throughput data available', ha='center', va='center', transform=ax.transAxes)
            ax.set_title('Average Throughput')
        
        plt.tight_layout()
        output_file = os.path.join(self.comparison_dir, "performance_metrics_comparison.png")
        plt.savefig(output_file, dpi=300, bbox_inches='tight')
        plt.close()
        print(f"Performance metrics comparison saved to: {output_file}")
    
    def compare_node_utilization(self, experiments: List[Dict[str, Any]]) -> None:
        """Compare node utilization across algorithms."""
        print("Generating node utilization comparison...")
        
        fig, axes = plt.subplots(2, 2, figsize=(15, 12))
        fig.suptitle('Node Utilization Comparison Across Algorithms', fontsize=16, fontweight='bold')
        
        # Prepare data for comparison
        node_data = []
        for exp in experiments:
            if 'nodes' in exp['raw_data']:
                nodes = exp['raw_data']['nodes']
                for node in nodes:
                    node_data.append({
                        'algorithm': exp['algorithm'],
                        'experiment': exp['experiment_name'],
                        'node_name': node.get('node_name', 'unknown'),
                        'region': node.get('region', 'unknown'),
                        'cpu_utilization': node.get('cpu_utilization', 0),
                        'power_draw': node.get('power_draw', 0),
                        'timestamp': node.get('timestamp', 0)
                    })
        
        if not node_data:
            print("No node metrics data found")
            return
            
        df = pd.DataFrame(node_data)
        
        # Plot 1: CPU Utilization by Algorithm
        ax = axes[0, 0]
        if len(df) > 0:
            sns.boxplot(data=df, x='algorithm', y='cpu_utilization', ax=ax)
            ax.set_title('CPU Utilization Distribution')
            ax.set_ylabel('CPU Utilization (%)')
            ax.set_xlabel('Algorithm')
        
        # Plot 2: Power Draw by Algorithm
        ax = axes[0, 1]
        if len(df) > 0:
            sns.boxplot(data=df, x='algorithm', y='power_draw', ax=ax)
            ax.set_title('Power Draw Distribution')
            ax.set_ylabel('Power Draw (Watts)')
            ax.set_xlabel('Algorithm')
        
        # Plot 3: CPU Utilization by Region
        ax = axes[1, 0]
        if len(df) > 0:
            avg_cpu_by_region = df.groupby(['algorithm', 'region'])['cpu_utilization'].mean().unstack(fill_value=0)
            avg_cpu_by_region.plot(kind='bar', ax=ax)
            ax.set_title('Average CPU Utilization by Region')
            ax.set_ylabel('CPU Utilization (%)')
            ax.set_xlabel('Algorithm')
            ax.legend(title='Region', bbox_to_anchor=(1.05, 1), loc='upper left')
            plt.setp(ax.get_xticklabels(), rotation=45)
        
        # Plot 4: Power Draw by Region
        ax = axes[1, 1]
        if len(df) > 0:
            avg_power_by_region = df.groupby(['algorithm', 'region'])['power_draw'].mean().unstack(fill_value=0)
            avg_power_by_region.plot(kind='bar', ax=ax)
            ax.set_title('Average Power Draw by Region')
            ax.set_ylabel('Power Draw (Watts)')
            ax.set_xlabel('Algorithm')
            ax.legend(title='Region', bbox_to_anchor=(1.05, 1), loc='upper left')
            plt.setp(ax.get_xticklabels(), rotation=45)
        
        plt.tight_layout()
        output_file = os.path.join(self.comparison_dir, "node_utilization_comparison.png")
        plt.savefig(output_file, dpi=300, bbox_inches='tight')
        plt.close()
        print(f"Node utilization comparison saved to: {output_file}")
    
    def generate_summary_report(self, experiments: List[Dict[str, Any]]) -> None:
        """Generate a summary report comparing all algorithms."""
        print("Generating summary report...")
        
        report = {
            'comparison_timestamp': datetime.now().isoformat(),
            'experiments_compared': [],
            'summary_metrics': {}
        }
        
        # Collect summary data for each experiment
        for exp in experiments:
            exp_summary = {
                'algorithm': exp['algorithm'],
                'experiment_name': exp['experiment_name'],
                'config': exp['config']
            }
            
            # Calculate summary metrics
            if 'carbon_metrics' in exp['raw_data']:
                carbon_metrics = exp['raw_data']['carbon_metrics']
                if carbon_metrics:
                    total_carbon = sum(m.get('total_carbon_rate', 0) for m in carbon_metrics)
                    avg_carbon = total_carbon / len(carbon_metrics) if carbon_metrics else 0
                    exp_summary['avg_carbon_rate'] = avg_carbon
                    exp_summary['total_emissions'] = total_carbon * len(carbon_metrics)  # Rough estimate
            
            if 'performance' in exp['raw_data']:
                perf_metrics = exp['raw_data']['performance']
                if perf_metrics:
                    final_perf = perf_metrics[-1] if perf_metrics else {}
                    exp_summary['final_running_pods'] = final_perf.get('running_pods', 0)
                    exp_summary['final_failed_pods'] = final_perf.get('failed_pods', 0)
            
            report['experiments_compared'].append(exp_summary)
        
        # Calculate comparative metrics
        if len(experiments) > 1:
            algorithms = [exp['algorithm'] for exp in experiments]
            carbon_rates = [exp.get('avg_carbon_rate', 0) for exp in report['experiments_compared']]
            
            if carbon_rates and max(carbon_rates) > 0:
                best_carbon_idx = carbon_rates.index(min(carbon_rates))
                report['best_carbon_algorithm'] = algorithms[best_carbon_idx]
                report['carbon_improvement'] = {
                    'best_rate': min(carbon_rates),
                    'worst_rate': max(carbon_rates),
                    'improvement_percent': ((max(carbon_rates) - min(carbon_rates)) / max(carbon_rates)) * 100
                }
        
        # Save report
        report_file = os.path.join(self.comparison_dir, "comparison_summary.json")
        with open(report_file, 'w') as f:
            json.dump(report, f, indent=2)
        
        print(f"Summary report saved to: {report_file}")
        
        # Print key findings
        print("\n=== COMPARISON SUMMARY ===")
        for exp in report['experiments_compared']:
            print(f"\n{exp['algorithm'].upper()} Algorithm:")
            print(f"  - Experiment: {exp['experiment_name']}")
            if 'avg_carbon_rate' in exp:
                print(f"  - Avg Carbon Rate: {exp['avg_carbon_rate']:.3f} gCO₂/sec")
            if 'final_running_pods' in exp:
                print(f"  - Final Running Pods: {exp['final_running_pods']}")
                print(f"  - Final Failed Pods: {exp['final_failed_pods']}")
        
        if 'best_carbon_algorithm' in report:
            print(f"\n🌱 Best Carbon Performance: {report['best_carbon_algorithm'].upper()}")
            if 'carbon_improvement' in report:
                improvement = report['carbon_improvement']['improvement_percent']
                print(f"   Improvement over worst: {improvement:.1f}%")

def main():
    parser = argparse.ArgumentParser(description="Compare metrics between different scheduling algorithms")
    parser.add_argument("--vanilla-dir", required=True, help="Path to vanilla experiment directory")
    parser.add_argument("--heuristic-dir", required=True, help="Path to heuristic experiment directory") 
    parser.add_argument("--global-optimal-dir", required=True, help="Path to global-optimal experiment directory")
    parser.add_argument("--output-dir", default="/root/carbon/benchmark_results", 
                       help="Output directory for comparison plots")
    
    args = parser.parse_args()
    
    # Initialize comparator
    comparator = AlgorithmComparator(args.output_dir)
    
    # Load experiment data
    experiments = []
    for alg_dir in [args.vanilla_dir, args.heuristic_dir, args.global_optimal_dir]:
        if os.path.exists(alg_dir):
            print(f"Loading data from: {alg_dir}")
            exp_data = comparator.load_experiment_data(alg_dir)
            experiments.append(exp_data)
        else:
            print(f"Warning: Directory not found: {alg_dir}")
    
    if len(experiments) < 2:
        print("Error: Need at least 2 experiments to compare")
        return
    
    print(f"\nComparing {len(experiments)} experiments...")
    
    # Generate comparisons
    comparator.compare_carbon_metrics(experiments)
    comparator.compare_performance_metrics(experiments)
    comparator.compare_node_utilization(experiments)
    comparator.generate_summary_report(experiments)
    
    print(f"\nComparison complete! Results saved to: {comparator.comparison_dir}")

if __name__ == "__main__":
    main()
