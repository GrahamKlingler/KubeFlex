from utils.cadvisor import *
from utils.db import *
from utils.kubeapi import *

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
import pytz

def collect_carbon_forecast(db_conn, interval=24):
    # Current date (UTC) minus three years
    current_date = datetime.now(pytz.timezone('UTC')) - timedelta(days=365 * 3)
    current_date_str = current_date.strftime("%Y-%m-%d %H:%M:%S %Z")

    epoch = current_date + timedelta(hours=interval)
    epoch_str = epoch.strftime("%Y-%m-%d %H:%M:%S %Z")

    db_min = []
    breakpoints = []

    # Get the minimum carbon emissions from the db
    try:
        db_min = fetch_min_slope(db_conn, current_date_str, epoch_str)
        logger.info(f"Minimum carbon emissions in the given time range {current_date_str} to {epoch_str}:")
        
        if db_min:
            # Iterate backwards to safely remove elements
            for i in range(len(db_min) - 1, -1, -1):
                # # Remove any inputs where the timezone is in the past
                # if db_min[i][0] < current_date.strftime("%Y-%m-%d %H:%M:%S"):
                #     db_min.pop(i)
                #     continue

                # Change it from a string to a datetime object first
                # Strip timezone info before parsing
                timestamp_str = db_min[i][0].split('+')[0]
                db_min[i][0] = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S") + timedelta(days=365*3)
                db_min[i][0] = db_min[i][0].strftime("%Y-%m-%d %H:%M:%S")
                logger.info(f"Timestamp: {db_min[i][0]}, Region: {db_min[i][1]}, Intensity: {db_min[i][2]}")
        
            # Go through the db_min and check if the region is different from the previous one
            for i in range(1, len(db_min)):
                if db_min[i][1] != db_min[i-1][1]:
                    logger.info(f"New region detected: {db_min[i][1]} at {db_min[i][0]}")
                    breakpoints.append(db_min[i])
        
            logger.info(f"Breakpoints: {breakpoints}")

        else:
            logger.info("No records found in the database for the given time range")
    except Exception as e:
        logger.info(f"Error fetching results: {e}")
    
    return db_min, breakpoints

def migrate_pod(namespace, pod, target_pod, target_node, delete_original):
    
    # Migrate the pod to the new node with the api
    url = "http://0.0.0.0:8000/migrate"
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

def main():
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    # Initialize global variables
    global db_min
    global breakpoints
    db_min = []
    breakpoints = []

    # Load environment variables
    pod_selector = os.getenv('POD_SELECTOR', 'io.kubernetes.pod.namespace=monitor')
    cadvisor_interval = int(os.getenv('POLLING_INTERVAL', '300'))
    forecast_interval = int(os.getenv('FORECAST_INTERVAL', '24'))

    # Connect to cadvisor API
    cadvisor_url = get_cadvisor_url()
    session = create_cadvisor_session()
    if not wait_for_cadvisor(session, cadvisor_url):
        logger.error("cAdvisor not available after timeout")
        return
    
    # Connect to PostgreSQL database
    db_conn = connect_to_db(db_config)
    if not db_conn:
        logger.error("Failed to connect to PostgreSQL database")
        return

    # Load the cluster config    
    load_kubernetes_config()
    nodes_info = list_nodes_with_labels_annotations()
    logger.info(f"Nodes in the cluster: {nodes_info}")

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
    
    # Schedule periodic forecast updates
    scheduler.add_job(
        func=update_forecast_and_schedule,
        trigger='interval',
        hours=forecast_interval,
        name='update_carbon_forecast'
    )
    
    scheduler.start()
    
    try:
        # Keep the main thread alive
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        logger.info("Scheduler shutdown complete")

if __name__ == "__main__":
    
    main()