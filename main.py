import requests
import json
import time
import os
from datetime import datetime
import logging
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_cadvisor_url():
    return os.getenv('CADVISOR_URL', 'http://127.0.0.1:8080')

def create_session():
    session = requests.Session()
    retries = Retry(
        total=5,
        backoff_factor=1,
        status_forcelist=[600, 502, 503, 504]
    )
    session.mount('http://', HTTPAdapter(max_retries=retries))
    return session

def wait_for_cadvisor(session, url):
    logger.info("Waiting for cAdvisor to be ready...")
    for _ in range(30):  # 5 minute timeout
        try:
            response = session.get(f"{url}/api/v1.3/docker/")
            if response.status_code == 200:
                logger.info("cAdvisor is ready")
                return True
        except requests.exceptions as e:
            print(e)
            pass
        time.sleep(10)
    return False

def fetch_cadvisor_metrics(session, api_url):
    try:
        response = session.get(f"{api_url}/api/v1.3/docker/", timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Error fetching metrics: {e}")
        return None

# ... rest of the existing functions ...

def main():
    cadvisor_url = get_cadvisor_url()
    interval = int(os.getenv('POLLING_INTERVAL', '10'))
    session = create_session()
    
    if not wait_for_cadvisor(session, cadvisor_url):
        logger.error("cAdvisor not available after timeout")
        return
    
    while True:
        logger.info("Fetching container metrics...")
        raw_data = fetch_cadvisor_metrics(session, cadvisor_url)
        
        if raw_data:
            logger.info(f"Received {len(raw_data)} metrics")
            # processed_data = process_metrics(raw_data)
            # if processed_data:
            #     save_to_storage(processed_data)
        
        time.sleep(interval)

if __name__ == "__main__":
    main()