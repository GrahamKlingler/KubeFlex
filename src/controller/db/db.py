from datetime import datetime, timedelta
import requests
import json
import time
import psycopg2
import os
import sys
import logging
import pytz

# logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database connection parameters
db_config = {
    'host': os.getenv('DB_HOST', 'db-service'),
    'port': int(os.getenv('DB_PORT', '5432')),
    'dbname': os.getenv('DB_NAME', 'sfarokhi'),
    'user': os.getenv('DB_USER', 'sfarokhi'),
    'password': os.getenv('DB_PASSWORD', 'wordpass')
}

min_query = """
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
"""

region_query = """
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
"""

extended_region_query = """
CREATE OR REPLACE FUNCTION get_extended_records_by_source(
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
        SELECT source, datetime, carbon_intensity_direct_avg,
               COALESCE(power_production_solar_avg, 0) as solar,
               COALESCE(power_production_wind_avg, 0) as wind,
               COALESCE(power_origin_percent_renewable_avg, 0) as pct_renewable
        FROM public.table
        WHERE datetime::TIMESTAMP BETWEEN start_date AND end_date
        AND source = source_region
        ORDER BY datetime::TIMESTAMP ASC
    LOOP
        results_array := array_append(results_array,
            r.source || ' | ' || r.datetime || ' | ' || r.carbon_intensity_direct_avg
            || ' | ' || r.wind || ' | ' || r.solar || ' | ' || r.pct_renewable
        );
    END LOOP;

    RETURN results_array;
END;
$$ LANGUAGE plpgsql;
"""

extended_all_regions_query = """
CREATE OR REPLACE FUNCTION get_extended_records_all_regions(
    start_date TIMESTAMP,
    end_date TIMESTAMP
)
RETURNS TEXT[] AS $$
DECLARE
    r RECORD;
    results_array TEXT[] := ARRAY[]::TEXT[];
BEGIN
    FOR r IN
        SELECT source, datetime, carbon_intensity_direct_avg,
               COALESCE(power_production_solar_avg, 0) as solar,
               COALESCE(power_production_wind_avg, 0) as wind,
               COALESCE(power_origin_percent_renewable_avg, 0) as pct_renewable
        FROM public.table
        WHERE datetime::TIMESTAMP BETWEEN start_date AND end_date
        ORDER BY datetime::TIMESTAMP ASC, source ASC
    LOOP
        results_array := array_append(results_array,
            r.source || ' | ' || r.datetime || ' | ' || r.carbon_intensity_direct_avg
            || ' | ' || r.wind || ' | ' || r.solar || ' | ' || r.pct_renewable
        );
    END LOOP;

    RETURN results_array;
END;
$$ LANGUAGE plpgsql;
"""

# Connect to PostgreSQL database
def connect_to_db(db_params):
    """Connect to PostgreSQL database."""
    try:
        connection = psycopg2.connect(**db_params)
        logger.info("Successfully connected to PostgreSQL database")
        return connection
    except psycopg2.Error as e:
        logger.error(f"Error connecting to PostgreSQL database: {e}")
        raise

# Query the minimum carbon emissions from the db from the given start and end date
def fetch_min_slope(conn, start_date, end_date):
    try:
        with conn.cursor() as cur:
            cur.execute(min_query)  # Create or replace the function
            cur.execute("SELECT get_min_intensity_records(%s, %s);", (start_date, end_date))
            result = cur.fetchone()[0]  # [0] because fetchone() returns a tuple
            # logger.info("Fetched results array:", result)

            final = []
            for record in result:

                min_region = record.split(" | ")[0]
                min_ts = record.split(" | ")[1]
                min_intensity = float(record.split(" | ")[2])
                final.append([min_ts, min_region, min_intensity])

            return sorted(final)

    except Exception as e:
        logger.info(f"Error fetching results: {e}")

# Query the minimum carbon emissions from the db from the given start and end date
def fetch_region_slope(conn, start_date, end_date, region):

    try:
        with conn.cursor() as cur:
            cur.execute(region_query)
            cur.execute("SELECT get_records_by_source(%s, %s, %s);", (start_date, end_date, region))
            result = cur.fetchone()[0]  # [0] because fetchone() returns a tuple
            # logger.info("Fetched results array:", result)

            final = []
            for record in sorted(result):

                min_region = record.split(" | ")[0]
                min_ts = record.split(" | ")[1]
                min_intensity = float(record.split(" | ")[2])
                final.append([min_ts, min_region, min_intensity])
            return sorted(final)

    except Exception as e:
        logger.info(f"Error fetching results: {e}")

# Collects the carbon forecast for the minimum regions over the interval
def collect_carbon_forecast(db_conn, interval=24, scheduler_time=None):
    # Use scheduler time if provided, otherwise use current time minus three years
    if scheduler_time is not None:
        # scheduler_time is a Unix timestamp
        current_date = datetime.fromtimestamp(float(scheduler_time), tz=pytz.timezone('UTC'))
    else:
        # Fallback: Current date (UTC) minus three years
        current_date = datetime.now(pytz.timezone('UTC')) - timedelta(days=365 * 3)
    current_date_str = current_date.strftime("%Y-%m-%d %H:%M:%S")

    epoch = current_date + timedelta(hours=int(interval))
    epoch_str = epoch.strftime("%Y-%m-%d %H:%M:%S")

    db_min = []
    breakpoints = []

    # Get the minimum carbon emissions from the db
    try:
        db_min = fetch_min_slope(db_conn, current_date_str, epoch_str)
        logger.info(f"Minimum carbon emissions in the given time range {current_date_str} to {epoch_str}:")
        
        if db_min:
            for i in range(len(db_min)):    
                timestamp_str = db_min[i][0].split('+')[0]
                # If scheduler_time was provided, the timestamp is already in the correct year
                # Otherwise, add 3 years to convert from historical data to current time
                if scheduler_time is None:
                    db_min[i][0] = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S") + timedelta(days=365*3)
                    db_min[i][0] = db_min[i][0].strftime("%Y-%m-%d %H:%M:%S")
                else:
                    # Timestamp is already in the correct year (2020-2022 range)
                    db_min[i][0] = timestamp_str
                logger.info(f"Timestamp: {db_min[i][0]}, Region: {db_min[i][1]}, Intensity: {db_min[i][2]}")

            # Go through the db_min and check if the region is different from the previous one
            for i in range(1, len(db_min)):
                if db_min[i][1] != db_min[i-1][1]:
                    breakpoints.append(db_min[i])
        
            logger.info(f"Breakpoints: {breakpoints}")

        else:
            logger.info("No records found in the database for the given time range")
    except Exception as e:
        logger.info(f"Error fetching results: {e}")
    
    return db_min, breakpoints

# Collects the carbon forecast for a single region
def collect_region_forecast(db_conn, region, interval=24, scheduler_time=None):
    # Use scheduler time if provided, otherwise use current time minus three years
    if scheduler_time is not None:
        # scheduler_time is a Unix timestamp
        current_date = datetime.fromtimestamp(float(scheduler_time), tz=pytz.timezone('UTC'))
    else:
        # Fallback: Current date (UTC) minus three years
        current_date = datetime.now(pytz.timezone('UTC')) - timedelta(days=365 * 3)
    current_date_str = current_date.strftime("%Y-%m-%d %H:%M:%S")

    epoch = current_date + timedelta(hours=int(interval))
    epoch_str = epoch.strftime("%Y-%m-%d %H:%M:%S")

    db_region = []

    # Get the carbon emissions for the region from the db
    try:
        db_region = fetch_region_slope(db_conn, current_date_str, epoch_str, region)
        logger.info(f"Carbon emissions for region {region} in the given time range {current_date_str} to {epoch_str}:")
        
        if db_region:
            for i in range(len(db_region)):    
                timestamp_str = db_region[i][0].split('+')[0]
                # If scheduler_time was provided, the timestamp is already in the correct year
                # Otherwise, add 3 years to convert from historical data to current time
                if scheduler_time is None:
                    db_region[i][0] = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S") + timedelta(days=365*3)
                    db_region[i][0] = db_region[i][0].strftime("%Y-%m-%d %H:%M:%S")
                else:
                    # Timestamp is already in the correct year (2020-2022 range)
                    db_region[i][0] = timestamp_str
                logger.info(f"Timestamp: {db_region[i][0]}, Region: {db_region[i][1]}, Intensity: {db_region[i][2]}")
        else:
            logger.info("No records found in the database for the given time range and region")
    except Exception as e:
        logger.info(f"Error fetching results: {e}")
    
    return db_region


def fetch_extended_region_data(conn, start_date, end_date, region=None):
    """Fetch extended carbon data including wind, solar, and renewable percentage.

    Returns list of [timestamp, region, intensity, wind, solar, pct_renewable].
    If region is None, fetches data for all regions.
    """
    try:
        with conn.cursor() as cur:
            if region:
                cur.execute(extended_region_query)
                cur.execute("SELECT get_extended_records_by_source(%s, %s, %s);",
                            (start_date, end_date, region))
            else:
                cur.execute(extended_all_regions_query)
                cur.execute("SELECT get_extended_records_all_regions(%s, %s);",
                            (start_date, end_date))

            result = cur.fetchone()[0]

            final = []
            if result:
                for record in result:
                    parts = record.split(" | ")
                    if len(parts) >= 6:
                        final.append([
                            parts[1],           # timestamp
                            parts[0],           # region
                            float(parts[2]),    # carbon_intensity_direct_avg
                            float(parts[3]),    # wind
                            float(parts[4]),    # solar
                            float(parts[5]),    # pct_renewable
                        ])
            return sorted(final)

    except Exception as e:
        logger.info(f"Error fetching extended region data: {e}")
        return []

