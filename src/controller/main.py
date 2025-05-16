from cadvisor import *
from db import *
from kubeapi import *

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
import pytz
from datetime import datetime
import time

import numpy as np
import matplotlib.pyplot as plt
import requests
import json
import base64
from io import BytesIO
from threading import Thread

"""
curl -X POST http://0.0.0.0:8008/migrate \
  -H "Content-Type: application/json" \
  -d '{
    "namespace": "foo",
    "pod": "test-pod",
    "target_pod": "test-pod-migrated",
    "target_node": "desktop-worker2",
    "delete_original": true
  }'
"""

def migrate_pod(namespace, pod, target_pod, target_node, delete_original):
    
    # Migrate the pod to the new node with the api
    url = "http://0.0.0.0:8008/migrate"
    headers = {"Content-Type": "application/json"}
    json_body = {
        "namespace": namespace,
        "pod": pod,
        "target_pod": target_pod,
        "target_node": target_node,
        "delete_original": delete_original,
    }

    logger.info("Migrating test pod to the new node...")
    response = requests.post(url, json=json_body, headers=headers)
    logger.info(f"Status Code: {response.status_code}")
    logger.info(f"Response: {response.text}")

def check_and_migrate_pods(namespace, region, db_data, nodes_info):
    logger.info(f"Checking and migrating pods for region: {region}")

    # Find nodes with the correct REGION label
    target_nodes = [n['name'] for n in nodes_info if n['labels'].get('REGION') == region]
    if not target_nodes:
        logger.warning(f"No nodes found with REGION={region}")
        return

    # Get all pods in the namespace
    pods = list_resources(namespace, output_format="table", include_system=False)
    logger.info(f"Pods in the namespace {namespace}: {pods}")

    for pod in pods:
        logger.info(f"{pod['name']}, {pod['region']}, {pod['age']}")

    # Move any that are on a different region to the min region
    for pod in pods:
        if pod.get('region') != region:
            logger.info(f"Migrating pod {pod['name']} to the min region")

            target_pod = pod['name'] + '-migrated'
            target_node = target_nodes[0]
            
            migrate_pod(
                namespace,
                pod['name'],
                target_pod,
                target_node,
                pod.get('delete_original', True)
            )

def schedule_migration_jobs(scheduler, breakpoints, db_data, nodes_info, pod_selector):
    for bp in breakpoints:
        logger.info(f"Scheduling migration job for {bp}")
        timestamp, region, intensity = bp
        trigger = DateTrigger(run_date=timestamp)
        
        logger.info(f"Adding job to scheduler: {f'migrate_pods_to_{region}_at_{timestamp}'}")
        scheduler.add_job(
            func=check_and_migrate_pods,
            trigger=trigger,
            args=[pod_selector, region, db_data, nodes_info],
            name=f'migrate_pods_to_{region}_at_{timestamp}'
        )

def send_plot_to_external_host(plot_data, pod_name, pod_region, external_host_url):
    """Send plot data to an external host"""
    try:
        # Convert plot to base64
        buffer = BytesIO()
        plt.savefig(buffer, format='png')
        buffer.seek(0)
        plot_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
        
        # Prepare payload
        payload = {
            'pod_name': pod_name,
            'pod_region': pod_region,
            'plot_data': plot_base64,
            'timestamp': datetime.now(pytz.UTC).isoformat()
        }
        
        # Send to external host
        response = requests.post(
            external_host_url,
            json=payload,
            headers={'Content-Type': 'application/json'}
        )
        
        if response.status_code == 200:
            logger.info(f"Successfully sent plot data for pod {pod_name} to external host")
        else:
            logger.error(f"Failed to send plot data. Status code: {response.status_code}")
            
    except Exception as e:
        logger.error(f"Error sending plot data: {str(e)}")
    finally:
        buffer.close()

def send_raw_data_to_external_host(pod_data, pod_name, pod_region, external_host_url):
    """Send raw carbon intensity data to an external host"""
    try:
        # Prepare payload
        payload = {
            'pod_name': pod_name,
            'pod_region': pod_region,
            'start_time': pod_data['start_time'].isoformat(),
            'end_time': pod_data['end_time'].isoformat(),
            'carbon_intensity_data': pod_data['carbon_intensity'],
            'min_forecast_data': pod_data['min_forecast'],
            'timestamp': datetime.now(pytz.UTC).isoformat()
        }
        
        # Send to external host
        response = requests.post(
            external_host_url,
            json=payload,
            headers={'Content-Type': 'application/json'}
        )
        
        if response.status_code == 200:
            logger.info(f"Successfully sent raw data for pod {pod_name} to external host")
        else:
            logger.error(f"Failed to send raw data. Status code: {response.status_code}")
            
    except Exception as e:
        logger.error(f"Error sending raw data: {str(e)}")

def run_scheduler(scheduler):
    """Run the scheduler in a separate thread"""
    try:
        scheduler.start()
        while True:
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        logger.info("Scheduler shutdown complete")

def main(): 
    # Extract the logs of the graphs (html)
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    # Initialize global variables
    global db_min
    global breakpoints
    db_min = []
    breakpoints = []

    # Load environment variables
    pod_selector = os.getenv('POD_SELECTOR', 'io.kubernetes.pod.namespace=monitor')
    forecast_interval = int(os.getenv('FORECAST_INTERVAL', '72'))
    server_url = os.getenv('CARBON_SERVER_URL', 'http://metadata:8008')
    server_port = int(os.getenv('SERVER_PORT', 8008))

    # # Connect to cadvisor API
    # cadvisor_url = get_cadvisor_url()
    # session = create_cadvisor_session()
    # if not wait_for_cadvisor(session, cadvisor_url):
    #     logger.error("cAdvisor not available after timeout")
    #     return
    
    # Connect to PostgreSQL database
    db_conn = connect_to_db(db_config)
    if not db_conn:
        logger.error("Failed to connect to PostgreSQL database")
        return

    # Load the cluster config    
    load_kubernetes_config()
    nodes_info = list_nodes_with_labels_annotations()
    for node in nodes_info:
        logger.info(f"Node: {node['name']}, Labels: {node['labels']}, Annotations: {node['annotations']}")

    # Initialize scheduler
    scheduler = BackgroundScheduler()

    def update_forecast_and_schedule():
        global db_min, breakpoints
        logger.info("Updating carbon forecast and migration schedule...")
        
        # Get new forecast data
        db_min, breakpoints = collect_carbon_forecast(db_conn, forecast_interval)
        
        # Clear existing jobs
        scheduler.remove_all_jobs()
        
        # Schedule new migration jobs
        schedule_migration_jobs(scheduler, 
                              breakpoints, 
                              db_min, 
                              nodes_info, 
                              pod_selector.split('=')[1])
        
        logger.info("Forecast and migration schedule updated successfully")

    # Schedule the initial forecast update
    update_forecast_and_schedule()

    # check_and_migrate_pods("foo", "NE", db_conn, nodes_info)
    # migrate_pod("foo", "test-pod", "test-pod-migrated", "desktop-worker2", False)

    # pods = list_resources("foo")
    # for pod in pods:
    #     pod_region = pod["annotations"]["REGION"]
    #     pod_start_time = pod["age"]
    #     pod_name = pod["name"]
    #     expected_duration = int(pod["annotations"]["EXPECTED_DURATION"])  # This is in hours
    #     pod_end_time = pod_start_time + timedelta(hours=expected_duration)        

    #     logger.info(f"{pod_region}, {pod_start_time}, {pod_end_time}, {expected_duration}")

    #     if pod_end_time < datetime.now(pytz.timezone('UTC')):
    #         logger.info(f"Error: Pod {pod_name} has extended past its duration")
    #     else:
    #         remaining_time = (pod_end_time - datetime.now(pytz.timezone('UTC'))).total_seconds() / 3600  # Convert seconds to hours

    #         pod_carbon = collect_region_forecast(db_conn, pod_region, remaining_time)

    #         # Filter db_min to only include timestamps within pod's lifetime
    #         min_forecast = [
    #             point for point in db_min 
    #             if pod_start_time <= datetime.strptime(point[0], "%Y-%m-%d %H:%M:%S").replace(tzinfo=pytz.UTC) <= pod_end_time
    #         ]
            
    #         logger.info(f"Found {len(min_forecast)} forecast points within pod {pod_name}'s lifetime")

    #         # Calculate cumulative sums
    #         pod_carbon_cumsum = np.cumsum([point[2] for point in pod_carbon])
    #         min_forecast_cumsum = np.cumsum([point[2] for point in min_forecast])

    #         # Create the plot
    #         plt.figure(figsize=(12, 6))
    #         plt.plot([point[0] for point in pod_carbon], pod_carbon_cumsum, label=f'Cumulative Carbon Intensity - {pod_region}')
    #         plt.plot([point[0] for point in min_forecast], min_forecast_cumsum, label='Cumulative Minimum Carbon Intensity')
            
    #         plt.xlabel('Time')
    #         plt.ylabel('Cumulative Carbon Intensity')
    #         plt.title(f'Cumulative Carbon Intensity Over Time - Pod: {pod_name}')
    #         plt.xticks(rotation=45)
    #         plt.legend()
    #         plt.grid(True)
            
    #         # Adjust layout to prevent label cutoff
    #         plt.tight_layout()
            
    #         # Save the plot locally
    #         plot_filename = f'plot_{pod_name}.png'
    #         plt.savefig(plot_filename)
            
    #         # Send plot to external host
    #         send_plot_to_external_host(plt, pod_name, pod_region, server_url)
            
    #         # Send raw data to external host
    #         pod_data = {
    #             'region': pod_region,
    #             'start_time': pod_start_time,
    #             'end_time': pod_end_time,
    #             'carbon_intensity': pod_carbon,
    #             'min_forecast': min_forecast
    #         }
    #         send_raw_data_to_external_host(pod_data, pod_name, pod_region, server_url)
            
    #         plt.close()
            
    #         logger.info(f"Generated carbon intensity plot: {plot_filename}")

    # Schedule periodic forecast updates
    scheduler.add_job(
        func=update_forecast_and_schedule,
        trigger='interval',
        hours=forecast_interval,
        name='update_carbon_forecast'
    )
    
    # Start scheduler in a separate thread
    scheduler_thread = Thread(target=run_scheduler, args=(scheduler,))
    scheduler_thread.daemon = True
    scheduler_thread.start()
    
    # Start the server in the main thread
    try:
        time.sleep(100)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        scheduler.shutdown()
        logger.info("Shutdown complete")

if __name__ == "__main__":
    main()