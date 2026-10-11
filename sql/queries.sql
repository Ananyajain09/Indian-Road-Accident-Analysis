-- ============================================================
-- SQL Queries for Indian Road Accident Analysis
-- Database: accidents.db | Table: accidents
-- ============================================================

-- Query 1: City-wise total accidents and fatality rate
-- Shows which cities have the most accidents and how deadly they are
SELECT
    city,
    COUNT(*) AS total_accidents,
    SUM(is_fatal) AS fatal_accidents,
    ROUND(AVG(is_fatal) * 100, 2) AS fatality_rate_pct
FROM accidents
GROUP BY city
ORDER BY total_accidents DESC;

-- Query 2: Hourly accident distribution
-- Helps identify which hours are most dangerous
SELECT
    hour,
    COUNT(*) AS total_accidents,
    SUM(casualties) AS total_casualties
FROM accidents
GROUP BY hour
ORDER BY hour;

-- Query 3: Weather vs fatality rate
-- Shows how weather conditions affect accident severity
SELECT
    weather,
    COUNT(*) AS total_accidents,
    SUM(is_fatal) AS fatal_accidents,
    ROUND(AVG(is_fatal) * 100, 2) AS fatality_rate_pct
FROM accidents
GROUP BY weather
ORDER BY fatality_rate_pct DESC;

-- Query 4: Cause-wise total casualties
-- Identifies the most dangerous causes of accidents
SELECT
    cause,
    COUNT(*) AS total_accidents,
    SUM(casualties) AS total_casualties,
    ROUND(AVG(casualties), 2) AS avg_casualties_per_accident
FROM accidents
GROUP BY cause
ORDER BY total_casualties DESC;

-- Query 5: State ranking using RANK() window function
-- Ranks states by number of accidents
SELECT
    state,
    total_accidents,
    total_casualties,
    RANK() OVER (ORDER BY total_accidents DESC) AS accident_rank
FROM (
    SELECT
        state,
        COUNT(*) AS total_accidents,
        SUM(casualties) AS total_casualties
    FROM accidents
    GROUP BY state
) sub
ORDER BY accident_rank;

-- Query 6: Yearly trend with YoY change using LAG()
-- Shows how accidents change year over year
SELECT
    year,
    total_accidents,
    total_casualties,
    LAG(total_accidents) OVER (ORDER BY year) AS prev_year_accidents,
    ROUND(
        (total_accidents - LAG(total_accidents) OVER (ORDER BY year)) * 100.0
        / LAG(total_accidents) OVER (ORDER BY year), 2
    ) AS yoy_change_pct
FROM (
    SELECT
        year,
        COUNT(*) AS total_accidents,
        SUM(casualties) AS total_casualties
    FROM accidents
    GROUP BY year
) sub
ORDER BY year;
