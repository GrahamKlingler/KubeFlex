from datetime import datetime, timedelta
import requests
import json
import time
import psycopg2
import os
import sys
import logging

# logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database connection parameters
db_config = {
    'host': 'db-service',
    'port': 5432,
    'dbname': 'postgres',
    'user': 'sfarokhi',
    'password': 'wordpass'
}

min_query = """
CREATE OR REPLACE FUNCTION get_min_intensity_records(
    start_date TIMESTAMP WITH TIME ZONE,
    end_date TIMESTAMP WITH TIME ZONE
)
RETURNS TEXT[] AS $$
DECLARE
    r RECORD;
    results_array TEXT[] := ARRAY[]::TEXT[];
BEGIN
    FOR r IN
        SELECT source, datetime, carbon_intensity_direct_avg
        FROM public.table
        WHERE datetime::TIMESTAMP WITH TIME ZONE BETWEEN start_date AND end_date
        AND (datetime::TIMESTAMP WITH TIME ZONE, carbon_intensity_direct_avg) IN (
            SELECT datetime::TIMESTAMP WITH TIME ZONE, MIN(carbon_intensity_direct_avg)
            FROM public.table
            WHERE datetime::TIMESTAMP WITH TIME ZONE BETWEEN start_date AND end_date
            GROUP BY datetime::TIMESTAMP WITH TIME ZONE
        )
        ORDER BY datetime::TIMESTAMP WITH TIME ZONE DESC
    LOOP
        results_array := array_append(results_array, 
            r.source || ' | ' || r.datetime || ' | ' || r.carbon_intensity_direct_avg
        );
    END LOOP;

    RETURN results_array;
END;
$$ LANGUAGE plpgsql;
"""

general_query = """
CREATE OR REPLACE FUNCTION get_records_by_source(
    start_date TIMESTAMP,
    end_date TIMESTAMP,
    source_list TEXT[]
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
        AND source = ANY(source_list)
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
def fetch_region_slopes(conn, start_date, end_date, regions):
    try:
        with conn.cursor() as cur:
            cur.execute(general_query)  # Create or replace the function
            cur.execute("SELECT get_records_by_source(%s, %s, %s);", (start_date, end_date, regions))
            result = cur.fetchone()[0]  # [0] because fetchone() returns a tuple
            # logger.info("Fetched results array:", result)

            min_region, min_ts, min_intensity = [], [], [] 
            for record in sorted(result):

                min_region.append(record.split(" | ")[0])
                min_ts.append(record.split(" | ")[1])
                min_intensity.append(float(record.split(" | ")[2]))

            return min_region, min_ts, min_intensity

    except Exception as e:
        logger.info(f"Error fetching results: {e}")