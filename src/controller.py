import psycopg2
import random
import datetime as date
import sys

do_block = """ 

CREATE OR REPLACE FUNCTION get_min_intensity_records(start_date TIMESTAMP, end_date TIMESTAMP)
RETURNS TEXT[] AS $$
DECLARE
    r RECORD;
    results_array TEXT[] := ARRAY[]::TEXT[];
BEGIN
    FOR r IN
        SELECT source, datetime, carbon_intensity_direct_avg
        FROM public.table
        WHERE CAST(datetime AS TIMESTAMP) BETWEEN start_date AND end_date
          AND (CAST(datetime AS TIMESTAMP), carbon_intensity_direct_avg) IN (
              SELECT CAST(datetime AS TIMESTAMP), MIN(carbon_intensity_direct_avg)
              FROM public.table
              WHERE CAST(datetime AS TIMESTAMP) BETWEEN start_date AND end_date
              GROUP BY CAST(datetime AS TIMESTAMP)
          )
        ORDER BY CAST(datetime AS TIMESTAMP) DESC
    LOOP
        results_array := array_append(results_array, 
            r.source || ' | ' || r.datetime || ' | ' || r.carbon_intensity_direct_avg
        );
    END LOOP;

    RETURN results_array;
END;
$$ LANGUAGE plpgsql;

"""

# Database connection parameters
db_config = {
    'host': 'localhost',
    'port': 5432,
    'dbname': 'sfarokhi',
    'user': 'sfarokhi'
}

def min_slope(start_date, end_date):
    try:
        conn = psycopg2.connect(**db_config)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT get_min_intensity_records('2020-01-01', '2020-01-02');"
            )
            result = cur.fetchone()[0]  # [0] because fetchone() returns a tuple
            # print("Fetched results array:", result)
            return result

    except Exception as e:
        print(f"Error fetching results: {e}")
    finally:
        if conn:
            conn.close()
            print("Database connection closed.")

if __name__ == "__main__":
    
    start_bound = f"2020-01-01 00:00:00"
    end_bound = f"2022-12-31 23:00:00"
    format_string = "%Y-%m-%d %H:%M:%S"

    start_year = random.randint(2020, 2021)
    start_month = random.randint(1, 12)
    start_day = random.randint(1, 28)
    start_hour = random.randint(0, 23)
    start_minute = random.randint(0, 59)

    start_date = date.datetime.strptime(f"{start_year:02d}-{start_month:02d}-{start_day:02d} {start_hour:02d}:{start_minute:02d}:00", \
                                      format_string)
    
    end_date = start_date + date.timedelta(hours=random.randint(1, 36))

    print(f"Start Date: {start_date.strftime(format_string)}")
    print(f"End Date: {end_date.strftime(format_string)}")

    min_regions = min_slope(start_date, end_date)
    print("Records from database:")
    
    min_region, min_ts, min_intensity = [], [], [] 
    for record in sorted(min_regions):

        min_region.append(record.split(" | ")[0])
        min_ts.append(record.split(" | ")[1])
        min_intensity.append(float(record.split(" | ")[2]))

    print(f"Regions with minimum carbon intensity: {set(min_region)}")
