from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import base64
from datetime import datetime, timedelta
import os
import logging
from threading import Thread
import numpy as np
import matplotlib.pyplot as plt
import pytz
from io import BytesIO
from db import *
from kubeapi import *

import plotly.graph_objects as go
from plotly.subplots import make_subplots

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# To access the server, forward the port 8008 to your local machine:
#   kubectl port-forward svc/metadata-service 8008:8008

# To create a plot, run the following command:
#   curl -X POST http://localhost:8008 -H "Content-Type: application/json" -d '{"pod_name": "test-pod", "pod_region": "TEN", "pod_namespace": "foo"}'

# To access the plots, run the following command:
#   curl http://localhost:8008/plot_test-pod.html -o plot.html

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
            pod_name = data.get('pod_name')
            pod_namespace = data.get('pod_namespace')

            # Get pod information from Kubernetes
            resources = list_resources(pod_namespace)
            pod_info = next((r for r in resources if \
                            r['name'] == pod_name and \
                            r['annotations']['REGION'] == pod_region), None)
            
            if not pod_info:
                raise ValueError(f"Pod {pod_name} not found in Kubernetes cluster")

            # Calculate start and end times from pod age
            pod_start_time = pod_info['age']
            pod_end_time = pod_start_time + timedelta(hours=int(pod_info['annotations']['EXPECTED_DURATION']))

            # Connect to database
            try:
                db_conn = connect_to_db(db_config)
                
                # Calculate interval in hours
                interval = int((pod_end_time - pod_start_time).total_seconds() / 3600)
                logger.info(f"Pod start time: {pod_start_time}")
                logger.info(f"Pod end time: {pod_end_time}")

                # Fetch data from database
                pod_carbon = collect_region_forecast(db_conn, pod_region, interval)
                min_forecast, _ = collect_carbon_forecast(db_conn, interval)
                
                # Format data for plotting
                pod_carbon = [[point[0], 100, point[2]] for point in pod_carbon]
                min_forecast = [[point[0], 100, point[2]] for point in min_forecast]

                if pod_end_time < datetime.now(pytz.timezone('UTC')):
                    logger.info(f"Error: Pod {pod_name} has extended past its duration")
                else:
                    # Create the plot using Plotly
                    fig = go.Figure()
                    
                    # Add traces for carbon intensity
                    fig.add_trace(go.Scatter(
                        x=[point[0] for point in pod_carbon],
                        y=[point[2] for point in pod_carbon],
                        name=f'Carbon Intensity - {pod_region}',
                        mode='lines',
                        line=dict(width=2)
                    ))
                    
                    fig.add_trace(go.Scatter(
                        x=[point[0] for point in min_forecast],
                        y=[point[2] for point in min_forecast],
                        name='Minimum Carbon Intensity',
                        mode='lines',
                        line=dict(width=2)
                    ))
                    
                    # Update layout
                    fig.update_layout(
                        title=f'Carbon Intensity Over Time - Pod: {pod_name}',
                        xaxis_title='Time',
                        yaxis_title='Carbon Intensity',
                        template='plotly_white',
                        height=600,
                        width=1000,
                        showlegend=True,
                        hovermode='x unified'
                    )
                    
                    # Add range slider for better time navigation
                    fig.update_xaxes(
                        rangeslider_visible=True,
                        rangeselector=dict(
                            buttons=list([
                                dict(count=1, label="1h", step="hour", stepmode="backward"),
                                dict(count=6, label="6h", step="hour", stepmode="backward"),
                                dict(count=12, label="12h", step="hour", stepmode="backward"),
                                dict(count=1, label="1d", step="day", stepmode="backward"),
                                dict(step="all")
                            ])
                        )
                    )
                    
                    # Save the plot as HTML
                    plot_filename = os.path.join(storage_path, f'plot_{pod_name}.html')
                    fig.write_html(plot_filename)
                    
                    # Get the HTML content
                    html_content = fig.to_html(include_plotlyjs=True, full_html=True)
                    
                    # Save raw data to JSON
                    raw_data = {
                        'pod_name': pod_name,
                        'pod_region': pod_region,
                        'start_time': pod_start_time.isoformat(),
                        'end_time': pod_end_time.isoformat(),
                        'carbon_intensity_data': pod_carbon,
                        'min_forecast_data': min_forecast,
                        'plot_path': plot_filename
                    }
                    
                    raw_data_filename = os.path.join(storage_path, f"raw_data_{pod_name}_{pod_region}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
                    with open(raw_data_filename, 'w') as f:
                        json.dump(raw_data, f, indent=2)
                    
                    logger.info(f"Generated carbon intensity plot: {plot_filename}")
                    logger.info(f"Saved raw data to: {raw_data_filename}")
                
                # Close database connection
                db_conn.close()
                
            except Exception as db_error:
                logger.error(f"Database error: {str(db_error)}")
                raise
            
            # Send a success response with the plot file path
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            response = {
                'status': 'success', 
                'message': 'Data processed successfully',
                'plot_path': plot_filename
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
    server_address = ('localhost', port)
    httpd = HTTPServer(server_address, CarbonDataHandler)
    logger.info(f"Starting server {server_address} on port {port}")
    httpd.serve_forever()

if __name__ == "__main__":
    port = int(os.getenv('SERVER_PORT', 8008))
    run_server(port) 