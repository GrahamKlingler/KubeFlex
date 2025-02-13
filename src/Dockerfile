FROM python:3.9-slim

WORKDIR /app

# Install dependencies
COPY controller/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy script into the container
COPY controller/main.py /app/

# Set the entrypoint to run the script
CMD ["python3", "main.py"]
