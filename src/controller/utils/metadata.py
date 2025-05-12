from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import base64
from datetime import datetime
import os
import logging
from threading import Thread
import numpy as np
import matplotlib.pyplot as plt
import pytz
from io import BytesIO
from db import *

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class CarbonDataHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        # Get the content length
        content_length = int(self.headers['Content-Length'])
        # Read the POST data
        post_data = self.rfile.read(content_length)
        
        try:
            # Parse the JSON data
            data = json.loads(post_data.decode('utf-8'))
            
            # Log the received data
            logger.info(f"Received request for pod: {data.get('pod_name')} in region: {data.get('pod_region')}")
            
            # Get storage path from environment variable
            storage_path = os.getenv('STORAGE_PATH', '/storage')
            os.makedirs(storage_path, exist_ok=True)

            # Process pod data
            pod_region = data.get('pod_region')
            pod_start_time = datetime.fromisoformat(data.get('start_time'))
            pod_end_time = datetime.fromisoformat(data.get('end_time'))
            pod_name = data.get('pod_name')

            # Connect to database
            try:
                db_conn = connect_to_db(db_config)
                
                # Calculate interval in hours
                interval = int((pod_end_time - pod_start_time).total_seconds() / 3600)
                
                # Fetch data from database
                pod_carbon = collect_region_forecast(db_conn, pod_region, interval)
                min_forecast, _ = collect_carbon_forecast(db_conn, interval)
                
                # Format data for plotting
                pod_carbon = [[point[0], 100, point[2]] for point in pod_carbon]  # Adding a placeholder value of 100
                min_forecast = [[point[0], 100, point[2]] for point in min_forecast]  # Adding a placeholder value of 100

                if pod_end_time < datetime.now(pytz.timezone('UTC')):
                    logger.info(f"Error: Pod {pod_name} has extended past its duration")
                else:
                    # Calculate cumulative sums
                    pod_carbon_cumsum = np.cumsum([point[2] for point in pod_carbon])
                    min_forecast_cumsum = np.cumsum([point[2] for point in min_forecast])

                    # Create the plot
                    plt.figure(figsize=(12, 6))
                    plt.plot([point[0] for point in pod_carbon], pod_carbon_cumsum, label=f'Cumulative Carbon Intensity - {pod_region}')
                    plt.plot([point[0] for point in min_forecast], min_forecast_cumsum, label='Cumulative Minimum Carbon Intensity')
                    
                    plt.xlabel('Time')
                    plt.ylabel('Cumulative Carbon Intensity')
                    plt.title(f'Cumulative Carbon Intensity Over Time - Pod: {pod_name}')
                    plt.xticks(rotation=45)
                    plt.legend()
                    plt.grid(True)
                    
                    # Adjust layout to prevent label cutoff
                    plt.tight_layout()
                    
                    # Save the plot locally
                    plot_filename = os.path.join(storage_path, f'plot_{pod_name}.png')
                    plt.savefig(plot_filename)
                    
                    # Convert plot to base64 for response
                    buffer = BytesIO()
                    plt.savefig(buffer, format='png')
                    buffer.seek(0)
                    plot_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
                    buffer.close()
                    
                    # Save raw data to JSON
                    raw_data = {
                        'pod_name': pod_name,
                        'pod_region': pod_region,
                        'start_time': pod_start_time.isoformat(),
                        'end_time': pod_end_time.isoformat(),
                        'carbon_intensity_data': pod_carbon,
                        'min_forecast_data': min_forecast
                    }
                    
                    raw_data_filename = os.path.join(storage_path, f"raw_data_{pod_name}_{pod_region}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
                    with open(raw_data_filename, 'w') as f:
                        json.dump(raw_data, f, indent=2)
                    
                    plt.close()
                    
                    logger.info(f"Generated carbon intensity plot: {plot_filename}")
                    logger.info(f"Saved raw data to: {raw_data_filename}")
                
                # Close database connection
                db_conn.close()
                
            except Exception as db_error:
                logger.error(f"Database error: {str(db_error)}")
                raise
            
            # Send a success response with the plot data
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            response = {
                'status': 'success', 
                'message': 'Data processed successfully',
                'plot_data': plot_base64
            }
            self.wfile.write(json.dumps(response).encode())
            
        except Exception as e:
            logger.error(f"Error processing request: {str(e)}")
            self.send_response(500)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            response = {'status': 'error', 'message': str(e)}
            self.wfile.write(json.dumps(response).encode())

    def do_GET(self):
        # Handle GET requests (for testing the server)
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        response = {'status': 'running', 'message': 'Server is running'}
        self.wfile.write(json.dumps(response).encode())

def run_server(port=8008):
    """Run the server in the main thread"""
    server_address = ('localhost', port)
    httpd = HTTPServer(server_address, CarbonDataHandler)
    logger.info(f"Starting server {server_address} on port {port}")
    httpd.serve_forever()

if __name__ == "__main__":
    port = int(os.getenv('SERVER_PORT', 8008))
    run_server(port) 