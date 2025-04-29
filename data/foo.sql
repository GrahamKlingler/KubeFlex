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