from http.server import HTTPServer, BaseHTTPRequestHandler
import json
from datetime import datetime, timedelta
import os
import logging
import pytz
import sys
from pathlib import Path
from kubernetes import client, config

# Import db functions from the same directory
# Since both files are in the same directory, we can import directly
import db

import plotly.graph_objects as go

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load Kubernetes configuration
def load_kubernetes_config():
    """Load Kubernetes configuration."""
    try:
        config.load_incluster_config()
        logger.info("Using in-cluster Kubernetes configuration")
    except:
        try:
            config.load_kube_config()
            logger.info("Using kubeconfig Kubernetes configuration")
        except Exception as e:
            logger.error(f"Failed to load Kubernetes configuration: {e}")
            return False
    return True

def list_resources(namespace: str):
    """List all pods in a namespace with their metadata."""
    try:
        load_kubernetes_config()
        api = client.CoreV1Api()
        pods = api.list_namespaced_pod(namespace=namespace)
        
        resources = []
        for pod in pods.items:
            # Calculate pod age
            creation_time = pod.metadata.creation_timestamp
            if creation_time:
                age = creation_time.replace(tzinfo=pytz.UTC)
            else:
                age = datetime.now(pytz.UTC)
            
            resource_info = {
                'name': pod.metadata.name,
                'namespace': pod.metadata.namespace,
                'age': age,
                'annotations': pod.metadata.annotations or {},
                'labels': pod.metadata.labels or {}
            }
            resources.append(resource_info)
        
        return resources
    except Exception as e:
        logger.error(f"Error listing resources: {e}")
        return []

# To access the server, forward the port 8008 to your local machine:
#   kubectl port-forward svc/metadata-service 8008:8008

# To create a plot, run the following command:
#   curl -X POST http://localhost:8008 -H "Content-Type: application/json" -d '{"pod_name": "test-pod", "pod_region": "TEN", "pod_namespace": "test-namespace"}'

# To access the plots, run the following command:
#   curl http://localhost:8008/plot_test-pod.html -o plot.html

class CarbonDataHandler(BaseHTTPRequestHandler):
    def handle_combined_min_forecast(self, duration, storage_path, start_time_override=None):
        """Handle combined min-forecast query: returns min forecast + forecasts for all regions in min forecast"""
        try:
            interval = int(duration)

            # Connect to database
            db_conn = db.connect_to_db(db.db_config)

            # Ensure database functions exist
            try:
                with db_conn.cursor() as cur:
                    cur.execute("""
                        CREATE OR REPLACE FUNCTION get_min_intensity_records(
                            start_date TIMESTAMP,
                            end_date TIMESTAMP
                        )
                        RETURNS TEXT[] AS $$
                        DECLARE
                            r RECORD;
                            results_array TEXT[] := ARRAY[]::TEXT[];
                        BEGIN
                            FOR r IN
                                SELECT source, datetime, carbon_intensity_direct_avg
                                FROM public.table
                                WHERE datetime::TIMESTAMP BETWEEN start_date AND end_date
                                AND (datetime::TIMESTAMP, carbon_intensity_direct_avg) IN (
                                    SELECT datetime::TIMESTAMP, MIN(carbon_intensity_direct_avg)
                                    FROM public.table
                                    WHERE datetime::TIMESTAMP BETWEEN start_date AND end_date
                                    GROUP BY datetime::TIMESTAMP
                                )
                                ORDER BY datetime::TIMESTAMP DESC
                            LOOP
                                results_array := array_append(results_array, 
                                    r.source || ' | ' || r.datetime || ' | ' || r.carbon_intensity_direct_avg
                                );
                            END LOOP;

                            RETURN results_array;
                        END;
                        $$ LANGUAGE plpgsql;
                    """)
                    
                    cur.execute("""
                        CREATE OR REPLACE FUNCTION get_records_by_source(
                            start_date TIMESTAMP,
                            end_date TIMESTAMP,
                            source_region TEXT
                        )
                        RETURNS TEXT[] AS $$
                        DECLARE
                            r RECORD;
                            results_array TEXT[] := ARRAY[]::TEXT[];
                        BEGIN
                            FOR r IN
                                SELECT source, datetime, carbon_intensity_direct_avg
                                FROM public.table
                                WHERE datetime::TIMESTAMP BETWEEN start_date AND end_date
                                AND source = source_region
                                ORDER BY datetime::TIMESTAMP DESC
                            LOOP
                                results_array := array_append(results_array, 
                                    r.source || ' | ' || r.datetime || ' | ' || r.carbon_intensity_direct_avg
                                );
                            END LOOP;

                            RETURN results_array;
                        END;
                        $$ LANGUAGE plpgsql;
                    """)
                    db_conn.commit()
                    logger.info("Database functions created/updated successfully")
            except Exception as func_error:
                logger.warning(f"Error creating/updating database functions: {func_error}")
            
            # Use start_time_override from request body if provided, otherwise fall back to env var
            if start_time_override is not None:
                try:
                    scheduler_time = float(start_time_override)
                    logger.info(f"Using start_time override from request: {scheduler_time}")
                except (ValueError, TypeError):
                    logger.warning(f"Invalid start_time_override: {start_time_override}, falling back to env var")
                    scheduler_time = None
            else:
                scheduler_time = None

            if scheduler_time is None:
                scheduler_time = os.getenv('SCHEDULER_TIME')
                if scheduler_time:
                    try:
                        scheduler_time = float(scheduler_time)
                        logger.info(f"Using scheduler time from ConfigMap: {scheduler_time}")
                    except (ValueError, TypeError):
                        logger.warning(f"Invalid SCHEDULER_TIME environment variable: {scheduler_time}, using default")
                        scheduler_time = None
                else:
                    logger.warning("SCHEDULER_TIME not set, using current time minus 3 years as fallback")
                    scheduler_time = None
            
            # Check if table exists before querying
            with db_conn.cursor() as cur:
                cur.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_schema = 'public' AND table_name = 'table'
                    )
                """)
                table_exists = cur.fetchone()[0]
                
                if not table_exists:
                    raise ValueError(f"Database table 'public.table' does not exist. Please ensure the db-upload job has completed successfully.")
            
            # Fetch minimum forecast
            logger.info(f"Fetching minimum forecast for duration: {interval} hours")
            min_forecast, _ = db.collect_carbon_forecast(db_conn, interval, scheduler_time=scheduler_time)
            
            if not min_forecast:
                raise ValueError(f"No minimum forecast data found for duration {interval} hours. The database may be empty or the time range has no data.")
            
            logger.info(f"Fetched {len(min_forecast)} data points for minimum forecast")
            
            # Extract unique regions from min forecast
            unique_regions = set()
            formatted_min_forecast = []
            for point in min_forecast:
                if len(point) >= 3:
                    formatted_min_forecast.append([point[0], point[1], float(point[2])])
                    unique_regions.add(point[1])
            
            unique_regions = sorted(list(unique_regions))
            logger.info(f"Found {len(unique_regions)} unique regions in minimum forecast: {unique_regions}")
            
            # Fetch forecasts for each region
            region_forecasts = {}
            for region in unique_regions:
                logger.info(f"Fetching forecast for region: {region}")
                region_forecast = db.collect_region_forecast(db_conn, region, interval, scheduler_time=scheduler_time)
                
                if region_forecast:
                    formatted_region_forecast = []
                    for point in region_forecast:
                        if len(point) >= 3:
                            formatted_region_forecast.append([point[0], point[1], float(point[2])])
                    region_forecasts[region] = formatted_region_forecast
                    logger.info(f"Fetched {len(formatted_region_forecast)} data points for region {region}")
                else:
                    logger.warning(f"No data found for region {region}")
                    region_forecasts[region] = []
            
            # Close database connection
            db_conn.close()
            
            # Prepare response
            response_data = {
                'duration_hours': interval,
                'generated_at': datetime.now(pytz.timezone('UTC')).isoformat(),
                'min_forecast': {
                    'forecast_data': formatted_min_forecast
                },
                'region_forecasts': {}
            }
            
            # Add region forecasts
            for region, forecast_data in region_forecasts.items():
                response_data['region_forecasts'][region] = {
                    'forecast_data': forecast_data
                }
            
            # Save to file
            output_filename = f"forecast_{interval}h.json"
            output_filepath = os.path.join(storage_path, output_filename)
            with open(output_filepath, 'w') as f:
                json.dump(response_data, f, indent=2)
            
            logger.info(f"Saved forecast data to: {output_filepath}")
            
            # Send response - return the actual data structure, not metadata
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            # Return the actual forecast data structure
            self.wfile.write(json.dumps(response_data, indent=2).encode())
            
        except Exception as e:
            logger.error(f"Error in combined min-forecast query: {str(e)}")
            self.send_response(500)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            response = {'status': 'error', 'message': str(e)}
            self.wfile.write(json.dumps(response).encode())
    
    def do_POST(self):
        # Get the content length
        content_length = int(self.headers['Content-Length'])
        # Read the POST data
        post_data = self.rfile.read(content_length)
        
        try:
            # Parse the JSON data
            data = json.loads(post_data.decode('utf-8'))
            
            # Get storage path from environment variable
            storage_path = os.getenv('STORAGE_PATH', '/storage')
            os.makedirs(storage_path, exist_ok=True)

            duration = data.get('duration')
            start_time = data.get('start_time')  # optional: unix timestamp to override SCHEDULER_TIME

            if duration is None:
                raise ValueError("Invalid request: must provide 'duration' parameter (e.g., {\"duration\": 24})")

            # Combined min-forecast query: returns min forecast + forecasts for all regions in min forecast
            logger.info(f"Processing forecast request for duration: {duration} hours, start_time: {start_time}")
            self.handle_combined_min_forecast(duration, storage_path, start_time_override=start_time)
            return
            
        except Exception as e:
            logger.error(f"Error processing request: {str(e)}")
            self.send_response(500)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            response = {'status': 'error', 'message': str(e)}
            self.wfile.write(json.dumps(response).encode())

    def do_GET(self):
        # Handle GET requests to retrieve files
        try:
            # Parse the path to get the requested file
            path = self.path.strip('/')
            
            # If no specific file is requested, return a list of available files
            if not path or path == '':
                storage_path = os.getenv('STORAGE_PATH', '/storage')
                files = os.listdir(storage_path)
                
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                response = {
                    'status': 'success',
                    'message': 'Available files',
                    'files': files
                }
                self.wfile.write(json.dumps(response).encode())
                return
            
            # Get the requested file
            storage_path = os.getenv('STORAGE_PATH', '/storage')
            file_path = os.path.join(storage_path, path)
            
            # Check if file exists
            if not os.path.exists(file_path):
                self.send_response(404)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                response = {'status': 'error', 'message': f'File {path} not found'}
                self.wfile.write(json.dumps(response).encode())
                return
            
            # Determine content type based on file extension
            content_type = 'application/octet-stream'
            if file_path.endswith('.html'):
                content_type = 'text/html'
            elif file_path.endswith('.json'):
                content_type = 'application/json'
            
            # Send the file
            self.send_response(200)
            self.send_header('Content-type', content_type)
            self.end_headers()
            
            with open(file_path, 'rb') as f:
                self.wfile.write(f.read())
                
        except Exception as e:
            logger.error(f"Error handling GET request: {str(e)}")
            self.send_response(500)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            response = {'status': 'error', 'message': str(e)}
            self.wfile.write(json.dumps(response).encode())

def run_server(port=8008):
    """Run the server in the main thread"""
    server_address = ('0.0.0.0', port)  # Listen on all interfaces
    httpd = HTTPServer(server_address, CarbonDataHandler)
    logger.info(f"Starting metadata server on {server_address} on port {port}")
    httpd.serve_forever()

if __name__ == "__main__":
    port = int(os.getenv('SERVER_PORT', 8008))
    run_server(port)

